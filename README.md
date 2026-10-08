# RAG Document Q&A

A **Retrieval-Augmented Generation (RAG)** application that lets users upload business documents (PDF, DOCX, TXT) and ask questions answered **strictly** from the uploaded content. Every answer cites the source document, page, and chunk. If the information is not in the documents, the system says so — it never hallucinates.

Built with FastAPI, ChromaDB, and OpenAI — **no LangChain or pre-built retrieval chains**; every RAG step is implemented explicitly.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         BROWSER (UI)                             │
│          app/static/index.html  —  plain HTML/CSS/JS             │
└──────────────────────────────┬───────────────────────────────────┘
                               │  HTTP (REST / JSON)
┌──────────────────────────────▼───────────────────────────────────┐
│                   FastAPI  (app/main.py)                          │
│  POST /documents/upload    GET /documents                         │
│  DELETE /documents/{id}    POST /chat                             │
└──┬───────────────┬──────────────┬──────────────┬─────────────────┘
   │               │              │              │
   ▼               ▼              ▼              ▼
loader.py      cleaner.py    chunker.py    embedder.py
PDF→PyMuPDF   whitespace     sliding       OpenAI
DOCX→docx     normalize      window +      text-embedding
TXT→open()               metadata          -3-small
                                               │
                                               ▼
                                        vector_store.py
                                        ChromaDB (cosine)
                                        persistent ./chroma_db
                                               │
                               ┌───────────────┘
                               ▼
                            rag.py
                   embed Q → similarity search
                   → score filter → prompt build
                   → gpt-4o-mini (temp=0)
                   → answer + sources
```

---

## Setup

### Prerequisites
- Python 3.10+
- An [OpenAI API key](https://platform.openai.com/api-keys)

### 1. Clone / enter the project
```bash
cd <project-root>
```

### 2. Create a virtual environment
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment
```bash
copy .env.example .env        # Windows
# cp .env.example .env        # macOS/Linux
```
Edit `.env` and fill in your `OPENAI_API_KEY`. All other defaults are fine for development.

### 5. Generate sample documents
```bash
python generate_samples.py
```
This creates `sample_docs/insurance_policy.docx` and `sample_docs/it_faq.pdf`.

---

## Running the Server

```bash
uvicorn app.main:app --reload
```

Open your browser at **http://127.0.0.1:8000**

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | *(required)* | Your OpenAI secret key |
| `CHAT_MODEL` | `gpt-4o-mini` | OpenAI chat model to use |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model |
| `CHUNK_SIZE` | `800` | Target characters per chunk |
| `CHUNK_OVERLAP` | `150` | Overlap characters between chunks |
| `TOP_K` | `4` | Number of chunks retrieved per query |
| `MIN_SCORE` | `0.30` | Minimum cosine similarity (0–1) to keep a chunk |
| `CHROMA_DB_PATH` | `./chroma_db` | ChromaDB persistence directory |
| `UPLOAD_DIR` | `./uploads` | Temporary upload storage |

---

## API — curl Examples

### Upload a document
```bash
curl -X POST http://127.0.0.1:8000/documents/upload \
  -F "file=@sample_docs/company_handbook.txt"
```

### List documents
```bash
curl http://127.0.0.1:8000/documents
```

### Ask a question
```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "How many annual leave days are available?"}'
```

### Ask with document filter
```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the coverage limit?", "document_id": "<uuid>"}'
```

### Delete a document
```bash
curl -X DELETE http://127.0.0.1:8000/documents/<document_id>
```

---

## Running Tests

With the server running in another terminal:
```bash
python tests/test_cases.py
```

Results are printed to stdout and saved to `tests/test_results.md`.

---

## Technical Notes

### Chunk Size (800 chars) and Overlap (150 chars)
800 characters is approximately 150–180 tokens — well within `text-embedding-3-small`'s 8,191-token context limit, and large enough to capture a complete policy paragraph (typical HR/legal sentences run 40–80 tokens). At this size, each chunk contains enough context to be semantically useful without being so large that it drowns out the specific fact being retrieved.

150-character overlap (~30 tokens) ensures that sentences or bullet points that span a natural split point are captured in at least one adjacent chunk, preventing missed answers at chunk boundaries.

Chunks never cross page boundaries, so page-number citations are always accurate.

### Embedding Model (`text-embedding-3-small`)
`text-embedding-3-small` produces 1,536-dimensional vectors and is the most cost-efficient OpenAI embedding model that still achieves strong retrieval accuracy on English business documents. It outperforms `ada-002` on BEIR benchmarks while costing ~5× less.

### TOP_K = 4
Four chunks provide enough context for multi-part questions (e.g., both the claim limit and the sub-limits for a coverage question) without exceeding the practical input budget of `gpt-4o-mini`. With CHUNK_SIZE=800, four chunks is approximately 3,200 characters (~700 tokens), leaving ample room for the system prompt and response.

### MIN_SCORE = 0.30
The minimum cosine similarity threshold of 0.30 (on a 0–1 scale) filters out chunks that are retrieved purely because of superficial lexical overlap (e.g., the word "policy" appearing in an unrelated section). Below 0.30, retrieved chunks empirically add noise rather than signal. If no chunk clears this threshold, the LLM is **not called at all** — the "not available" message is returned directly, saving API costs.

### Prompt Design
The system prompt forbids the model from using outside knowledge:

> "Answer the user's question using ONLY the context passages provided below. Do NOT use any external knowledge..."

If the answer is not found, the model must reply with the exact string: `"This information is not available in the supplied documents."` This exact-string check allows the application to reliably clear sources from the response.

Context is passed as numbered, labelled passages (`[Context 1 | Document: ... | Page: ...]`), giving the model precise attribution targets.

### Known Limitations
| Limitation | Detail |
|------------|--------|
| **No OCR** | Scanned / image-only PDFs produce no text. PyMuPDF extracts embedded text only. |
| **No PDF table handling** | Tables in PDFs may lose row/column structure during text extraction. |
| **No reranking** | Retrieved chunks are ranked purely by cosine similarity. A cross-encoder reranker (e.g., `ms-marco-MiniLM`) could improve precision. |
| **No hybrid search** | Dense (embedding) retrieval only. Adding BM25 sparse retrieval and fusing scores (RRF) would help keyword-heavy queries. |
| **No streaming** | Answers are returned in full after the LLM completes. Streaming (`stream=True`) would improve perceived latency. |
| **Single-user, in-process** | ChromaDB runs in-process; not suitable for concurrent production load. |

---

## Project Structure

```
app/
  main.py           FastAPI app, 4 endpoints, static mount
  config.py         pydantic-settings — loads .env
  schemas.py        Pydantic request/response models
  services/
    loader.py       Text extraction: PDF/DOCX/TXT
    cleaner.py      Whitespace normalisation
    chunker.py      Sliding-window chunking + metadata
    embedder.py     OpenAI embedding API wrapper
    vector_store.py ChromaDB: add, query, list, delete
    rag.py          End-to-end RAG orchestration
  static/
    index.html      Single-page frontend UI
sample_docs/
  company_handbook.txt
  insurance_policy.docx
  it_faq.pdf
tests/
  test_cases.py     Upload samples, run 6 questions, PASS/FAIL
generate_samples.py Create binary sample documents
requirements.txt
.env.example
.gitignore
README.md
```
