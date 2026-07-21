from __future__ import annotations

import hashlib
from difflib import SequenceMatcher

from app.scoring import normalize_text


def fingerprint(text: str) -> str:
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def similarity(left: str, right: str) -> int:
    left_normalized = normalize_text(left)
    right_normalized = normalize_text(right)
    return int(round(SequenceMatcher(None, left_normalized, right_normalized).ratio() * 100))
