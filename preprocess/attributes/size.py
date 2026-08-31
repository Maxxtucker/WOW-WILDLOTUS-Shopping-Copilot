"""Purpose: extract apparel letters, shoe numbers, and object dimensions."""

from __future__ import annotations

import re
from collections.abc import Mapping

from ..sources import SIZE_DETAIL_KEYS, is_dimension_detail_key, is_weight_detail_key
from ..text import categories_list, details_map, fold_key, to_inches, to_pounds
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
_WEIGHT_RE = re.compile(
    r"(?P<n>\d+(?:\.\d+)?)\s*(?P<u>pounds?|lbs?|oz|ounces?|kgs?|kilograms?|grams?|g)\b",
    re.IGNORECASE,
)


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


def _letter(value: str) -> str | None:
    key = fold_key(value).replace("-", " ")
    compact = key.replace(" ", "")
    return APPAREL_LETTERS.get(key) or APPAREL_LETTERS.get(compact)


def _weight_source(token: str) -> str:
    key = token.casefold()
    if key.startswith("oz") or key.startswith("ounce"):
        return "oz"
    if key.startswith("kg") or key.startswith("kilo"):
        return "kg"
    if key in {"g", "gram", "grams"}:
        return "g"
    return "lb"


def parse_weight_lb(text: str, *, default_lb: bool = False) -> float | None:
    match = _WEIGHT_RE.search(text or "")
    if match:
        return to_pounds(float(match.group("n")), _weight_source(match.group("u")))
    if default_lb:
        numbers = _NUMBER_RE.findall(text or "")
        if len(numbers) == 1:
            return float(numbers[0])
    return None


def _dimension_row(text: str, source: str, source_key: str) -> SlotRecord | None:
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
    weight = parse_weight_lb(
        text, default_lb=is_weight_detail_key(source_key) and match is None
    )
    if length is None and width is None and height is None and weight is None:
        return None
    unit_source = _source_unit(text) or "in"
    if length is not None:
        length = to_inches(length, unit_source)
    if width is not None:
        width = to_inches(width, unit_source)
    if height is not None:
        height = to_inches(height, unit_source)
    extras = {
        "kind": "dimension",
        "unit": "in",
        "length": length,
        "width": width,
        "height": height,
        "amount": length,
        "source_key": source_key,
    }
    if weight is not None:
        extras["weight"] = weight
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
    for key, raw in details.items():
        if raw and (is_dimension_detail_key(key) or is_weight_detail_key(key)):
            rows.append(_dimension_row(raw, f"details:{key}", key))
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
