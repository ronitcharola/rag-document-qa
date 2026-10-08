"""
vector_store.py — ChromaDB interface for storing and querying chunk embeddings.

ChromaDB is run in persistent mode (./chroma_db).  All documents share one
collection ("rag_documents") partitioned by metadata filters.

Cosine similarity is used (ChromaDB's default when using "cosine" space).
ChromaDB returns *distances* (0 = identical, 2 = opposite); we convert them
to similarity scores in [0, 1] using:  similarity = 1 - (distance / 2)
"""

import chromadb
from chromadb import Settings as ChromaSettings
from typing import Any

from app.config import settings as app_settings

# ---------------------------------------------------------------------------
# Client / collection singleton
# ---------------------------------------------------------------------------

_chroma_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None

COLLECTION_NAME = "rag_documents"


def _get_collection() -> chromadb.Collection:
    """Return (or lazily create) the ChromaDB collection."""
    global _chroma_client, _collection
    if _collection is None:
        _chroma_client = chromadb.PersistentClient(
            path=app_settings.chroma_db_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        _collection = _chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},  # use cosine similarity
        )
    return _collection


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_chunks(chunks: list[dict[str, Any]], embeddings: list[list[float]]) -> None:
    """
    Upsert chunk embeddings and metadata into ChromaDB.

    Args:
        chunks:     List of chunk dicts (from chunker.py).
        embeddings: Parallel list of float vectors.
    """
    collection = _get_collection()

    ids:        list[str]             = []
    vectors:    list[list[float]]     = []
    documents:  list[str]             = []
    metadatas:  list[dict[str, Any]]  = []

    for chunk, vector in zip(chunks, embeddings):
        # Unique ID: combine document_id and chunk_id to support multi-doc.
        chroma_id = f"{chunk['document_id']}::{chunk['chunk_id']}"
        ids.append(chroma_id)
        vectors.append(vector)
        documents.append(chunk["text"])
        metadatas.append(
            {
                "document_id":   chunk["document_id"],
                "document_name": chunk["document_name"],
                "page":          chunk["page"],
                "chunk_id":      chunk["chunk_id"],
                "chunk_index":   chunk["chunk_index"],
            }
        )

    collection.upsert(
        ids=ids,
        embeddings=vectors,
        documents=documents,
        metadatas=metadatas,
    )


def query_chunks(
    query_embedding: list[float],
    top_k: int,
    document_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Find the top_k most similar chunks.

    Args:
        query_embedding: Float vector of the user's question.
        top_k:           Number of results to return.
        document_id:     If set, restrict results to this document.

    Returns:
        List of result dicts sorted by similarity (descending), each with:
            text, document_id, document_name, page, chunk_id, chunk_index, score
    """
    collection = _get_collection()

    where_filter = {"document_id": document_id} if document_id else None

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count() or 1),
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )

    hits: list[dict[str, Any]] = []
    if not results["ids"] or not results["ids"][0]:
        return hits

    for chroma_id, doc, meta, dist in zip(
        results["ids"][0],
        results["documents"][0],  # type: ignore[index]
        results["metadatas"][0],  # type: ignore[index]
        results["distances"][0],  # type: ignore[index]
    ):
        # Convert cosine distance [0, 2] → similarity [0, 1]
        similarity = max(0.0, 1.0 - dist / 2.0)
        hits.append(
            {
                "text":          doc,
                "document_id":   meta["document_id"],
                "document_name": meta["document_name"],
                "page":          meta["page"],
                "chunk_id":      meta["chunk_id"],
                "chunk_index":   meta["chunk_index"],
                "score":         round(similarity, 4),
            }
        )

    # Already sorted by distance (ascending) → similarity (descending)
    return hits


def list_documents() -> list[dict[str, Any]]:
    """
    Return one entry per unique document_id stored in the collection.
    Each entry: {document_id, document_name, chunks}.
    """
    collection = _get_collection()

    if collection.count() == 0:
        return []

    # Fetch all metadata (no embeddings needed)
    all_items = collection.get(include=["metadatas"])
    metadatas = all_items.get("metadatas") or []

    # Aggregate by document_id
    doc_map: dict[str, dict[str, Any]] = {}
    for meta in metadatas:
        doc_id = meta["document_id"]
        if doc_id not in doc_map:
            doc_map[doc_id] = {
                "document_id":   doc_id,
                "document_name": meta["document_name"],
                "chunks":        0,
            }
        doc_map[doc_id]["chunks"] += 1

    return list(doc_map.values())


def delete_document(document_id: str) -> int:
    """
    Delete all chunks belonging to document_id.
    Returns the number of chunks deleted.
    """
    collection = _get_collection()

    # Find all chunk IDs for this document
    existing = collection.get(
        where={"document_id": document_id},
        include=[],  # only need ids
    )
    ids_to_delete = existing.get("ids") or []

    if ids_to_delete:
        collection.delete(ids=ids_to_delete)

    return len(ids_to_delete)
