"""
schemas.py — Pydantic models for all API request and response bodies.
"""

from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Document upload
# ---------------------------------------------------------------------------

class UploadResponse(BaseModel):
    """Returned after a successful document upload and indexing."""
    document_id: str
    filename: str
    pages: int
    chunks: int


class DocumentInfo(BaseModel):
    """One entry in the GET /documents list."""
    document_id: str
    filename: str
    chunks: int


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """Request body for POST /chat."""
    question: str = Field(..., min_length=1, description="The question to ask.")
    top_k: Optional[int] = Field(None, ge=1, le=20, description="Override the default TOP_K.")
    document_id: Optional[str] = Field(None, description="Restrict search to one document.")


class SourceReference(BaseModel):
    """A single retrieved chunk that contributed to the answer."""
    document: str       # original filename
    page: int           # 1-based page number
    chunk_id: str       # e.g. "chunk_03"
    score: float        # cosine similarity 0-1


class ChatResponse(BaseModel):
    """Response body for POST /chat."""
    answer: str
    sources: list[SourceReference]
