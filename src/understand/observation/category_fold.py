"""Purpose: fold a category label the same way the sidecar and category tree do.

Input: a category label, tree id, or catalog tag.
Output: lowercase, stopword-stripped, singularized identity key.
Role: one import site. Rules match ``preprocess.text.fold_category``
so runtime Agent code does not import the extract package.
"""

from __future__ import annotations

import re
import unicodedata

# Keep in lockstep with submission/preprocess/text.py fold_category.

IRREGULAR_PLURALS = {
    "women": "woman",
    "men": "man",
    "children": "child",
    "people": "person",
    "teeth": "tooth",
    "feet": "foot",
    "geese": "goose",
    "mice": "mouse",
}

DO_NOT_SINGULARIZE = frozenset(
    {
        "jeans",
        "clothes",
        "plus",
        "glass",
        "accessories",
        "sunglasses",
        "leggings",
        "shorts",
        "pants",
        "tights",
        "earrings",
        "series",
        "news",
        "cross",
        "boss",
        "swiss",
        "canvas",
        "tennis",
        "fitness",
        "business",
        "kids",
        "boys",
        "girls",
        "mens",
        "womens",
    }
)

CATEGORY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "for",
        "with",
        "by",
        "from",
        "at",
        "to",
    }
)


def _fold_key(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("colour", "color").replace("grey", "gray")
    return re.sub(r"\s+", " ", text).strip()


def _normalize_canonical(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = text.replace("colour", "color").replace("grey", "gray")
    text = re.sub(r"\bus\s*\$", "$", text)
    held: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        held.append(match.group(0))
        return f"\x00{len(held) - 1}\x00"

    text = re.sub(r"\d+\.\d+", _stash, text)
    text = re.sub(r"[^\w$\x00]+", " ", text, flags=re.UNICODE)
    text = re.sub(r"\x00(\d+)\x00", lambda match: held[int(match.group(1))], text)
    return re.sub(r"\s+", " ", text).strip()


def _singularize(word: str) -> str:
    key = _fold_key(word)
    if not key or " " in key:
        return key
    if key in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[key]
    if key in DO_NOT_SINGULARIZE:
        return key
    if key.endswith("ies") and len(key) > 4:
        return key[:-3] + "y"
    if key.endswith("sses") or key.endswith("shes") or key.endswith("ches"):
        return key[:-2]
    if key.endswith("s") and not key.endswith("ss") and len(key) > 4:
        return key[:-1]
    return key


def fold_category(value: object) -> str:
    """One category key: lowercase, strip symbols, drop stopwords, singularize tokens."""

    text = _normalize_canonical(value)
    if not text:
        return ""
    kept: list[str] = []
    for token in text.split():
        if token in CATEGORY_STOPWORDS:
            continue
        lemma = _singularize(token)
        if lemma:
            kept.append(lemma)
    return " ".join(kept) if kept else text


__all__ = ["fold_category"]
