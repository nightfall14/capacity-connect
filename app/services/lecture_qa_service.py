"""Local, deterministic transcript search for lecture Q&A."""

from __future__ import annotations

import re


_TIMESTAMP_LINE = re.compile(r"^\s*\[(\d+):([0-5]\d)\]\s+(.+?)\s*$")
_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a", "an", "and", "are", "at", "be", "by", "can", "do", "for", "from",
    "how", "i", "in", "is", "it", "me", "of", "on", "or", "the", "to", "what",
    "when", "where", "which", "with", "why", "you", "your",
}


def parse_timestamped_transcript(raw: str | None) -> list[dict]:
    """Parse `[MM:SS] text` lines, skipping malformed lines by design."""
    chunks = []
    for line in (raw or "").splitlines():
        match = _TIMESTAMP_LINE.match(line)
        if not match:
            continue
        minute, second, text = match.groups()
        chunks.append({"start_seconds": int(minute) * 60 + int(second), "text": text})
    return chunks


def transcript_answer(question: str, chunks: list[dict]) -> dict | None:
    """Return the highest keyword-overlap transcript chunk, or no match."""
    keywords = {
        word for word in _WORD.findall((question or "").lower())
        if word not in _STOPWORDS
    }
    if not keywords:
        return None

    best_chunk = None
    best_start_seconds = 0.0
    best_score = 0
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        text = str(chunk.get("text", ""))
        try:
            start_seconds = float(chunk.get("start_seconds", chunk.get("start")))
        except (TypeError, ValueError):
            continue
        chunk_words = set(_WORD.findall(text.lower()))
        score = len(keywords & chunk_words)
        if score > best_score:
            best_chunk, best_score, best_start_seconds = chunk, score, start_seconds
    if not best_chunk:
        return None
    return {
        "text": str(best_chunk["text"]),
        "start_seconds": best_start_seconds,
        "score": best_score,
    }
