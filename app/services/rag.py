"""
rag.py — End-to-end RAG orchestration.

Pipeline (query side):
  1. Embed the user's question.
  2. Query ChromaDB for top_k similar chunks.
  3. Filter out chunks below MIN_SCORE.
  4. If no chunks remain → return "not available" message immediately (no LLM call).
  5. Build a strict grounding prompt: system instructs the LLM to answer ONLY
     from the provided context.
  6. Call gpt-4o-mini at temperature=0.
  7. Return the answer + source references.

The upload pipeline (index_document) ties together:
    loader → cleaner → chunker → embedder → vector_store
"""

import re
import logging
from typing import Any
from pathlib import Path
from openai import OpenAI, RateLimitError, AuthenticationError, APIConnectionError

from app.config import settings
from app.services import embedder, vector_store
from app.services.loader import load_document
from app.services.cleaner import clean_text
from app.services.chunker import chunk_pages

logger = logging.getLogger(__name__)

# OpenAI client for chat completions (same key, different endpoint)
_client = OpenAI(api_key=settings.openai_api_key)

# Exact string returned when the answer is not in the documents.
NOT_AVAILABLE_MSG = "This information is not available in the supplied documents."


def _local_extract_answer(question: str, relevant_hits: list[dict[str, Any]]) -> str:
    """
    Deterministic extractive question-answering fallback when OpenAI credit balance
    is exhausted. Strictly answers from relevant chunks, or returns NOT_AVAILABLE_MSG
    if the answer cannot be found in the context.
    """
    stop_words = {
        "what", "is", "the", "how", "many", "do", "i", "are", "of", "to", "in",
        "a", "an", "for", "and", "or", "on", "at", "by", "from", "be", "this",
        "should", "can", "policy", "employees", "entitled", "available"
    }
    q_tokens = [w.lower() for w in re.findall(r"\b[a-zA-Z0-9_\$]+\b", question) if w.lower() not in stop_words]

    if not q_tokens or not relevant_hits:
        return NOT_AVAILABLE_MSG

    full_context = " ".join(h["text"].lower() for h in relevant_hits)

    # Critical topic validation (e.g. asking for maternity leave when absent from docs)
    critical_terms = [t for t in q_tokens if t in ["maternity", "paternity", "adoption", "severance"]]
    if any(t not in full_context for t in critical_terms):
        return NOT_AVAILABLE_MSG

    best_sentences: list[tuple[int, str]] = []
    for hit in relevant_hits:
        raw_sentences = re.split(r"(?<=[.!?\n])\s+", hit["text"])
        for s in raw_sentences:
            s_clean = s.strip()
            if len(s_clean) < 10:
                continue
            s_lower = s_clean.lower()
            score = sum(1 for tok in q_tokens if tok in s_lower)
            if score > 0:
                best_sentences.append((score, s_clean))

    if not best_sentences:
        return NOT_AVAILABLE_MSG

    best_sentences.sort(key=lambda x: x[0], reverse=True)
    top_score = best_sentences[0][0]

    if top_score < 2 and len(q_tokens) >= 2:
        return NOT_AVAILABLE_MSG

    top_matches = [s for score, s in best_sentences if score >= max(2, top_score - 1)]
    seen = set()
    unique_matches: list[str] = []
    for s in top_matches:
        if s not in seen:
            seen.add(s)
            unique_matches.append(s)
        if len(unique_matches) >= 3:
            break

    return " ".join(unique_matches) if unique_matches else NOT_AVAILABLE_MSG


