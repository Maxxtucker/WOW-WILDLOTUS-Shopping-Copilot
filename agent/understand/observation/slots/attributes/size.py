"""Purpose: size slot grounding (shoe / apparel / dimension).

Input: parsed size item, grounded surface, user message.
Output: ConstraintSlot with kind, system, letter canonical, or converted L/W/H.
Role: model picks kind and letter buckets; code folds official keys and converts cm→mm.
"""

from __future__ import annotations

import re

from ..text import (
    fold_key,
    grounded_number,
    infer_op,
    number_spans,
    parse_amount,
)
from ..types import ConstraintSlot, ParsedItem, SizeKind, SizeSystem, SizeUnit

SIZE_SYSTEMS = ("us", "uk", "eu")
SIZE_SYSTEM_SET = frozenset(SIZE_SYSTEMS)
SIZE_KINDS = ("shoe", "apparel", "dimension")
SIZE_KIND_SET = frozenset(SIZE_KINDS)
SIZE_UNITS = ("in", "mm")
SIZE_UNIT_SET = frozenset(SIZE_UNITS)
APPAREL_LETTERS = ("xs", "s", "m", "l", "xl", "xxl", "xxxl", "one_size")
APPAREL_LETTER_SET = frozenset(APPAREL_LETTERS)

_SYSTEM_NEAR_CHARS = 32
_SIZE_SYSTEM_TOKEN_RE = re.compile(
    r"(?<![A-Za-z])(?P<token>USA|U\.S\.A\.|U\.S\.|US|UK|EUR|EU)(?![A-Za-z])",
    re.IGNORECASE,
)
_US_PRONOUN_PREFIX = re.compile(
    r"\b(?:tell|give|let|show|inform|allow|help)\s+$",
    re.IGNORECASE,
)
_SIZE_SYSTEM_ALIASES = {
    "us": "us",
    "usa": "us",
    "u.s": "us",
    "u.s.": "us",
    "uk": "uk",
    "eu": "eu",
    "eur": "eu",
}
_SIZE_KIND_ALIASES = {
    "shoe": "shoe",
    "shoes": "shoe",
    "apparel": "apparel",
    "dimension": "dimension",
    "dimensions": "dimension",
}
APPAREL_LETTER_SYNONYMS = {
    "extra small": "xs",
    "x small": "xs",
    "xsmall": "xs",
    "small": "s",
    "medium": "m",
    "large": "l",
    "extra large": "xl",
    "x large": "xl",
    "xlarge": "xl",
    "xx large": "xxl",
    "2xl": "xxl",
    "xxlarge": "xxl",
    "xxx large": "xxxl",
    "3xl": "xxxl",
    "one size": "one_size",
    "onesize": "one_size",
    "one_size": "one_size",
    "one size fits all": "one_size",
}
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


def _normalize_size_system(value: object) -> SizeSystem | None:
    key = fold_key(str(value or "")).replace(" ", "")
    mapped = _SIZE_SYSTEM_ALIASES.get(key)
    if mapped == "us":
        return "us"
    if mapped == "uk":
        return "uk"
    if mapped == "eu":
        return "eu"
    return None


def _size_systems_near_amount(text: str, amount: float | None) -> tuple[SizeSystem, ...]:
    """US/UK/EU tokens inside a short window around the size digits."""

    text = text or ""
    spans = number_spans(text, amount)
    if not spans:
        return ()
    found: list[SizeSystem] = []
    for start, end in spans:
        lo = max(0, start - _SYSTEM_NEAR_CHARS)
        hi = min(len(text), end + _SYSTEM_NEAR_CHARS)
        window = text[lo:hi]
        for match in _SIZE_SYSTEM_TOKEN_RE.finditer(window):
            raw = match.group("token")
            mapped = _normalize_size_system(raw)
            if mapped == "us" and raw == "us":
                prefix = text[: lo + match.start()]
                if _US_PRONOUN_PREFIX.search(prefix):
                    continue
            if mapped is not None and mapped not in found:
                found.append(mapped)
    return tuple(found)


def resolve_size_system(
    surface: str,
    hint: object,
    message: str,
    *,
    extras: tuple[str, ...] = (),
    amount: float | None = None,
) -> SizeSystem | None:
    """US/UK/EU when that label appears near the size number. Do not guess."""

    for blob in (surface, *extras):
        found = _size_systems_near_amount(blob, amount)
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            return None
    mentioned = _size_systems_near_amount(message, amount)
    hinted = _normalize_size_system(hint)
    if hinted is not None and hinted in mentioned and len(mentioned) == 1:
        return hinted
    if hinted is None and len(mentioned) == 1 and parse_amount(surface) is not None:
        return mentioned[0]
    return None


def _normalize_size_kind(value: object) -> SizeKind | None:
    mapped = _SIZE_KIND_ALIASES.get(fold_key(str(value or "")))
    if mapped == "shoe":
        return "shoe"
    if mapped == "apparel":
        return "apparel"
    if mapped == "dimension":
        return "dimension"
    return None


