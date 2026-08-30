"""Turn recommendation ASINs into ProductCard props."""

from __future__ import annotations

from typing import Any

from demo.images import resolve_image_url

# Soft brand accents for the image placeholder (dark UI).
_ACCENTS = (
    "#4A7C59",
    "#3D6B8C",
    "#8B5E3C",
    "#6B4C7A",
    "#4F6F8F",
    "#7A5C3E",
)


def _short_title(title: str, limit: int = 72) -> str:
    title = (title or "").strip()
    if len(title) <= limit:
        return title
    return title[: limit - 1].rstrip() + "…"


def _leaf_category(categories: list | None) -> str:
    if not categories:
        return ""
    parts = [str(c).strip() for c in categories if c]
    return parts[-1] if parts else ""


def _blurb(product: dict[str, Any]) -> str:
    for feat in product.get("features") or []:
        if isinstance(feat, str) and len(feat.strip()) > 24:
            text = feat.strip()
            return text if len(text) <= 100 else text[:99] + "…"
    return ""


def _accent_for(parent_asin: str) -> str:
    if not parent_asin:
        return _ACCENTS[0]
    return _ACCENTS[sum(ord(c) for c in parent_asin) % len(_ACCENTS)]


def _shopping_tags(product: dict[str, Any]) -> list[str]:
    """Short chips that feel like shopping filters, not DB fields."""

    tags: list[str] = []
    leaf = _leaf_category(product.get("categories"))
    if leaf:
        tags.append(leaf)

    price = product.get("price")
    if isinstance(price, (int, float)):
        if price < 50:
            tags.append("Under $50")
        elif price < 100:
            tags.append("Under $100")
        elif price <= 150:
            tags.append("Under $150")

    store = str(product.get("store") or "").strip()
    if store and store not in tags and len(tags) < 3:
        tags.append(store)

    return tags[:3]


def to_card(
    product: dict[str, Any] | None,
    parent_asin: str,
    *,
    image_index: dict[str, str] | None = None,
    on_slate: bool = False,
) -> dict[str, Any]:
    """Build one ProductCard props dict from a catalog product."""

    p = product or {}
    return {
        "parent_asin": parent_asin,
        "title": _short_title(str(p.get("title") or parent_asin)),
        "price": p.get("price"),
        "store": str(p.get("store") or ""),
        "rating": p.get("average_rating"),
        "category": _leaf_category(p.get("categories")),
        "blurb": _blurb(p),
        "tags": _shopping_tags(p),
        "accent": _accent_for(parent_asin),
        "image_url": resolve_image_url(p, parent_asin, image_index),
        "on_slate": bool(on_slate),
    }


def hydrate_many(
    retriever: Any,
    recommendations: list[dict],
    *,
    limit: int = 10,
    image_index: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Resolve the head of a recommendations list into card props."""

    cards: list[dict[str, Any]] = []
    for row in recommendations[:limit]:
        asin = str((row or {}).get("parent_asin") or "").strip()
        if not asin:
            continue
        product = retriever.get_product(asin)
        cards.append(
            to_card(
                product,
                asin,
                image_index=image_index,
                on_slate=bool((row or {}).get("on_slate")),
            )
        )
    return cards


def expand_recommendations_for_ui(
    retriever: Any,
    state: Any,
    recommendations: list[dict],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Take last_ranked head for display. Mark official protocol slate ASINs.

    Do not call retrieve again. A second hybrid pass over the full catalog
    blocked the Chainlit reply after Decide had already finished.
    """

    del retriever
    slate: set[str] = set()
    official: list[str] = []
    for row in recommendations or []:
        asin = str((row or {}).get("parent_asin") or "").strip()
        if not asin or asin in slate:
            continue
        official.append(asin)
        slate.add(asin)

    ranked: list[str] = []
    if state is not None:
        for asin in getattr(state, "last_ranked", None) or []:
            asin = str(asin or "").strip()
            if asin:
                ranked.append(asin)

    ordered: list[str] = []
    seen: set[str] = set()
    source = ranked if ranked else official
    for asin in source:
        if asin in seen:
            continue
        ordered.append(asin)
        seen.add(asin)
        if len(ordered) >= limit:
            break
    return [
        {"parent_asin": asin, "on_slate": asin in slate}
        for asin in ordered[:limit]
    ]
