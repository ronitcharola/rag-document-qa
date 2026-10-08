"""
loader.py — Extract text from PDF, DOCX, and TXT files.

Each function returns a list of page dicts:
    [{"page": 1, "text": "..."}, {"page": 2, "text": "..."}, ...]

PDF:  PyMuPDF (fitz) — preserves page numbers exactly.
DOCX: python-docx — all content treated as page 1 (no native page concept).
TXT:  plain open() with utf-8, fallback to latin-1 — treated as page 1.
"""

from pathlib import Path
from typing import Any

import fitz          # PyMuPDF
import docx          # python-docx


def load_pdf(file_path: Path) -> list[dict[str, Any]]:
    """Extract text from each page of a PDF using PyMuPDF."""
    pages: list[dict[str, Any]] = []
    with fitz.open(str(file_path)) as doc:
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text("text")  # plain text extraction
            pages.append({"page": page_num, "text": text})
    return pages


def load_docx(file_path: Path) -> list[dict[str, Any]]:
    """Extract text from a DOCX file. All content maps to page 1."""
    document = docx.Document(str(file_path))
    # Join all paragraph texts; preserve paragraph breaks with newlines.
    full_text = "\n".join(
        para.text for para in document.paragraphs if para.text.strip()
    )
    return [{"page": 1, "text": full_text}]


def load_txt(file_path: Path) -> list[dict[str, Any]]:
    """Read a plain-text file. Falls back to latin-1 if utf-8 fails."""
    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = file_path.read_text(encoding="latin-1")
    return [{"page": 1, "text": text}]


def load_document(file_path: Path) -> list[dict[str, Any]]:
    """
    Dispatch to the correct loader based on file extension.
    Raises ValueError for unsupported types.
    """
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return load_pdf(file_path)
    elif suffix == ".docx":
        return load_docx(file_path)
    elif suffix == ".txt":
        return load_txt(file_path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")
