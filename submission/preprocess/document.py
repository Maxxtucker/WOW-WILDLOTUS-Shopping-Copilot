"""Purpose: fold title, details values, and description for later semantic compare.

Input: one catalog product dict.
Output: at most three (field, surface, canonical) rows. Not typed constraint slots.
Role: sidecar product_text only. Retrieve does not read this table yet.
"""

from __future__ import annotations

from collections.abc import Mapping

from .text import details_map, flatten_text, fold_document


def extract_documents(product: Mapping[str, object]) -> list[tuple[str, str, str]]:
    """Return (field, original surface, folded canonical) for non-empty blobs."""

    rows: list[tuple[str, str, str]] = []
    title = str(product.get("title") or "").strip()
    if title:
        folded = fold_document(title)
        if folded:
            rows.append(("title", title, folded))
    details = " ".join(
        value for value in details_map(product).values() if value.strip()
    ).strip()
    if details:
        folded = fold_document(details)
        if folded:
            rows.append(("details", details, folded))
    description = flatten_text(product.get("description")).strip()
    if description:
        folded = fold_document(description)
        if folded:
            rows.append(("description", description, folded))
    return rows
