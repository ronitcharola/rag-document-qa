"""
chunker.py — Split cleaned page text into overlapping chunks.

Algorithm:
  - Sliding window over characters (not tokens).
    CHUNK_SIZE characters wide, CHUNK_OVERLAP characters of overlap.
  - Each page is chunked independently so chunks NEVER cross page boundaries.
  - Every chunk carries full metadata needed for citation.

Chunk metadata schema:
    {
        "document_id":   str,   # UUID assigned at upload
        "document_name": str,   # original filename
        "page":          int,   # 1-based page number
        "chunk_id":      str,   # "chunk_01", "chunk_02", ...  (global within doc)
        "chunk_index":   int,   # 0-based integer index
        "text":          str,   # the chunk content
    }
"""

from typing import Any

from app.config import settings


def chunk_text(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """
    Split *text* into overlapping windows of *chunk_size* characters,
    advancing by (chunk_size - chunk_overlap) each step.
    Returns an empty list if the input is empty.
    """
    if not text.strip():
        return []

    step = chunk_size - chunk_overlap
    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start += step

    return chunks


def chunk_pages(
    pages: list[dict[str, Any]],
    document_id: str,
    document_name: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[dict[str, Any]]:
    """
    Chunk all pages of a document and attach metadata to each chunk.

    Args:
        pages:         Output of loader (list of {page, text} dicts).
        document_id:   UUID string for this document.
        document_name: Original filename.
        chunk_size:    Override settings.chunk_size if provided.
        chunk_overlap: Override settings.chunk_overlap if provided.

    Returns:
        List of chunk dicts, each with full metadata + text.
    """
    cs = chunk_size or settings.chunk_size
    co = chunk_overlap or settings.chunk_overlap

    all_chunks: list[dict[str, Any]] = []
    global_index = 0  # chunk index across the whole document

    for page_dict in pages:
        page_num: int = page_dict["page"]
        page_text: str = page_dict["text"]

        for chunk_text_str in chunk_text(page_text, cs, co):
            chunk_id = f"chunk_{global_index + 1:02d}"
            all_chunks.append(
                {
                    "document_id":   document_id,
                    "document_name": document_name,
                    "page":          page_num,
                    "chunk_id":      chunk_id,
                    "chunk_index":   global_index,
                    "text":          chunk_text_str,
                }
            )
            global_index += 1

    return all_chunks
