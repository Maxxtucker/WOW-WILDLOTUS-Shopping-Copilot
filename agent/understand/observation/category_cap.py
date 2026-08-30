"""Purpose: cap a bloated turn category list to five tags that cover the item.

Input: this turn's category rows plus the original shopper message.
Output: the same rows trimmed to at most five fold-matched catalog tags.
Role: understand safety net after identity emit. LLM filter, then sidecar df.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ...progress import emit, skip_nodes
from ...retrieve.catalog.slots_sidecar import DEFAULT_SLOTS_RELATIVE, resolve_slots_path
from .category_fold import fold_category
from .slots.attributes.category import grounded_catalog_tags

CATEGORY_CAP_LIMIT = 5
CATEGORY_CAP_ATTEMPTS = 3

CompleteFn = Callable[..., dict[str, Any] | None]

_CATEGORY_CAP_PROMPT = """\
You filter catalog category tags to those that can contain the shopper's product.
Return JSON only: {"ids": ["<canonical>", ...]}

ids: copy exactly 5 tags from the allowed list. Do not invent tags.
Pick the 5 closest tags that can contain this item (broader ancestors plus matching subtypes).
If the message names a product type that appears in the allowed list, that tag MUST be one of the 5.
Copy allowed strings. Do not return attributes, products, or ASINs.
"""


def unique_category_tags(tags: Sequence[str]) -> tuple[str, ...]:
    """Preserve first-seen original strings; drop later same-fold duplicates."""

    found: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        cleaned = str(tag).strip()
        if not cleaned:
            continue
        key = fold_category(cleaned) or cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        found.append(cleaned)
    return tuple(found)


def pool_fold_map(tags: Sequence[str]) -> dict[str, str]:
    """fold_category(tag) → first original pool string."""

    mapping: dict[str, str] = {}
    for tag in unique_category_tags(tags):
        key = fold_category(tag) or tag.casefold()
        mapping.setdefault(key, tag)
    return mapping


def tags_from_category_rows(rows: Sequence[dict[str, Any]]) -> tuple[str, ...]:
    collected: list[str] = []
    for row in rows:
        raw = row.get("canonical") or ()
        if isinstance(raw, str):
            collected.append(raw)
            continue
        if isinstance(raw, (list, tuple)):
            collected.extend(str(item) for item in raw)
    return unique_category_tags(collected)


def parse_cap_ids(payload: dict[str, Any] | None) -> tuple[str, ...] | None:
    if not isinstance(payload, dict):
        return None
    raw_ids = payload.get("ids", payload.get("id"))
    ids: list[str] = []
    if isinstance(raw_ids, str):
        if raw_ids.strip():
            ids.append(raw_ids.strip())
    elif isinstance(raw_ids, list):
        for item in raw_ids:
            text = str(item or "").strip()
            if text:
                ids.append(text)
    else:
        return None
    return tuple(ids)


def resolve_model_ids(
    raw_ids: Sequence[str], fold_map: Mapping[str, str]
) -> tuple[str, ...] | None:
    """Map model strings onto pool originals. None when not exactly five unique hits."""

    resolved: list[str] = []
    seen: set[str] = set()
    for item in raw_ids:
        key = fold_category(item)
        original = fold_map.get(key) if key else None
        if original is None:
            return None
        if key in seen:
            return None
        seen.add(key)
        resolved.append(original)
    if len(resolved) != CATEGORY_CAP_LIMIT:
        return None
    return tuple(resolved)


def required_grounded_tags(message: str, pool: Sequence[str]) -> tuple[str, ...]:
    return grounded_catalog_tags(message, pool)


def covers_item(
    kept: Sequence[str],
    required: Sequence[str],
    fold_map: Mapping[str, str],
) -> bool:
    kept_keys = {fold_category(tag) for tag in kept}
    required_keys: list[str] = []
    seen: set[str] = set()
    for tag in required:
        key = fold_category(tag)
        if not key or key not in fold_map or key in seen:
            continue
        seen.add(key)
        required_keys.append(key)
    if len(required_keys) > CATEGORY_CAP_LIMIT:
        return kept_keys <= set(required_keys) and len(kept_keys) == CATEGORY_CAP_LIMIT
    return all(key in kept_keys for key in required_keys)


def _count_for(tag: str, counts: Mapping[str, int]) -> int:
    key = fold_category(tag) or tag.casefold()
    if key in counts:
        return int(counts[key])
    if tag in counts:
        return int(counts[tag])
    return 0


def fallback_category_tags(
    pool: Sequence[str],
    required: Sequence[str],
    counts: Mapping[str, int],
    *,
    limit: int = CATEGORY_CAP_LIMIT,
) -> tuple[str, ...]:
    """Grounded tags first, then highest sidecar df in the same pool."""

    fold_map = pool_fold_map(pool)
    required_orig: list[str] = []
    seen: set[str] = set()
    for tag in required:
        key = fold_category(tag)
        original = fold_map.get(key) if key else None
        if original is None or key in seen:
            continue
        seen.add(key)
        required_orig.append(original)

    def rank_key(tag: str) -> tuple[int, str]:
        folded = fold_category(tag) or tag.casefold()
        return (-_count_for(tag, counts), folded)

    if len(required_orig) >= limit:
        return tuple(sorted(required_orig, key=rank_key)[:limit])

    kept = list(required_orig)
    kept_keys = {fold_category(tag) for tag in kept}
    rest = [
        tag
        for tag in unique_category_tags(pool)
        if (fold_category(tag) or tag.casefold()) not in kept_keys
    ]
    rest.sort(key=rank_key)
    for tag in rest:
        if len(kept) >= limit:
            break
        kept.append(tag)
    return tuple(kept[:limit])


def load_category_product_counts(path: Path | None = None) -> dict[str, int]:
    """fold → df from sidecar slot_stats. Empty when the file is missing."""

    slots = path or _resolve_slots_file()
    if slots is None or not slots.is_file():
        return {}
    try:
        connection = sqlite3.connect(str(slots.resolve()))
    except sqlite3.Error:
        return {}
    try:
        rows = connection.execute(
            "SELECT canonical, df FROM slot_stats WHERE attribute = 'category'"
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
    counts: dict[str, int] = {}
    for canonical, df in rows:
        key = fold_category(canonical) or str(canonical).strip()
        if key and key not in counts:
            counts[key] = int(df)
    return counts


def _resolve_slots_file() -> Path | None:
    found = resolve_slots_path()
    if found is not None and found.is_file():
        return found
    repo = Path(__file__).resolve().parents[3] / DEFAULT_SLOTS_RELATIVE
    if repo.is_file():
        return repo
    return found


def category_cap_user_prompt(
    message: str,
    tags: Sequence[str],
    counts: Mapping[str, int] | None = None,
) -> str:
    stats = counts or {}
    lines = ["Allowed category tags (copy these strings):"]
    for tag in tags:
        df = _count_for(tag, stats) if stats else None
        if stats:
            lines.append(f"- {tag} (products: {df})")
        else:
            lines.append(f"- {tag}")
    lines.append(f"User message: {message}")
    return "\n".join(lines)


def apply_kept_to_rows(
    rows: Sequence[dict[str, Any]], kept: Sequence[str]
) -> list[dict[str, Any]]:
    fold_map = pool_fold_map(kept)
    kept_keys = set(fold_map)
    out: list[dict[str, Any]] = []
    for row in rows:
        raw = row.get("canonical") or ()
        values = [raw] if isinstance(raw, str) else list(raw)
        mapped: list[str] = []
        seen: set[str] = set()
        for item in values:
            key = fold_category(item)
            original = fold_map.get(key) if key in kept_keys else None
            if original is None or key in seen:
                continue
            seen.add(key)
            mapped.append(original)
        if not mapped:
            continue
        updated = dict(row)
        updated["canonical"] = mapped
        out.append(updated)
    return out


def cap_category_canonicals(
    message: str,
    tags: Sequence[str],
    *,
    complete: CompleteFn | None = None,
    product_counts: Mapping[str, int] | None = None,
) -> tuple[str, ...]:
    """Return at most five pool originals that cover the named item."""

    pool = unique_category_tags(tags)
    if len(pool) <= CATEGORY_CAP_LIMIT:
        skip_nodes("understand", "category_cap", why="at most 5 category tags")
        return pool

    fold_map = pool_fold_map(pool)
    required = required_grounded_tags(message, pool)
    counts = dict(product_counts) if product_counts is not None else load_category_product_counts()
    allowed = list(pool)

    for attempt in range(1, CATEGORY_CAP_ATTEMPTS + 1):
        emit(
            "understand",
            "category_cap",
            "running",
            {"attempt": attempt, "allowed": allowed},
        )
        payload = None
        if complete is not None:
            payload = complete(
                category_cap_user_prompt(message, pool, counts),
                system=_CATEGORY_CAP_PROMPT,
                num_predict=512,
            )
        kept = None
        raw_ids = parse_cap_ids(payload)
        if raw_ids is not None:
            resolved = resolve_model_ids(raw_ids, fold_map)
            if resolved is not None and covers_item(resolved, required, fold_map):
                kept = resolved
        if kept is not None:
            emit(
                "understand",
                "category_cap",
                "completed",
                {"attempt": attempt, "allowed": allowed, "kept": list(kept)},
            )
            return kept
        emit(
            "understand",
            "category_cap",
            "error",
            {"attempt": attempt, "allowed": allowed},
        )

    kept = fallback_category_tags(pool, required, counts)
    emit(
        "understand",
        "category_cap",
        "completed",
        {
            "attempt": CATEGORY_CAP_ATTEMPTS,
            "allowed": allowed,
            "kept": list(kept),
            "why": "slot_stats.df",
        },
    )
    return kept


def cap_category_payload(
    message: str,
    rows: Sequence[dict[str, Any]],
    *,
    complete: CompleteFn | None = None,
    product_counts: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Trim category JSON rows in place for inspect()."""

    if not rows:
        skip_nodes("understand", "category_cap", why="no category tags")
        return list(rows)
    tags = tags_from_category_rows(rows)
    kept = cap_category_canonicals(
        message,
        tags,
        complete=complete,
        product_counts=product_counts,
    )
    if len(tags) <= CATEGORY_CAP_LIMIT:
        return list(rows)
    return apply_kept_to_rows(rows, kept)