def _source_unit_in(text: str) -> str | None:
    """Original unit in the span: in, cm, or mm. Mixed families are empty."""

    blob = text or ""
    has_cm = bool(re.search(r"\bcentimet(?:re|er)s?\b|\bcm\b", blob, re.IGNORECASE))
    has_mm = bool(
        re.search(r"\bmillimet(?:re|er)s?\b|\bmm\b", blob, re.IGNORECASE)
    )
    has_in = bool(
        re.search(r"\binches?\b", blob, re.IGNORECASE)
        or re.search(r'\d+(?:\.\d+)?\s*"', blob)
    )
    if has_in and (has_cm or has_mm):
        return None
    if has_cm and has_mm:
        return None
    if has_in:
        return "in"
    if has_cm:
        return "cm"
    if has_mm:
        return "mm"
    return None


def _canonical_unit_from_source(source: str) -> SizeUnit:
    return "in" if source == "in" else "mm"


def _to_canonical_amount(value: float | None, source: str) -> float | None:
    if value is None:
        return None
    if source == "cm":
        return value * 10.0
    return value


def _official_letter(value: str | None) -> str | None:
    """Accept a token that already is an official letter key (case/punctuation)."""

    key = fold_key(value or "")
    if not key:
        return None
    key = key.replace("-", "_")
    compact = key.replace("_", "").replace(" ", "")
    if key in APPAREL_LETTER_SET:
        return key
    if compact in APPAREL_LETTER_SET:
        return compact
    return None


def _coerce_letter_hint(canonical_hint: str | None) -> str | None:
    """Fold a model canonical onto the letter list. Do not scan shopper surface."""

    official = _official_letter(canonical_hint)
    if official is not None:
        return official
    key = fold_key(canonical_hint or "")
    if not key:
        return None
    compact = key.replace("-", "").replace("_", "").replace(" ", "")
    mapped = APPAREL_LETTER_SYNONYMS.get(key) or APPAREL_LETTER_SYNONYMS.get(compact)
    if mapped in APPAREL_LETTER_SET:
        return mapped
    return None


def _looks_like_dimension(surface: str) -> bool:
    text = surface or ""
    return bool(_DIM_CHAIN_RE.search(text) or _SINGLE_DIM_RE.search(text))


def _parse_dimension_numbers(
    surface: str,
) -> tuple[float | None, float | None, float | None]:
    match = _DIM_CHAIN_RE.search(surface or "")
    if match:
        length = float(match.group("a"))
        width = float(match.group("b"))
        raw_height = match.group("c")
        height = float(raw_height) if raw_height else None
        return length, width, height
    match = _SINGLE_DIM_RE.search(surface or "")
    if match:
        return float(match.group("n")), None, None
    return None, None, None


def resolve_size_kind(hint: object, surface: str) -> SizeKind | None:
    """Use the model's kind. Infer dimension only from a measurement span."""

    if _looks_like_dimension(surface):
        return "dimension"
    return _normalize_size_kind(hint)


def resolve_size_unit(
    surface: str,
    hint: object,
    message: str,
    *,
    extras: tuple[str, ...] = (),
) -> tuple[SizeUnit | None, str | None]:
    """Canonical in/mm from the original unit word. cm maps to mm."""

    del hint
    source: str | None = None
    for blob in (surface, *extras, message):
        found = _source_unit_in(blob)
        if found is not None:
            source = found
            break
    if source is None:
        return None, None
    return _canonical_unit_from_source(source), source


def _raw_dict(parsed: ParsedItem) -> dict:
    return parsed.raw if isinstance(parsed.raw, dict) else {}


def ground(parsed: ParsedItem, surface: str, message: str) -> ConstraintSlot | None:
    raw = _raw_dict(parsed)
    kind = resolve_size_kind(raw.get("kind"), surface)
    amount = parsed.amount
    op = parsed.op
    if amount is None:
        amount = parse_amount(surface)
    if amount is not None:
        if op is None:
            op = infer_op(surface)
    else:
        op = None
    canonical_value = None
    system: SizeSystem | None = None
    unit: SizeUnit | None = None
    length: float | None = None
    width: float | None = None
    height: float | None = None
    extras = parsed.extras
    if kind == "apparel":
        letter = _coerce_letter_hint(parsed.canonical_hint) or _official_letter(surface)
        if letter is not None:
            canonical_value = (letter,)
            amount = None
            op = None
        else:
            system = resolve_size_system(
                surface, raw.get("system"), message, extras=extras, amount=amount
            )
    elif kind == "shoe":
        system = resolve_size_system(
            surface, raw.get("system"), message, extras=extras, amount=amount
        )
    elif kind == "dimension":
        unit, source = resolve_size_unit(
            surface, raw.get("unit"), message, extras=extras
        )
        parsed_l, parsed_w, parsed_h = _parse_dimension_numbers(surface)
        length = grounded_number(raw.get("length"), message) or parsed_l
        width = grounded_number(raw.get("width"), message) or parsed_w
        height = grounded_number(raw.get("height"), message) or parsed_h
        if source is not None:
            length = _to_canonical_amount(length, source)
            width = _to_canonical_amount(width, source)
            height = _to_canonical_amount(height, source)
        if length is not None:
            amount = length
            op = op or "eq"
    else:
        system = resolve_size_system(
            surface, raw.get("system"), message, extras=extras, amount=amount
        )
    return ConstraintSlot(
        attribute="size",
        surface=surface,
        canonical=canonical_value,
        amount=amount,
        op=op,
        system=system,
        kind=kind,
        unit=unit,
        length=length,
        width=width,
        height=height,
    )
