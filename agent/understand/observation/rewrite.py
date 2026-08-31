"""Purpose: casefold shopper text and replace color/material aliases before NLU.

Input: the raw user message plus committed color/material alias JSON.
Optional verify callbacks drop pairs whose source is not a color or material word.
Output: a rewritten sentence. Session still stores the original message.
Role: parallel longest-match color and material maps onto the 11 eval colors
and 9 materials. Same-span hits concatenate ``color material``. Jewelry metals
(gold, silver, platinum) are not rewritten to yellow/white.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Sequence

from ...domain import MATERIALS
from ...progress import emit, skip_nodes
from .slots.attributes.color import CLOSED_COLOR_SET

_ALIASES_DIR = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "catalog_preprocess"
    / "aliases"
)
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_METAL_TOKENS = frozenset({"gold", "silver", "platinum"})
MAX_COLOR_NGRAM = 4
MAX_MATERIAL_NGRAM = 5

TokenSpan = tuple[int, int, str]
AliasVerify = Callable[[Sequence["AliasHit"]], Sequence["AliasHit"]]


@dataclass(frozen=True, slots=True)
class AliasHit:
    """One longest-match alias span in token indexes ``[start, end)``."""

    start: int
    end: int
    phrase: str
    replacement: str


def rewrite_for_nlu(
    message: str,
    *,
    verify_color: AliasVerify | None = None,
    verify_material: AliasVerify | None = None,
) -> str:
    """Casefold ``message`` and replace known color/material phrases."""

    emit(
        "understand",
        "casefold",
        "running",
        {"input": {"message": message or ""}},
    )
    folded = (message or "").casefold()
    emit(
        "understand",
        "casefold",
        "completed",
        {
            "text": folded,
            "input": {"message": message or ""},
            "output": {"folded": folded},
        },
    )
    if not folded.strip():
        skip_nodes(
            "understand",
            "color_map",
            "material_map",
            "color_verify",
            "material_verify",
            "merge_rewrite",
            why="casefolded message is empty",
        )
        return folded
    spans = [(match.start(), match.end(), match.group()) for match in _WORD_RE.finditer(folded)]
    if not spans:
        skip_nodes(
            "understand",
            "color_map",
            "material_map",
            "color_verify",
            "material_verify",
            "merge_rewrite",
            why="message contains no word tokens for alias matching",
        )
        return folded
    color_map, color_n = _load_color_mapping()
    material_map, material_n = _load_material_mapping()
    emit("understand", "color_map", "running")
    emit("understand", "material_map", "running")
    color_hits = collect_hits(spans, color_map, color_n)
    material_hits = collect_hits(spans, material_map, material_n)
    emit(
        "understand",
        "color_map",
        "completed",
        {
            "hits": _alias_rows(color_hits),
            "input": {
                "folded": folded,
                "maximum_ngram": color_n,
                "alias_count": len(color_map),
            },
            "output": {"hits": _alias_rows(color_hits)},
        },
    )
    emit(
        "understand",
        "material_map",
        "completed",
        {
            "hits": _alias_rows(material_hits),
            "input": {
                "folded": folded,
                "maximum_ngram": material_n,
                "alias_count": len(material_map),
            },
            "output": {"hits": _alias_rows(material_hits)},
        },
    )
    color_work = _has_nontrivial(color_hits)
    material_work = _has_nontrivial(material_hits)
    if (
        verify_color is not None
        and verify_material is not None
        and color_work
        and material_work
    ):
        before_color = list(color_hits)
        before_material = list(material_hits)
        emit("understand", "color_verify", "running")
        emit("understand", "material_verify", "running")
        color_hits, material_hits = gate_hits_parallel(
            color_hits, material_hits, verify_color, verify_material
        )
        emit(
            "understand",
            "color_verify",
            "completed",
            {
                "hits": _alias_rows(before_color, color_hits),
                "input": {"hits": _alias_rows(before_color)},
                "output": {"hits": _alias_rows(before_color, color_hits)},
            },
        )
        emit(
            "understand",
            "material_verify",
            "completed",
            {
                "hits": _alias_rows(before_material, material_hits),
                "input": {"hits": _alias_rows(before_material)},
                "output": {
                    "hits": _alias_rows(before_material, material_hits)
                },
            },
        )
    else:
        color_hits = _gate_with_progress(
            "color_verify", color_hits, verify_color
        )
        material_hits = _gate_with_progress(
            "material_verify", material_hits, verify_material
        )
    emit("understand", "merge_rewrite", "running")
    merged = merge_alias_hits(color_hits, material_hits)
    rewritten = _apply_hits(folded, spans, merged)
    emit(
        "understand",
        "merge_rewrite",
        "completed",
        {
            "original": message,
            "rewritten": rewritten,
            "hits": _alias_rows(merged),
            "input": {
                "folded": folded,
                "color_hits": _alias_rows(color_hits),
                "material_hits": _alias_rows(material_hits),
            },
            "output": {
                "rewritten": rewritten,
                "hits": _alias_rows(merged),
            },
        },
    )
    return rewritten


def collect_hits(
    spans: Sequence[TokenSpan],
    mapping: dict[str, str],
    max_n: int,
) -> list[AliasHit]:
    """Greedy longest word-boundary matches. Spans do not overlap."""

    hits: list[AliasHit] = []
    if not mapping or max_n < 1:
        return hits
    index = 0
    while index < len(spans):
        matched_len = 0
        replacement = ""
        phrase = ""
        limit = min(max_n, len(spans) - index)
        for width in range(limit, 0, -1):
            candidate = " ".join(token for _start, _end, token in spans[index : index + width])
            mapped = mapping.get(candidate)
            if mapped is None:
                continue
            matched_len = width
            replacement = mapped
            phrase = candidate
            break
        if matched_len:
            hits.append(
                AliasHit(
                    start=index,
                    end=index + matched_len,
                    phrase=phrase,
                    replacement=replacement,
                )
            )
            index += matched_len
            continue
        index += 1
    return hits


def merge_alias_hits(
    color_hits: Sequence[AliasHit],
    material_hits: Sequence[AliasHit],
) -> list[AliasHit]:
    """Same token span with both maps → ``color material``. Longer span wins overlaps."""

    by_span: dict[tuple[int, int], dict[str, AliasHit]] = {}
    for hit in color_hits:
        by_span.setdefault((hit.start, hit.end), {})["color"] = hit
    for hit in material_hits:
        by_span.setdefault((hit.start, hit.end), {})["material"] = hit
    candidates: list[AliasHit] = []
    for (start, end), kinds in by_span.items():
        color = kinds.get("color")
        material = kinds.get("material")
        if color and material:
            replacement = f"{color.replacement} {material.replacement}"
            phrase = color.phrase
        elif color:
            replacement = color.replacement
            phrase = color.phrase
        else:
            assert material is not None
            replacement = material.replacement
            phrase = material.phrase
        candidates.append(
            AliasHit(start=start, end=end, phrase=phrase, replacement=replacement)
        )
    candidates.sort(key=lambda hit: (hit.start - hit.end, hit.start))
    picked: list[AliasHit] = []
    used: set[int] = set()
    for hit in candidates:
        if any(index in used for index in range(hit.start, hit.end)):
            continue
        picked.append(hit)
        used.update(range(hit.start, hit.end))
    picked.sort(key=lambda hit: hit.start)
    return picked


def _has_nontrivial(hits: Sequence[AliasHit]) -> bool:
    return any(hit.phrase != hit.replacement for hit in hits)


def _alias_rows(
    hits: Sequence[AliasHit],
    kept: Sequence[AliasHit] | None = None,
) -> list[dict[str, object]]:
    kept_keys = (
        None
        if kept is None
        else {(hit.start, hit.end, hit.phrase) for hit in kept}
    )
    rows: list[dict[str, object]] = []
    for hit in hits:
        row: dict[str, object] = {
            "phrase": hit.phrase,
            "replacement": hit.replacement,
        }
        if kept_keys is not None:
            row["kept"] = (hit.start, hit.end, hit.phrase) in kept_keys
        rows.append(row)
    return rows


def _gate_with_progress(
    node: str,
    hits: list[AliasHit],
    verify: AliasVerify | None,
) -> list[AliasHit]:
    if verify is None or not hits or not _has_nontrivial(hits):
        skip_nodes(
            "understand",
            node,
            why=(
                "no verifier is configured"
                if verify is None
                else "no non-trivial alias hit requires semantic verification"
            ),
        )
        return _gate_hits(hits, verify)
    before = list(hits)
    emit(
        "understand",
        node,
        "running",
        {"input": {"hits": _alias_rows(before)}},
    )
    kept = _gate_hits(hits, verify)
    emit(
        "understand",
        node,
        "completed",
        {
            "hits": _alias_rows(before, kept),
            "input": {"hits": _alias_rows(before)},
            "output": {"hits": _alias_rows(before, kept)},
        },
    )
    return kept


def _gate_hits(hits: list[AliasHit], verify: AliasVerify | None) -> list[AliasHit]:
    if verify is None or not hits:
        return hits
    identity = [hit for hit in hits if hit.phrase == hit.replacement]
    nontrivial = [hit for hit in hits if hit.phrase != hit.replacement]
    if not nontrivial:
        return hits
    kept = list(verify(nontrivial))
    return [*identity, *kept]


def _apply_hits(folded: str, spans: Sequence[TokenSpan], hits: Sequence[AliasHit]) -> str:
    pieces: list[str] = []
    cursor = 0
    for hit in hits:
        start_char = spans[hit.start][0]
        end_char = spans[hit.end - 1][1]
        pieces.append(folded[cursor:start_char])
        pieces.append(hit.replacement)
        cursor = end_char
    pieces.append(folded[cursor:])
    return "".join(pieces)


def _load_color_mapping() -> tuple[dict[str, str], int]:
    return _color_mapping_cached()


def _load_material_mapping() -> tuple[dict[str, str], int]:
    return _material_mapping_cached()


@lru_cache(maxsize=1)
def _color_mapping_cached() -> tuple[dict[str, str], int]:
    mapping: dict[str, str] = {}
    path = _ALIASES_DIR / "color_aliases.json"
    if path.is_file():
        _absorb_color_aliases(mapping, _read_alias_object(path))
    max_n = max((len(key.split()) for key in mapping), default=1)
    return mapping, max_n


@lru_cache(maxsize=1)
def _material_mapping_cached() -> tuple[dict[str, str], int]:
    mapping: dict[str, str] = {}
    path = _ALIASES_DIR / "material_aliases.json"
    if path.is_file():
        _absorb_material_aliases(mapping, _read_alias_object(path))
    max_n = max((len(key.split()) for key in mapping), default=1)
    return mapping, max_n


def _read_alias_object(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return {
        key: value
        for key, value in payload.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def _absorb_color_aliases(mapping: dict[str, str], raw: dict[str, dict]) -> None:
    for key, row in raw.items():
        eval_color = str(row.get("eval") or "").strip().casefold()
        if eval_color not in CLOSED_COLOR_SET:
            continue
        folded = _fold_alias_key(key)
        tokens = folded.split()
        if not tokens or len(tokens) > MAX_COLOR_NGRAM:
            continue
        if _METAL_TOKENS.intersection(tokens):
            continue
        mapping[folded] = eval_color


def _absorb_material_aliases(mapping: dict[str, str], raw: dict[str, dict]) -> None:
    allowed = frozenset(MATERIALS)
    for key, row in raw.items():
        eval_material = str(row.get("eval") or "").strip().casefold()
        if eval_material not in allowed:
            continue
        folded = _fold_alias_key(key)
        tokens = folded.split()
        if not tokens or len(tokens) > MAX_MATERIAL_NGRAM:
            continue
        if _METAL_TOKENS.intersection(tokens):
            continue
        mapping[folded] = eval_material


def _fold_alias_key(value: str) -> str:
    text = value.casefold().replace("-", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def gate_hits_parallel(
    color_hits: Sequence[AliasHit],
    material_hits: Sequence[AliasHit],
    verify_color: AliasVerify,
    verify_material: AliasVerify,
) -> tuple[list[AliasHit], list[AliasHit]]:
    """Run both word-class gates at once. Used by inspect when both sides have work."""

    with ThreadPoolExecutor(max_workers=2) as pool:
        color_future = pool.submit(_gate_hits, list(color_hits), verify_color)
        material_future = pool.submit(_gate_hits, list(material_hits), verify_material)
        return list(color_future.result()), list(material_future.result())
