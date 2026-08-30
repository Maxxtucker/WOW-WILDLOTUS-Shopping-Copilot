"""Purpose: detect Amazon merchandising / promo category labels.

Input: a catalog category label (not an id).
Output: True when the label is a storefront sale, deal, or test shelf.
Role: drop those nodes from the NLU tree and classify prompts. Product-type
labels (Women, Shoes, Running) stay. Zero imports besides stdlib.
"""

from __future__ import annotations

import re

_MERCH_RE = re.compile(
    r"""
    (?:
        \d+\s*%\s*off
        | %\s*off
        | up\s+to\s+\d+\s*%
        | \$\s*\d[\d,]*\s+and\s+under
        | and\s+under\s+\$
        | under\s+\$\s*\d
        | starting\s+\$\s*\d
        | \bsales?\s*(?:&|and)\s*deals?\b
        | \bclearance\b
        | \boutlet\b
        | lightning\s+deal
        | deal\s+of\s+the\s+day
        | end\s+of\s+season\s+sale
        | \bprime\s+members?\b
        | exclusive\s+brands?
        | members?\s+exclusive
        | \d\+?\s*stars?\b
        | featured\s+brands?
        | no\s+title\s+match
        | 100%\s*plus
        | amazon\s+fashion\s+\d+
        | most[- ]loved
        | pasin\s+test
        | associates\s+top\s+products
        | curated\s+brands
        | bulk\s+buying
        | quantity\s+discounts
        | coinstar\s+exclusive
        | build\s+your\s+wardrobe
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def is_merchandising_label(label: str) -> bool:
    """True for promo/sale/test shelves, not classic product-type names."""

    text = (label or "").strip()
    if not text:
        return False
    return bool(_MERCH_RE.search(text))
