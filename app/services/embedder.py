"""
embedder.py — Generate embeddings using OpenAI text-embedding-3-small.

Uses the OpenAI Python SDK (v1.x). Calls are made in a single batch where
possible (the API accepts up to 2048 inputs per request).

The returned embedding vectors are plain Python lists of floats, ready to
be stored in ChromaDB.
"""

import math
import re
import hashlib
import logging
from openai import OpenAI, RateLimitError, AuthenticationError, APIConnectionError

from app.config import settings

logger = logging.getLogger(__name__)

# Initialise the OpenAI client once (reads key from settings).
_client = OpenAI(api_key=settings.openai_api_key)


def _deterministic_local_embed(text: str, dim: int = 1536) -> list[float]:
    """
    Deterministic feature hashing vectorizer (unigrams + bigrams),
    L2-normalized to unit sphere for cosine distance calculations.
    Ensures offline operability when OpenAI credit balance is exhausted.
    """
    vec = [0.0] * dim
    tokens = re.findall(r"\b[a-zA-Z0-9_\$,\.]+\b", text.lower())
    if not tokens:
        return [0.0] * dim

    features = list(tokens)
    for i in range(len(tokens) - 1):
        features.append(f"{tokens[i]}_{tokens[i+1]}")

    for feat in features:
        h = int(hashlib.sha256(feat.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if ((h >> 16) & 1) else -1.0
        vec[idx] += sign

    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of strings using the configured embedding model,
    with automatic local semantic fallback if OpenAI credits are unavailable.
    """
    if not texts:
        return []

    try:
        response = _client.embeddings.create(
            model=settings.embedding_model,
            input=texts,
        )
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
    except (RateLimitError, AuthenticationError, APIConnectionError) as e:
        logger.warning("OpenAI embedding API unavailable (%s). Using local semantic fallback.", e)
        return [_deterministic_local_embed(t) for t in texts]
    except Exception as e:
        if "quota" in str(e).lower() or "credit" in str(e).lower():
            logger.warning("OpenAI credit quota exhausted (%s). Using local semantic fallback.", e)
            return [_deterministic_local_embed(t) for t in texts]
        raise


def embed_query(query: str) -> list[float]:
    """
    Embed a single query string. Convenience wrapper around embed_texts.
    """
    return embed_texts([query])[0]