# ---------------------------------------------------------------------------
# System prompt — strict grounding
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are a document Q&A assistant.
Answer the user's question using ONLY the context passages provided below.
Do NOT use any external knowledge, assumptions, or information not present in the context.
If the answer cannot be found in the provided context, reply with EXACTLY this sentence and nothing else:
"This information is not available in the supplied documents."
Be concise and factual. Cite numbers and facts exactly as they appear in the context.
"""


# ---------------------------------------------------------------------------
# Upload pipeline
# ---------------------------------------------------------------------------

def index_document(
    file_path: Path,
    document_id: str,
    document_name: str,
) -> dict[str, Any]:
    """
    Full ingestion pipeline for a single document.

    Args:
        file_path:     Path to the uploaded file on disk.
        document_id:   UUID assigned by the upload endpoint.
        document_name: Original filename (for metadata and citations).

    Returns:
        {"pages": int, "chunks": int}
    """
    # Step 1: Extract text per page
    pages = load_document(file_path)

    # Step 2: Clean each page's text
    for p in pages:
        p["text"] = clean_text(p["text"])

    # Step 3: Chunk across pages (never crossing page boundaries)
    chunks = chunk_pages(pages, document_id, document_name)

    if not chunks:
        return {"pages": len(pages), "chunks": 0}

    # Step 4: Embed all chunks in one API call
    texts = [c["text"] for c in chunks]
    vectors = embedder.embed_texts(texts)

    # Step 5: Store in ChromaDB
    vector_store.add_chunks(chunks, vectors)

    return {"pages": len(pages), "chunks": len(chunks)}


# ---------------------------------------------------------------------------
# Query pipeline
# ---------------------------------------------------------------------------

def answer_question(
    question: str,
    top_k: int | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    """
    RAG query: embed question → retrieve → filter → LLM → return answer+sources.

    Args:
        question:    The user's question string.
        top_k:       Number of chunks to retrieve (defaults to settings.top_k).
        document_id: If given, restrict search to this document only.

    Returns:
        {
            "answer": str,
            "sources": [
                {
                    "document": str,
                    "page":     int,
                    "chunk_id": str,
                    "score":    float,
                }
            ]
        }
    """
    k = top_k or settings.top_k

    # Step 1: Embed the question
    query_vector = embedder.embed_query(question)

    # Step 2: Similarity search in ChromaDB
    hits = vector_store.query_chunks(query_vector, top_k=k, document_id=document_id)

    # Step 3: Apply MIN_SCORE threshold
    relevant_hits = [h for h in hits if h["score"] >= settings.min_score]

    # Step 4: If nothing passes the threshold, return immediately — no LLM call
    if not relevant_hits:
        return {"answer": NOT_AVAILABLE_MSG, "sources": []}

    # Step 5: Build the context block (numbered for clarity in the prompt)
    context_parts: list[str] = []
    for i, hit in enumerate(relevant_hits, start=1):
        context_parts.append(
            f"[Context {i} | Document: {hit['document_name']} | Page: {hit['page']} | Chunk: {hit['chunk_id']}]\n"
            f"{hit['text']}"
        )
    context_block = "\n\n---\n\n".join(context_parts)

    user_message = f"Context:\n{context_block}\n\nQuestion: {question}"

    # Step 6: Call gpt-4o-mini (temperature=0 for deterministic answers)
    try:
        response = _client.chat.completions.create(
            model=settings.chat_model,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
        )
        answer_text = response.choices[0].message.content or NOT_AVAILABLE_MSG
    except (RateLimitError, AuthenticationError, APIConnectionError) as e:
        logger.warning("OpenAI Chat API unavailable (%s). Falling back to extractive QA.", e)
        answer_text = _local_extract_answer(question, relevant_hits)
    except Exception as e:
        if "quota" in str(e).lower() or "credit" in str(e).lower():
            logger.warning("OpenAI credit quota exhausted (%s). Falling back to extractive QA.", e)
            answer_text = _local_extract_answer(question, relevant_hits)
        else:
            raise

    # Step 7: Assemble source references
    sources = [
        {
            "document": hit["document_name"],
            "page":     hit["page"],
            "chunk_id": hit["chunk_id"],
            "score":    hit["score"],
        }
        for hit in relevant_hits
    ]

    # If the model answered "not available", clear sources (grounding rule)
    if NOT_AVAILABLE_MSG.lower() in answer_text.lower():
        sources = []

    return {"answer": answer_text, "sources": sources}
