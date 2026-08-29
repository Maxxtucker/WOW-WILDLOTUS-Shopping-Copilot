"""Purpose: shared folding, n-grams, and composition parsing for catalog extractors."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence

# Text folding follows protocol_copy.normalize_text, except decimal numbers
# keep their "." so budget and size amounts stay parseable as floats.
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_COMPOSITION_RE = re.compile(
    r"(?P<pct>\d+(?:\.\d+)?)\s*%\s*(?P<name>[A-Za-z][A-Za-z][A-Za-z \-/]*)",
    re.IGNORECASE,
)
_HYPHEN_SPLIT = re.compile(r"[-/,&]| and ", re.IGNORECASE)

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

STOP_NGRAMS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "for",
        "with",
        "from",
        "this",
        "that",
        "size",
        "pack",
        "set",
        "new",
        "usa",
        "imported",
    }
)

# Glue words dropped when folding a catalog category node into one tree key.
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


def fold_key(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("colour", "color").replace("grey", "gray")
    return re.sub(r"\s+", " ", text).strip()


def normalize_canonical(value: object) -> str:
    """Match retrieve signature normalization (NFKC, grey/gray, non-word → space)."""

    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = text.replace("colour", "color").replace("grey", "gray")
    text = re.sub(r"\bus\s*\$", "$", text)
    held: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        held.append(match.group(0))
        return f"\x00{len(held) - 1}\x00"

    # Keep 1.99 as 1.99. Stripping "." to a space breaks budget/size compare.
    text = re.sub(r"\d+\.\d+", _stash, text)
    text = re.sub(r"[^\w$\x00]+", " ", text, flags=re.UNICODE)
    text = re.sub(r"\x00(\d+)\x00", lambda match: held[int(match.group(1))], text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(value: object) -> tuple[str, ...]:
    return tuple(_WORD_RE.findall(fold_key(value)))


def ngrams(words: Sequence[str], *, maximum: int = 4) -> list[tuple[int, int, str]]:
    """Return (start, end_exclusive, phrase) longest-first."""

    length = len(words)
    spans: list[tuple[int, int, str]] = []
    for width in range(min(maximum, length), 0, -1):
        for start in range(0, length - width + 1):
            end = start + width
            phrase = " ".join(words[start:end])
            if phrase in STOP_NGRAMS:
                continue
            spans.append((start, end, phrase))
    return spans


def flatten_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        return " ".join(f"{key} {item}" for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return " ".join(str(item) for item in value if item not in (None, ""))
    return str(value)


def details_map(product: Mapping[str, object]) -> dict[str, str]:
    raw = product.get("details")
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, item in raw.items():
        if item in (None, "", []):
            continue
        result[fold_key(key)] = str(item).strip()
    return result


def feature_lines(product: Mapping[str, object]) -> list[str]:
    raw = product.get("features")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [str(item).strip() for item in raw if item not in (None, "")]


def categories_list(product: Mapping[str, object]) -> list[str]:
    raw = product.get("categories") or []
    if isinstance(raw, str):
        return [raw]
    if not isinstance(raw, Sequence):
        return [str(raw)]
    return [str(item) for item in raw if item not in (None, "")]


def composition_parts(text: str) -> list[tuple[float, str]]:
    found: list[tuple[float, str]] = []
    for match in _COMPOSITION_RE.finditer(text or ""):
        name = match.group("name").strip(" -/")
        name = re.sub(r"\s+", " ", name)
        name = re.split(r"\s+\b(?:and|with)\b\s+", name, maxsplit=1, flags=re.I)[0]
        name = name.strip(" ,;/")
        if not name:
            continue
        found.append((float(match.group("pct")), name))
    return found


def split_alternatives(value: str) -> list[str]:
    parts = [piece.strip() for piece in _HYPHEN_SPLIT.split(value or "")]
    return [piece for piece in parts if piece]


def singularize(word: str) -> str:
    key = fold_key(word)
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
    """One category key: lowercase, strip symbols, drop stopwords, singularize tokens.

    ``Clothing, Shoes & Jewelry`` and ``Clothing, Shoes and Jewelry`` both become
    ``clothing shoe jewelry``. ``Shoes`` / ``shoe`` both become ``shoe``.
    """

    text = normalize_canonical(value)
    if not text:
        return ""
    kept: list[str] = []
    for token in text.split():
        if token in CATEGORY_STOPWORDS:
            continue
        lemma = singularize(token)
        if lemma:
            kept.append(lemma)
    return " ".join(kept) if kept else text


def category_tag_forms(*labels: str) -> list[str]:
    """Fold labels the same way as sidecar category canonicals and tree tags."""

    seen: set[str] = set()
    out: list[str] = []
    for label in labels:
        folded = fold_category(label)
        if folded and folded not in seen:
            seen.add(folded)
            out.append(folded)
    return out


def unique_rows(rows: Iterable[tuple]) -> list[tuple]:
    seen: set[tuple] = set()
    result: list[tuple] = []
    for row in rows:
        if row in seen:
            continue
        seen.add(row)
        result.append(row)
    return result
