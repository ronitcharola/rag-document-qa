"""
test_cases.py — Mandatory RAG test suite.

Uploads the three sample documents, runs 6 test questions against the live
server, prints PASS/FAIL for each, and saves a test_results.md artifact.

Usage (server must be running on http://127.0.0.1:8000):
    python tests/test_cases.py

Requirements:
    pip install requests
"""

import sys
import time
import json
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests

BASE_URL = "http://127.0.0.1:8000"
SAMPLE_DIR = Path(__file__).parent.parent / "sample_docs"
RESULTS_FILE = Path(__file__).parent / "test_results.md"

# Colour helpers (ANSI) — fall back gracefully on non-ANSI terminals
GREEN = "\033[92m"
RED   = "\033[91m"
RESET = "\033[0m"
BOLD  = "\033[1m"


def pass_msg(text: str) -> str:
    return f"{GREEN}PASS{RESET}  {text}"

def fail_msg(text: str) -> str:
    return f"{RED}FAIL{RESET}  {text}"


# ── Test definitions ───────────────────────────────────────────────────────────
# Each test: {id, question, must_contain (ANY of), must_not_contain, expected_source_hint}
TESTS = [
    {
        "id": "TC-01",
        "description": "Annual leave days",
        "question": "How many annual leave days are available?",
        "must_contain": ["24"],
        "must_not_contain": [],
        "expected_source_hint": "company_handbook",
    },
    {
        "id": "TC-02",
        "description": "Sick leave days",
        "question": "How many sick leave days are employees entitled to?",
        "must_contain": ["12"],
        "must_not_contain": [],
        "expected_source_hint": "company_handbook",
    },
    {
        "id": "TC-03",
        "description": "Leave advance notice",
        "question": "How many days in advance should leave be requested?",
        "must_contain": ["3"],
        "must_not_contain": [],
        "expected_source_hint": "company_handbook",
    },
    {
        "id": "TC-04",
        "description": "Health insurance coverage limit",
        "question": "What is the health insurance coverage limit?",
        "must_contain": ["500,000", "500000", "five lakh", "5,00,000"],
        "must_not_contain": [],
        "expected_source_hint": "insurance_policy",
    },
    {
        "id": "TC-05",
        "description": "Maternity leave (not in docs)",
        "question": "What is the maternity leave policy?",
        "must_contain": ["not available in the supplied documents"],
        "must_not_contain": [],
        "expected_source_hint": None,   # sources must be empty
    },
    {
        "id": "TC-06",
        "description": "Password reset steps",
        "question": "How do I reset my password?",
        "must_contain": ["password", "reset", "step"],
        "must_not_contain": [],
        "expected_source_hint": "it_faq",
    },
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def upload_document(file_path: Path) -> dict:
    """Upload a single document and return the response JSON."""
    with open(file_path, "rb") as f:
        mime_map = {".pdf": "application/pdf",
                    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ".txt": "text/plain"}
        mime = mime_map.get(file_path.suffix.lower(), "application/octet-stream")
        resp = requests.post(
            f"{BASE_URL}/documents/upload",
            files={"file": (file_path.name, f, mime)},
            timeout=120,
        )
    resp.raise_for_status()
    return resp.json()


def ask(question: str, top_k: int = 5) -> dict:
    """Send a chat question and return the response JSON."""
    resp = requests.post(
        f"{BASE_URL}/chat",
        json={"question": question, "top_k": top_k},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def evaluate(test: dict, result: dict) -> tuple[bool, list[str]]:
    """
    Check must_contain and source hint.
    Returns (passed: bool, reasons: list[str]).
    """
    answer_lower = result["answer"].lower()
    reasons: list[str] = []

    # Check must_contain — at least ONE phrase must appear
    if test["must_contain"]:
        found = any(phrase.lower() in answer_lower for phrase in test["must_contain"])
        if not found:
            reasons.append(
                f"Answer missing required phrase(s): {test['must_contain']}\n"
                f"    Got: \"{result['answer'][:200]}\""
            )

    # Check must_not_contain
    for phrase in test.get("must_not_contain", []):
        if phrase.lower() in answer_lower:
            reasons.append(f"Answer contains forbidden phrase: \"{phrase}\"")

    # Source hint check
    hint = test.get("expected_source_hint")
    if hint is None:
        # Sources must be empty for "not available" answers
        if result.get("sources"):
            reasons.append(
                f"Expected empty sources for 'not available' answer, "
                f"got: {[s['document'] for s in result['sources']]}"
            )
    else:
        # At least one source must match the hint
        source_docs = [s["document"].lower() for s in result.get("sources", [])]
        if not any(hint in d for d in source_docs):
            reasons.append(
                f"Expected source containing '{hint}', got: {source_docs or '(no sources)'}"
            )

    passed = len(reasons) == 0
    return passed, reasons


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{BOLD}═══════════════════════════════════════{RESET}")
    print(f"{BOLD}  RAG Document Q&A — Test Suite{RESET}")
    print(f"{BOLD}═══════════════════════════════════════{RESET}\n")

    # ── Step 1: Health check ────────────────────────────────────────────────
    print("▶ Checking server health...")
    try:
        resp = requests.get(f"{BASE_URL}/documents", timeout=5)
        resp.raise_for_status()
        print(f"  Server OK at {BASE_URL}\n")
    except Exception as e:
        print(f"  {RED}Cannot reach server: {e}{RESET}")
        print("  Start the server with:  uvicorn app.main:app --reload")
        sys.exit(1)

    # ── Step 2: Upload sample documents ────────────────────────────────────
    print("▶ Uploading sample documents...")
    sample_files = [
        SAMPLE_DIR / "company_handbook.txt",
        SAMPLE_DIR / "insurance_policy.docx",
        SAMPLE_DIR / "it_faq.pdf",
    ]

    uploaded = []
    for fp in sample_files:
        if not fp.exists():
            print(f"  {RED}Missing sample: {fp}{RESET}")
            print("  Run: python generate_samples.py")
            sys.exit(1)
        try:
            info = upload_document(fp)
            print(f"  ✓  {fp.name}  →  {info['chunks']} chunks, {info['pages']} pages")
            uploaded.append(info)
        except Exception as e:
            print(f"  {RED}Upload failed for {fp.name}: {e}{RESET}")
            sys.exit(1)

    print()
    # Allow embeddings to settle
    time.sleep(1)

    # ── Step 3: Run test questions ──────────────────────────────────────────
    print("▶ Running test cases...\n")
    results_rows: list[dict] = []
    pass_count = 0
    fail_count = 0

    for test in TESTS:
        try:
            result = ask(test["question"])
            passed, reasons = evaluate(test, result)
        except Exception as e:
            passed = False
            reasons = [f"Request error: {e}"]
            result = {"answer": "", "sources": []}

        label = pass_msg(test["id"]) if passed else fail_msg(test["id"])
        print(f"  {label}  {test['description']}")
        if not passed:
            for r in reasons:
                print(f"         ↳ {r}")
        else:
            # Show snippet of answer on pass too
            snippet = result["answer"][:120].replace("\n", " ")
            print(f"         → \"{snippet}{'…' if len(result['answer']) > 120 else ''}\"")

        if passed:
            pass_count += 1
        else:
            fail_count += 1

        results_rows.append({
            "test": test,
            "result": result,
            "passed": passed,
            "reasons": reasons,
        })
        print()

    # ── Step 4: Summary ─────────────────────────────────────────────────────
    total = pass_count + fail_count
    print(f"{BOLD}═══════════════════════════════════════{RESET}")
    print(f"  Results: {pass_count}/{total} passed", end="")
    if fail_count == 0:
        print(f"  {GREEN}ALL TESTS PASSED ✓{RESET}")
    else:
        print(f"  {RED}{fail_count} FAILED ✗{RESET}")
    print(f"{BOLD}═══════════════════════════════════════{RESET}\n")

    # ── Step 5: Save test_results.md ────────────────────────────────────────
    write_results_md(results_rows, pass_count, fail_count)
    print(f"  Report saved to: {RESULTS_FILE}\n")


def write_results_md(rows: list[dict], pass_count: int, fail_count: int):
    """Write a markdown test results report."""
    lines = [
        "# RAG Document Q&A — Test Results\n",
        f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}  \n",
        f"**Results:** {pass_count}/{pass_count + fail_count} passed\n\n",
        "---\n\n",
        "| # | Description | Status | Answer (excerpt) | Sources |\n",
        "|---|-------------|--------|------------------|---------|\n",
    ]

    for row in rows:
        t      = row["test"]
        r      = row["result"]
        passed = row["passed"]
        status = "✅ PASS" if passed else "❌ FAIL"
        answer = r.get("answer", "")[:100].replace("|", "\\|").replace("\n", " ")
        if len(r.get("answer", "")) > 100:
            answer += "…"
        sources = ", ".join(s["document"] for s in r.get("sources", [])) or "*(none)*"
        lines.append(f"| {t['id']} | {t['description']} | {status} | {answer} | {sources} |\n")

    lines.append("\n---\n\n## Detailed Results\n\n")
    for row in rows:
        t      = row["test"]
        r      = row["result"]
        passed = row["passed"]
        status = "✅ PASS" if passed else "❌ FAIL"
        lines.append(f"### {t['id']} — {t['description']} {status}\n\n")
        lines.append(f"**Question:** {t['question']}\n\n")
        lines.append(f"**Answer:**\n> {r.get('answer', '').replace(chr(10), '  \n> ')}\n\n")
        if r.get("sources"):
            lines.append("**Sources:**\n")
            for s in r["sources"]:
                lines.append(f"- `{s['document']}` · page {s['page']} · {s['chunk_id']} · score {s['score']:.3f}\n")
        else:
            lines.append("**Sources:** *(none)*\n")
        if not passed:
            lines.append("\n**Failure reasons:**\n")
            for reason in row["reasons"]:
                lines.append(f"- {reason}\n")
        lines.append("\n")

    RESULTS_FILE.write_text("".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
