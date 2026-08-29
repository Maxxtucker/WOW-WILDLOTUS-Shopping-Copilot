"""Purpose: extract apparel letters, shoe numbers, and object dimensions."""

from __future__ import annotations

import re
from collections.abc import Mapping

from ..sources import DIMENSION_DETAIL_KEYS, SIZE_DETAIL_KEYS
from ..text import categories_list, details_map, fold_key
from ..types import SlotRecord
from ._common import dedupe, slot

APPAREL_LETTERS = {
    "xs": "xs",
    "s": "s",
    "m": "m",
    "l": "l",
    "xl": "xl",
    "xxl": "xxl",
    "xxxl": "xxxl",
    "one size": "one_size",
    "onesize": "one_size",
    "one_size": "one_size",
    "os": "one_size",
    "extra small": "xs",
    "small": "s",
    "medium": "m",
    "large": "l",
    "extra large": "xl",
    "2xl": "xxl",
    "3xl": "xxxl",
}
LETTER_SYNONYMS = {
    "x small": "xs",
    "xsmall": "xs",
    "x large": "xl",
    "xlarge": "xl",
    "xx large": "xxl",
    "xxx large": "xxxl",
    "one size fits all": "one_size",
}
APPAREL_LETTERS.update(LETTER_SYNONYMS)

SHOE_MARKERS = (
    "shoe",
    "shoes",
    "sneaker",
    "boot",
    "sandal",
    "slipper",
    "loafer",
    "heel",
    "footwear",
)
_DIM_CHAIN_RE = re.compile(
    r"(?P<a>\d+(?:\.\d+)?)\s*(?:\"|inches|inch|in|cm|mm)?"
    r"\s*[wdh]?\s*[x×]\s*"
    r"(?P<b>\d+(?:\.\d+)?)"
    r"(?:\s*(?:\"|inches|inch|in|cm|mm)?\s*[wdh]?\s*[x×]\s*(?P<c>\d+(?:\.\d+)?))?",
    re.IGNORECASE,
)
_SINGLE_DIM_RE = re.compile(
    r"(?P<n>\d+(?:\.\d+)?)\s*(?:cm|mm|inches|inch)\b",
    re.IGNORECASE,
)
_SYSTEM_RE = re.compile(r"\b(usa|u\.s\.a\.|u\.s\.|us|uk|eur|eu)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b(\d+(?:\.\d+)?)\b")


def _looks_like_shoe(product: Mapping[str, object]) -> bool:
    blob = " ".join(fold_key(item) for item in categories_list(product))
    blob += " " + fold_key(product.get("title"))
    return any(marker in blob for marker in SHOE_MARKERS)


def _source_unit(text: str) -> str | None:
    blob = text or ""
    has_cm = bool(re.search(r"\bcm\b|centimet", blob, re.I))
    has_mm = bool(re.search(r"\bmm\b|millimet", blob, re.I))
    has_in = bool(re.search(r"\binches?\b|\bin\b|\"", blob, re.I))
    if has_in and not has_cm and not has_mm:
        return "in"
    if has_cm and not has_mm and not has_in:
        return "cm"
    if has_mm and not has_cm and not has_in:
        return "mm"
    return None


def _to_canonical_amount(value: float, source: str) -> float:
    return value * 10.0 if source == "cm" else value


def _letter(value: str) -> str | None:
    key = fold_key(value).replace("-", " ")
    compact = key.replace(" ", "")
    return APPAREL_LETTERS.get(key) or APPAREL_LETTERS.get(compact)


def _dimension_row(text: str, source: str) -> SlotRecord | None:
    match = _DIM_CHAIN_RE.search(text)
    length = width = height = None
    if match:
        length = float(match.group("a"))
        width = float(match.group("b"))
        raw_h = match.group("c")
        height = float(raw_h) if raw_h else None
    else:
        single = _SINGLE_DIM_RE.search(text)
        if single:
            length = float(single.group("n"))
        else:
            return None
    unit_source = _source_unit(text) or "in"
    unit = "in" if unit_source == "in" else "mm"
    if unit_source == "cm":
        length = _to_canonical_amount(length, "cm") if length is not None else None
        width = _to_canonical_amount(width, "cm") if width is not None else None
        height = _to_canonical_amount(height, "cm") if height is not None else None
    extras = {
        "kind": "dimension",
        "unit": unit,
        "length": length,
        "width": width,
        "height": height,
        "amount": length,
    }
    return slot("size", "dimension", text[:180], source, extras)


def _system_token(text: str) -> str | None:
    match = _SYSTEM_RE.search(text)
    if not match:
        return None
    token = match.group(1).casefold().replace(".", "")
    if token in {"us", "usa"}:
        return "us"
    if token == "uk":
        return "uk"
    if token in {"eu", "eur"}:
        return "eu"
    return None


def extract(product: Mapping[str, object]) -> list[SlotRecord]:
    details = details_map(product)
    rows: list[SlotRecord | None] = []
    for key in DIMENSION_DETAIL_KEYS:
        raw = details.get(key)
        if raw:
            rows.append(_dimension_row(raw, f"details:{key}"))
    size_raw = None
    for key in SIZE_DETAIL_KEYS:
        if details.get(key):
            size_raw = details[key]
            source = f"details:{key}"
            break
    else:
        size_raw = None
        source = "details:size"
    if size_raw:
        letter = _letter(size_raw)
        if letter:
            rows.append(
                slot("size", letter, size_raw, source, {"kind": "apparel"})
            )
        else:
            system = _system_token(size_raw)
            numbers = [float(item) for item in _NUMBER_RE.findall(size_raw)]
            amount = numbers[0] if numbers else None
            if _looks_like_shoe(product) and amount is not None:
                extras = {"kind": "shoe", "amount": amount}
                if system:
                    extras["system"] = system
                label = f"{system} {amount:g}".strip() if system else f"{amount:g}"
                rows.append(slot("size", label, size_raw, source, extras))
            elif amount is not None:
                extras = {"kind": "apparel", "amount": amount}
                if system:
                    extras["system"] = system
                rows.append(slot("size", size_raw, size_raw, source, extras))
            else:
                rows.append(slot("size", size_raw, size_raw, source))
    return dedupe(rows)
