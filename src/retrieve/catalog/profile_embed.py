"""Purpose: optional bi-encoder scores for long-term preference tags.

Input: joined preference_tags and product_text surfaces for the current pool.
Output: parent_asin -> max cosine (title, 0.7 details, 0.5 description).
Role: weak retrieve tie-break only. Never used for exact pool or BM25.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

_model = None
_model_failed = False


def _env_mode() -> str:
    mode = os.environ.get("AGENT_PROFILE_EMBED_MODE", "auto").strip().casefold()
    return mode if mode in {"off", "auto", "required"} else "auto"


def encode_texts(texts: Sequence[str]) -> list[list[float]] | None:
    """Encode texts with a lazy SentenceTransformer. None if unavailable."""

    global _model, _model_failed
    if not texts:
        return []
    mode = _env_mode()
    if mode == "off":
        return None
    if _model_failed and mode != "required":
        return None
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer

            name = (
                os.environ.get("AGENT_PROFILE_EMBED_MODEL", DEFAULT_MODEL).strip()
                or DEFAULT_MODEL
            )
            _model = SentenceTransformer(name)
        except Exception:
            _model_failed = True
            if mode == "required":
                raise
            return None
    vectors = _model.encode(
        list(texts),
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [list(map(float, row)) for row in vectors]


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


def profile_fits(
    tags: Sequence[str],
    documents: Mapping[str, Mapping[str, str]],
) -> dict[str, float]:
    """Return clipped cosine fits. Empty tags or a missing model yield {}."""

    cleaned = [str(tag).strip() for tag in tags if str(tag).strip()]
    if not cleaned or not documents:
        return {}
    query = ", ".join(cleaned)
    asins = list(documents)
    fields = ("title", "details", "description")
    field_weights = {"title": 1.0, "details": 0.7, "description": 0.5}
    blobs: list[str] = [query]
    index: list[tuple[str, str]] = []
    for parent_asin in asins:
        row = documents[parent_asin]
        for field in fields:
            text = str(row.get(field) or "").strip()
            if text:
                blobs.append(text)
                index.append((parent_asin, field))
    vectors = encode_texts(blobs)
    if not vectors or len(vectors) != len(blobs):
        return {}
    query_vec = vectors[0]
    best: dict[str, float] = {}
    for offset, (parent_asin, field) in enumerate(index):
        score = max(0.0, _dot(query_vec, vectors[offset + 1]))
        weighted = field_weights[field] * score
        previous = best.get(parent_asin, 0.0)
        if weighted > previous:
            best[parent_asin] = weighted
    return best
