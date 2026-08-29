"""Purpose: details-key routing used by attribute extractors."""

from __future__ import annotations

COLOR_DETAIL_KEYS = frozenset(
    {"color", "colour", "color name", "colour name", "shade"}
)
MATERIAL_DETAIL_KEYS = frozenset(
    {"material", "fabric type", "fabric", "fiber", "fibre", "outer material"}
)
SIZE_DETAIL_KEYS = frozenset({"size", "size name", "size map"})
DIMENSION_DETAIL_KEYS = frozenset(
    {
        "product dimensions",
        "package dimensions",
        "item package dimensions l x w x h",
        "item dimensions lxwxh",
        "item dimensions  lxwxh",
    }
)
BRAND_DETAIL_KEYS = frozenset({"brand", "brand name"})
STYLE_DETAIL_KEYS = frozenset(
    {"style", "fit type", "neck style", "closure type", "pattern"}
)
FEATURE_DETAIL_KEYS = frozenset({"special feature", "special features"})
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
