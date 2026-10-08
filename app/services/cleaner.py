"""
cleaner.py — Normalise raw extracted text before chunking.

Steps:
  1. Remove non-printable / control characters (except newlines and tabs).
  2. Replace multiple consecutive blank lines with a single blank line.
  3. Strip leading / trailing whitespace from each line.
  4. Collapse runs of spaces within a line to a single space.
"""

import re


def clean_text(text: str) -> str:
    """
    Return a cleaned version of the input text suitable for chunking.
    Preserves paragraph structure (single blank lines between paragraphs).
    """
    # 1. Remove control characters (keep \n, \t, and printable chars)
    text = re.sub(r"[^\S\n\t]+", " ", text)          # runs of non-newline whitespace → single space
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)  # strip control chars

    # 2. Strip each line
    lines = [line.strip() for line in text.splitlines()]

    # 3. Collapse 3+ consecutive blank lines → 1 blank line
    cleaned_lines: list[str] = []
    blank_count = 0
    for line in lines:
        if line == "":
            blank_count += 1
            if blank_count <= 1:
                cleaned_lines.append(line)
        else:
            blank_count = 0
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()
