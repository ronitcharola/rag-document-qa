"""
main.py — FastAPI application entry point.

Routes:
  POST /documents/upload   — upload and index a document
  GET  /documents          — list all indexed documents
  DELETE /documents/{id}   — delete a document and its vectors
  POST /chat               — ask a question, get answer + sources
  GET  /                   — serve the frontend UI
"""

import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.schemas import ChatRequest, ChatResponse, DocumentInfo, SourceReference, UploadResponse
from app.services import rag, vector_store

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="RAG Document Q&A",
    description="Upload documents and ask questions answered strictly from their content.",
    version="1.0.0",
)

# Serve frontend at /static/* (the UI fetches /documents and /chat via JS)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Allowed MIME types for upload
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}

# Map MIME → file extension for saving
MIME_TO_EXT = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_upload_dir() -> Path:
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui():
    """Serve the single-page frontend."""
    html_file = STATIC_DIR / "index.html"
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


@app.post("/documents/upload", response_model=UploadResponse, tags=["Documents"])
async def upload_document(file: UploadFile = File(...)):
    """
    Upload a PDF, DOCX, or TXT file. The document is extracted, chunked,
    embedded and stored in ChromaDB. Returns document metadata.
    """
    # Validate MIME type
    content_type = file.content_type or ""
    # Strip parameters (e.g. "text/plain; charset=utf-8" → "text/plain")
    mime = content_type.split(";")[0].strip()

    if mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{mime}'. Allowed: PDF, DOCX, TXT.",
        )

    # Assign a unique document ID
    document_id = str(uuid.uuid4())
    original_name = file.filename or f"document{MIME_TO_EXT[mime]}"

    # Save to disk temporarily for the loader
    upload_dir = _ensure_upload_dir()
    ext = MIME_TO_EXT[mime]
    save_path = upload_dir / f"{document_id}{ext}"

    try:
        contents = await file.read()
        save_path.write_bytes(contents)

        # Run the full ingestion pipeline
        result = rag.index_document(
            file_path=save_path,
            document_id=document_id,
            document_name=original_name,
        )
    except Exception as exc:
        # Clean up partial file on failure
        if save_path.exists():
            save_path.unlink()
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}") from exc

    return UploadResponse(
        document_id=document_id,
        filename=original_name,
        pages=result["pages"],
        chunks=result["chunks"],
    )


@app.get("/documents", response_model=list[DocumentInfo], tags=["Documents"])
async def list_documents():
    """List all documents currently indexed in the vector store."""
    docs = vector_store.list_documents()
    return [
        DocumentInfo(
            document_id=d["document_id"],
            filename=d["document_name"],
            chunks=d["chunks"],
        )
        for d in docs
    ]


@app.delete("/documents/{document_id}", tags=["Documents"])
async def delete_document(document_id: str):
    """
    Delete a document and all its chunk embeddings from the vector store.
    Also removes the cached file from disk if present.
    """
    deleted_chunks = vector_store.delete_document(document_id)

    if deleted_chunks == 0:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")

    # Remove cached file (any extension)
    upload_dir = Path(settings.upload_dir)
    for ext in MIME_TO_EXT.values():
        cached = upload_dir / f"{document_id}{ext}"
        if cached.exists():
            cached.unlink()

    return {"message": f"Deleted {deleted_chunks} chunks for document '{document_id}'."}


@app.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(request: ChatRequest):
    """
    Ask a question. The answer is grounded strictly in the indexed documents.
    Returns the answer text and the source chunk references.
    """
    result = rag.answer_question(
        question=request.question,
        top_k=request.top_k,
        document_id=request.document_id,
    )

    sources = [
        SourceReference(
            document=s["document"],
            page=s["page"],
            chunk_id=s["chunk_id"],
            score=s["score"],
        )
        for s in result["sources"]
    ]

    return ChatResponse(answer=result["answer"], sources=sources)
