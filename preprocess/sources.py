"""Purpose: details-key routing used by attribute extractors."""

from __future__ import annotations

COLOR_DETAIL_KEYS = frozenset(
    {"color", "colour", "color name", "colour name", "shade"}
)
MATERIAL_DETAIL_KEYS = frozenset(
    {"material", "fabric type", "fabric", "fiber", "fibre", "outer material"}
)
SIZE_DETAIL_KEYS = frozenset({"size", "size name", "size map"})


def _fold_detail_key(key: str) -> str:
    return " ".join(str(key or "").casefold().split())


def is_dimension_detail_key(key: str) -> bool:
    """True when a details key names object or package measurements."""

    return "dimension" in _fold_detail_key(key)


def is_brand_detail_key(key: str) -> bool:
    """True when a details key is a brand field (brand, product brand, …)."""

    return "brand" in _fold_detail_key(key)


def _detail_tokens(key: str) -> list[str]:
    return _fold_detail_key(key).replace("-", " ").split()


def is_style_detail_key(key: str) -> bool:
    """True when a details key names a style field (not lifestyle)."""

    return "style" in _detail_tokens(key)


def is_feature_detail_key(key: str) -> bool:
    """True when a details key names a feature field."""

    return "feature" in _detail_tokens(key)


def is_weight_detail_key(key: str) -> bool:
    """True when a details key names item or package weight (not lightweight)."""

    return "weight" in _detail_tokens(key)


STYLE_DETAIL_KEYS = frozenset({"fit type", "closure type", "pattern"})
USE_CASE_DETAIL_KEYS = frozenset({"sport type", "sport", "occasion", "theme"})
SKIP_OTHER_KEYS = frozenset(
    {
        "date first available",
        "item model number",
        "is discontinued by manufacturer",
        "best sellers rank",
        "country of origin",
        "part number",
        "package weight",
        "batteries",
        "batteries required",
        "manufacturer recommended age",
        "number of items",
        "item package quantity",
        "model name",
        "included components",
        "item weight",
        "manufacturer",
        "department",
    }
)
GENDER_MAP = {
    "womens": "womens",
    "women": "womens",
    "woman": "womens",
    "ladies": "womens",
    "mens": "mens",
    "men": "mens",
    "man": "mens",
    "girls": "girls",
    "girl": "girls",
    "boys": "boys",
    "boy": "boys",
    "baby": "baby",
    "unisex": "unisex",
    "kids": "kids",
    "kid": "kids",
}
