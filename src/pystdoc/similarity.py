"""Lightweight, deterministic semantic-similarity helpers (no LLM calls).

Used to decide whether a regenerated description is "essentially the same"
as the previous one, so that change propagation can stop early.
"""

import re
from typing import Optional, Set

_PUNCT_RE = re.compile(r"[.,。、:：;；!?！？\-_()（）「」『』`\"'\[\]{}*#>|/\\\s]+")


def get_tokens(text: Optional[str]) -> Set[str]:
    """Tokenize into lowercase words plus character 2-grams (for CJK)."""
    clean = _PUNCT_RE.sub(" ", (text or "").lower()).strip()
    words = set(clean.split())
    compact = clean.replace(" ", "")
    for i in range(len(compact) - 1):
        words.add(compact[i:i + 2])
    return words


def similarity(a: Optional[str], b: Optional[str]) -> float:
    """Return the max of Jaccard and overlap coefficient (0.0 - 1.0).

    The overlap coefficient tolerates elaboration (one text containing the
    other) while Jaccard penalizes unrelated text.
    """
    t1, t2 = get_tokens(a), get_tokens(b)
    if not t1 and not t2:
        return 1.0
    if not t1 or not t2:
        return 0.0
    inter = len(t1 & t2)
    jaccard = inter / len(t1 | t2)
    overlap = inter / min(len(t1), len(t2))
    # overlap alone is too lenient for very different sizes; damp it.
    size_ratio = min(len(t1), len(t2)) / max(len(t1), len(t2))
    return max(jaccard, overlap * (0.5 + 0.5 * size_ratio))


def is_semantically_same(
    a: Optional[str], b: Optional[str], threshold: float = 0.85
) -> bool:
    return similarity(a, b) >= threshold
