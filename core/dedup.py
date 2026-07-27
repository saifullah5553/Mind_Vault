"""Duplicate / near-duplicate detection.

DESIGN: Two backends behind one interface. `difflib` (stdlib, zero deps) gives a
solid lexical similarity that works everywhere. `embeddings`
(sentence-transformers, optional) gives true semantic similarity. Config
`dedup.method: auto` uses embeddings if installed, else difflib — so the
80%-similarity gate always works, and upgrades automatically when you install
the optional package. No external service, no cost.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from functools import lru_cache

from core.config import get_settings
from core.logging_setup import get_logger

log = get_logger("dedup")


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _difflib_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


@lru_cache(maxsize=1)
def _load_embedder():
    """Lazily load a sentence-transformer if available; else None."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        log.info("Loaded sentence-transformers for semantic dedup.")
        return SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:  # not installed or failed to load
        return None


def _embedding_similarity(a: str, b: str) -> float | None:
    model = _load_embedder()
    if model is None:
        return None
    import numpy as np

    va, vb = model.encode([a, b])
    denom = (np.linalg.norm(va) * np.linalg.norm(vb)) or 1.0
    return float(np.dot(va, vb) / denom)


def similarity(a: str, b: str) -> float:
    """Return similarity in [0, 1] using the configured/available method."""
    method = get_settings().dedup.method.lower()
    if method in ("auto", "embeddings"):
        emb = _embedding_similarity(a, b)
        if emb is not None:
            return emb
        if method == "embeddings":
            log.warning("embeddings requested but unavailable; using difflib.")
    return _difflib_similarity(a, b)


def is_duplicate(candidate: str, existing: list[str], threshold: float | None = None) -> tuple[bool, float]:
    """Return (is_dup, max_similarity) comparing candidate against existing corpus."""
    thr = get_settings().dedup.threshold if threshold is None else threshold
    if not existing:
        return False, 0.0
    best = max(similarity(candidate, e) for e in existing)
    return best >= thr, best
