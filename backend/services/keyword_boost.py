"""Bounded lexical boost for RAG retrieval.

Dense embeddings sometimes rank an exact-term hit just under
GANTRY_MIN_SOURCE_SIMILARITY (the Whitfield AGI case scored 0.3986 against a
0.42 floor). A small BM25-style boost, applied only in a near-miss window and
only when enough distinctive query terms appear in the chunk (or filename),
can lift that hit without dragging in unrelated low-similarity chunks.
"""

from __future__ import annotations

import math
import os
import re

# Compact English function-word list. Query terms shorter than 2 chars are
# also dropped, so "q" and "a" never trigger a boost on their own.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
    }
)

_TOKEN = re.compile(r"[A-Za-z0-9]+")

# Conservative defaults: 0.3986 + 0.05 clears 0.42, but 0.334 (typical
# generic off-topic) cannot reach the floor even with a full boost.
DEFAULT_MAX_BOOST = 0.05
DEFAULT_WINDOW = 0.06
DEFAULT_MIN_SCORE = 0.5
# Hard cap so a typo cannot disable the similarity floor.
MAX_BOOST_CAP = 0.10
WINDOW_CAP = 0.20


def tokenize(text: str) -> list[str]:
    """Lowercased alphanumeric tokens."""
    return [t.lower() for t in _TOKEN.findall(text or "")]


def query_terms(query: str) -> list[str]:
    """Distinctive query terms, order-preserving and de-duplicated."""
    seen: set[str] = set()
    terms: list[str] = []
    for tok in tokenize(query):
        if tok in _STOPWORDS or len(tok) < 2 or tok in seen:
            continue
        seen.add(tok)
        terms.append(tok)
    return terms


def _term_weight(term: str) -> float:
    """Longer terms (names, forms) weigh more than short ones like 'agi'."""
    return math.log(1.0 + len(term))


def lexical_score(query: str, text: str) -> float:
    """Weighted coverage of query terms in `text`, in [0, 1]."""
    terms = query_terms(query)
    if not terms:
        return 0.0
    haystack = set(tokenize(text))
    matched = sum(_term_weight(t) for t in terms if t in haystack)
    total = sum(_term_weight(t) for t in terms)
    return matched / total if total else 0.0


def lexical_boost(score: float, max_boost: float, min_score: float) -> float:
    """Map a lexical score to a bounded additive boost, or 0 if below min_score."""
    if max_boost <= 0 or score < min_score:
        return 0.0
    return max_boost * score


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if not math.isfinite(value):
        return default
    return min(max(value, lo), hi)


def boost_settings() -> tuple[float, float, float]:
    """Return (max_boost, window, min_score) from env, with defaults and caps."""
    max_boost = _env_float(
        "GANTRY_KEYWORD_BOOST_MAX", DEFAULT_MAX_BOOST, 0.0, MAX_BOOST_CAP
    )
    window = _env_float("GANTRY_KEYWORD_BOOST_WINDOW", DEFAULT_WINDOW, 0.0, WINDOW_CAP)
    min_score = _env_float(
        "GANTRY_KEYWORD_BOOST_MIN_SCORE", DEFAULT_MIN_SCORE, 0.0, 1.0
    )
    flag = (os.getenv("GANTRY_KEYWORD_BOOST") or "").strip().lower()
    if flag in {"0", "false", "off", "no"}:
        max_boost = 0.0
    return max_boost, window, min_score


def apply_boost(
    query: str,
    chunk_text: str,
    dense_similarity: float,
    floor: float,
    filename: str = "",
    *,
    max_boost: float | None = None,
    window: float | None = None,
    min_score: float | None = None,
) -> tuple[float, float]:
    """Return (boosted_similarity, boost) for one hit.

    The boost is applied only when dense_similarity is within `window` of the
    floor (or the floor is off). Lexical matching uses chunk text plus filename.
    The returned similarity is clamped to [0, 1].
    """
    if max_boost is None or window is None or min_score is None:
        env_max, env_window, env_min = boost_settings()
        if max_boost is None:
            max_boost = env_max
        if window is None:
            window = env_window
        if min_score is None:
            min_score = env_min

    if max_boost <= 0:
        return min(max(dense_similarity, 0.0), 1.0), 0.0

    in_window = True if floor <= 0 else dense_similarity >= floor - window
    if not in_window:
        return min(max(dense_similarity, 0.0), 1.0), 0.0

    text = f"{filename} {chunk_text}".strip()
    score = lexical_score(query, text)
    boost = lexical_boost(score, max_boost, min_score)
    return min(dense_similarity + boost, 1.0), boost
