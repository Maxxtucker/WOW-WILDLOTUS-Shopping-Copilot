"""Purpose: category may be a top-level extract field or a typed slot.

Input: raw category value plus the original user message, or a parsed item.
Output: a copied span, or a ConstraintSlot with optional sidecar canonicals.
Role: surface is a span of the original shopper sentence (label, slug, tag, or
a token from those strings). catalog_tags stay classify keys for sidecar probe
and are not required to appear as a whole phrase.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ...schema import ground_span
from ..text import clean_surface
from ..types import ConstraintSlot, ParsedItem

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_CITE_GLUE = frozenset(
    {"and", "or", "the", "a", "an", "of", "for", "to", "in", "on", "with", "no"}
)
_MIN_CITE_TOKEN = 3


def ground_category(value: object, message: str) -> str | None:
    return ground_span(value, message)


def ground(parsed: ParsedItem, surface: str, message: str) -> ConstraintSlot | None:
    del message
    tags = tuple(dict.fromkeys(item.strip() for item in parsed.canonical_hints if item.strip()))
    cited = surface.strip()
    if not cited:
        return None
    return ConstraintSlot(
        attribute="category",
        surface=cited,
        canonical=tags or None,
        is_hard=parsed.is_hard,
    )


def surface_for_tags(message: str, *candidates: str) -> str | None:
    """Longest candidate that is a span of ``message``, else None."""

    best: str | None = None
    for raw in candidates:
        cleaned = clean_surface(raw)
        if not cleaned:
            continue
        grounded = ground_span(cleaned, message)
        if grounded is None:
            continue
        if best is None or len(grounded) > len(best):
            best = grounded
    return best


def cite_tokens(*texts: str) -> tuple[str, ...]:
    """Content tokens from labels/tags, for matching a shopper span."""

    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for token in _TOKEN_RE.findall(text or ""):
            folded = token.casefold()
            if len(folded) < _MIN_CITE_TOKEN or folded in _CITE_GLUE:
                continue
            if folded in seen:
                continue
            seen.add(folded)
            found.append(folded)
    return tuple(found)


def cite_category_node(
    message: str,
    *,
    label: str,
    node_id: str = "",
    tags: Sequence[str] = (),
) -> str | None:
    """Shopper span that corresponds to this tree node, or None."""

    slug = node_id.replace("_", " ")
    tag_list = tuple(tags)
    return surface_for_tags(
        message,
        label,
        slug,
        *tag_list,
        *cite_tokens(label, slug, *tag_list),
    )
