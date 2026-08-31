#!/usr/bin/env python3
"""Write the committed 3-level category tree used by understand NLU.

Runtime only reads the JSON. Re-run after catalog changes:

    python build_category_tree.py

L1 is Amazon roots (plus any extra catalog roots). Under a catalog L1, L2/L3
follow catalog paths. A child whose ``fold_category`` key equals its parent is
not kept as a layer: its tags (and any grandchildren) merge up. Siblings that
fold to the same key are one node. Nodes deeper than 3 become ``catalog_tags``
on the L3 leaf so every catalog category canonical is in the tree.
leaf so every catalog category canonical is in the tree. Merchandising / promo
pages (% off, sales & deals, Prime exclusive shelves, star filters, priced
"under $N" collections) are omitted so classify prompts list product types
only. Tags are ``fold_category`` keys (lowercase, no punctuation, no glue
words, singular tokens).

The same run writes ``category_parents.json``: unique child→parent plus
per-tag homes (parent + L1..L3) so catalog preprocess can align with this
tree without walking it per product.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PARENT = ROOT.parent
PROJECT = (
    _PARENT
    if (_PARENT / "evaluator").is_dir() and (_PARENT / "starter").is_dir()
    else ROOT
)
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from src.understand.observation.category_merch import is_merchandising_label
from preprocess.category_parents import build_parent_index
from preprocess.text import categories_list, category_tag_forms, fold_category, normalize_canonical

OUT = ROOT / "src" / "assets" / "aliases" / "category_tree.json"
PARENTS_OUT = ROOT / "src" / "assets" / "aliases" / "category_parents.json"
CATALOG = PROJECT / "data" / "catalog.jsonl"

AMAZON_L1 = (
    ("All_Beauty", "All Beauty"),
    ("Amazon_Fashion", "Amazon Fashion"),
    ("Appliances", "Appliances"),
    ("Arts_Crafts_and_Sewing", "Arts, Crafts and Sewing"),
    ("Automotive", "Automotive"),
    ("Baby_Products", "Baby Products"),
    ("Beauty_and_Personal_Care", "Beauty and Personal Care"),
    ("Books", "Books"),
    ("CDs_and_Vinyl", "CDs and Vinyl"),
    ("Cell_Phones_and_Accessories", "Cell Phones and Accessories"),
    ("Clothing_Shoes_and_Jewelry", "Clothing, Shoes and Jewelry"),
    ("Digital_Music", "Digital Music"),
    ("Electronics", "Electronics"),
    ("Gift_Cards", "Gift Cards"),
    ("Grocery_and_Gourmet_Food", "Grocery and Gourmet Food"),
    ("Handmade_Products", "Handmade Products"),
    ("Health_and_Household", "Health and Household"),
    ("Health_and_Personal_Care", "Health and Personal Care"),
    ("Home_and_Kitchen", "Home and Kitchen"),
    ("Industrial_and_Scientific", "Industrial and Scientific"),
    ("Kindle_Store", "Kindle Store"),
    ("Magazine_Subscriptions", "Magazine Subscriptions"),
    ("Movies_and_TV", "Movies and TV"),
    ("Musical_Instruments", "Musical Instruments"),
    ("Office_Products", "Office Products"),
    ("Patio_Lawn_and_Garden", "Patio, Lawn and Garden"),
    ("Pet_Supplies", "Pet Supplies"),
    ("Software", "Software"),
    ("Sports_and_Outdoors", "Sports and Outdoors"),
    ("Subscription_Boxes", "Subscription Boxes"),
    ("Tools_and_Home_Improvement", "Tools and Home Improvement"),
    ("Toys_and_Games", "Toys and Games"),
    ("Video_Games", "Video Games"),
    ("Unknown", "Unknown"),
)

_CATALOG_L1_TO_AMAZON = {
    normalize_canonical("Clothing, Shoes & Jewelry"): "Clothing_Shoes_and_Jewelry",
}

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _tags(*labels: str) -> list[str]:
    return category_tag_forms(*labels)


def node(node_id: str, label: str, tags: list[str] | None = None, children: list | None = None) -> dict:
    row: dict = {
        "id": node_id,
        "label": label,
        "catalog_tags": tags if tags is not None else _tags(label),
    }
    if children:
        row["children"] = children
    return row


def _slug(label: str, used: set[str]) -> str:
    base = _SLUG_RE.sub("", normalize_canonical(label).replace(" ", "_")).strip("_")
    if not base:
        base = "node"
    if base[0].isdigit():
        base = f"c_{base}"
    slug = base
    index = 2
    while slug in used:
        slug = f"{base}_{index}"
        index += 1
    used.add(slug)
    return slug


def iter_catalog_paths(catalog_path: Path | None = None) -> list[tuple[str, ...]]:
    """Unique non-empty category paths from catalog.jsonl."""

    source = catalog_path or CATALOG
    paths: set[tuple[str, ...]] = set()
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            cats = tuple(
                str(item).strip()
                for item in categories_list(row)
                if str(item).strip()
            )
            if cats:
                paths.add(cats)
    return sorted(paths)


def catalog_category_canonicals(catalog_path: Path | None = None) -> set[str]:
    """Every distinct catalog category node, folded like sidecar canonicals."""

    found: set[str] = set()
    for path in iter_catalog_paths(catalog_path):
        for label in path:
            folded = fold_category(label)
            if folded:
                found.add(folded)
    return found


def tree_catalog_tags(tree: dict) -> set[str]:
    """Union of catalog_tags on every node (including internal nodes)."""

    found: set[str] = set()

    def walk(raw: object) -> None:
        if not isinstance(raw, dict):
            return
        for tag in raw.get("catalog_tags") or ():
            folded = str(tag or "").strip()
            if folded:
                found.add(folded)
        for child in raw.get("children") or ():
            walk(child)

    for root in tree.get("roots") or ():
        walk(root)
    return found


def tree_path_tags(tree: dict) -> set[str]:
    """Tags a product path can hit: node catalog_tags plus folded labels."""

    found = set(tree_catalog_tags(tree))

    def walk(raw: object) -> None:
        if not isinstance(raw, dict):
            return
        folded = fold_category(raw.get("label") or "")
        if folded:
            found.add(folded)
        for child in raw.get("children") or ():
            walk(child)

    for root in tree.get("roots") or ():
        walk(root)
    return found


def product_category_tags(product: dict) -> list[str]:
    """Folded category nodes on one catalog product, path order, unique."""

    seen: set[str] = set()
    tags: list[str] = []
    for label in categories_list(product):
        folded = fold_category(label)
        if folded and folded not in seen:
            seen.add(folded)
            tags.append(folded)
    return tags


def products_missing_tree_path(
    catalog_path: Path | None = None,
    tree: dict | None = None,
) -> list[tuple[str, list[str]]]:
    """Products whose folded category path never hits the current tree."""

    source = catalog_path or CATALOG
    payload = tree
    if payload is None:
        if not OUT.is_file():
            return []
        payload = json.loads(OUT.read_text(encoding="utf-8"))
    on_tree = tree_path_tags(payload)
    missing: list[tuple[str, list[str]]] = []
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            tags = product_category_tags(row)
            if tags and any(tag in on_tree for tag in tags):
                continue
            asin = str(row.get("parent_asin") or "").strip() or "?"
            missing.append((asin, tags))
    return missing


def merchandising_catalog_folds(catalog_path: Path | None = None) -> set[str]:
    """Fold keys of merch nodes and every label under a merch ancestor."""

    dropped: set[str] = set()
    for path in iter_catalog_paths(catalog_path):
        drop_rest = False
        for label in path:
            if drop_rest or is_merchandising_label(label):
                drop_rest = True
                folded = fold_category(label)
                if folded:
                    dropped.add(folded)
    return dropped


def _descendant_tags(own_label: str, paths: list[tuple[str, ...]], *, from_index: int) -> list[str]:
    labels: list[str] = []
    if not is_merchandising_label(own_label):
        labels.append(own_label)
    for path in paths:
        for label in path[from_index:]:
            if is_merchandising_label(label):
                break
            labels.append(label)
    return _tags(*(labels or (own_label,)))


def _l2_l3_from_paths(paths: list[tuple[str, ...]]) -> list[dict]:
    by_l2: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for path in paths:
        if len(path) < 2:
            continue
        by_l2[path[1]].append(path)
    l2_nodes: list[dict] = []
    used_l2: set[str] = set()
    for l2_label in sorted(by_l2, key=str.casefold):
        if is_merchandising_label(l2_label):
            continue
        group = by_l2[l2_label]
        by_l3: dict[str, list[tuple[str, ...]]] = defaultdict(list)
        for path in group:
            if len(path) >= 3:
                by_l3[path[2]].append(path)
        children: list[dict] = []
        used_l3: set[str] = set()
        for l3_label in sorted(by_l3, key=str.casefold):
            if is_merchandising_label(l3_label):
                continue
            sub = by_l3[l3_label]
            children.append(
                node(
                    _slug(l3_label, used_l3),
                    l3_label,
                    _descendant_tags(l3_label, sub, from_index=3),
                )
            )
        l2_tags = (
            _descendant_tags(l2_label, group, from_index=2)
            if not children
            else _tags(l2_label)
        )
        l2_nodes.append(
            node(_slug(l2_label, used_l2), l2_label, l2_tags, children or None)
        )
    return [_collapse_fold_redundant(item) for item in l2_nodes]


def _merge_tags(*groups: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for tag in group:
            folded = str(tag or "").strip()
            if folded and folded not in seen:
                seen.add(folded)
                out.append(folded)
    return out


def _collapse_fold_redundant(raw: dict) -> dict:
    """Drop same-fold children and merge siblings that share a fold_category key."""

    children = [
        _collapse_fold_redundant(child)
        for child in (raw.get("children") or ())
        if isinstance(child, dict)
    ]
    parent_fold = fold_category(raw.get("label") or "")
    tags = list(raw.get("catalog_tags") or ())
    changed = True
    while changed:
        changed = False
        next_children: list[dict] = []
        for child in children:
            child_fold = fold_category(child.get("label") or "")
            if parent_fold and child_fold == parent_fold:
                tags = _merge_tags(tags, child.get("catalog_tags") or ())
                next_children.extend(
                    grand
                    for grand in (child.get("children") or ())
                    if isinstance(grand, dict)
                )
                changed = True
            else:
                next_children.append(child)
        children = next_children
        merged, sibling_changed = _merge_siblings_by_fold(children)
        if sibling_changed:
            changed = True
        children = merged
    out: dict = {
        "id": raw["id"],
        "label": raw["label"],
        "catalog_tags": tags,
    }
    if children:
        out["children"] = children
    return out


def _merge_siblings_by_fold(children: list[dict]) -> tuple[list[dict], bool]:
    by_fold: dict[str, dict] = {}
    order: list[str] = []
    changed = False
    for child in children:
        key = fold_category(child.get("label") or "") or str(child.get("id") or "")
        existing = by_fold.get(key)
        if existing is None:
            by_fold[key] = child
            order.append(key)
            continue
        changed = True
        existing["catalog_tags"] = _merge_tags(
            existing.get("catalog_tags") or [],
            child.get("catalog_tags") or [],
        )
        kids = [
            item
            for item in (*(existing.get("children") or ()), *(child.get("children") or ()))
            if isinstance(item, dict)
        ]
        if kids:
            existing["children"] = kids
            by_fold[key] = _collapse_fold_redundant(existing)
        else:
            existing.pop("children", None)
    return [by_fold[key] for key in order], changed


def _sports() -> dict:
    return node(
        "Sports_and_Outdoors",
        "Sports and Outdoors",
        _tags("athletic", "outdoor"),
        [
            node("running", "Running", _tags("running", "road running", "trail running")),
            node("hiking", "Hiking", _tags("hiking trekking", "hiking shoes", "hiking boots", "outdoor work")),
            node("team_sports", "Team sports", _tags("team sports", "basketball", "golf", "cycling", "skiing")),
        ],
    )


def _baby() -> dict:
    return node(
        "Baby_Products",
        "Baby Products",
        _tags("baby"),
        [
            node("baby_girls", "Baby girls", _tags("baby girls")),
            node("baby_boys", "Baby boys", _tags("baby boys")),
        ],
    )


def _phones() -> dict:
    return node(
        "Cell_Phones_and_Accessories",
        "Cell Phones and Accessories",
        [],
        [
            node(
                "phone_accessories",
                "Phone accessories",
                [],
                [node("power_banks", "Power banks", [])],
            )
        ],
    )


def build_tree(catalog_path: Path | None = None) -> dict:
    paths = iter_catalog_paths(catalog_path)
    by_l1: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for path in paths:
        by_l1[path[0]].append(path)

    amazon_from_catalog: dict[str, tuple[str, list[dict]]] = {}
    extra_roots: list[dict] = []
    used_extra: set[str] = set(node_id for node_id, _label in AMAZON_L1)
    for l1_label, group in sorted(by_l1.items(), key=lambda item: item[0].casefold()):
        folded = normalize_canonical(l1_label)
        amazon_id = _CATALOG_L1_TO_AMAZON.get(folded)
        children = _l2_l3_from_paths(group)
        l1_tags = _tags(l1_label)
        if amazon_id:
            amazon_from_catalog[amazon_id] = (l1_label, children)
            continue
        extra_roots.append(
            node(_slug(l1_label, used_extra), l1_label, l1_tags, children or None)
        )

    special = {
        "Sports_and_Outdoors": _sports(),
        "Baby_Products": _baby(),
        "Cell_Phones_and_Accessories": _phones(),
    }
    roots: list[dict] = []
    for node_id, label in AMAZON_L1:
        if node_id in amazon_from_catalog:
            catalog_label, children = amazon_from_catalog[node_id]
            roots.append(node(node_id, label, _tags(label, catalog_label), children))
            continue
        if node_id in special:
            roots.append(special[node_id])
            continue
        roots.append(node(node_id, label, []))
    roots.extend(extra_roots)
    roots = [_collapse_fold_redundant(item) for item in roots]
    return {"version": 1, "max_depth": 3, "roots": roots}


def main() -> None:
    if not CATALOG.is_file():
        raise SystemExit(f"Catalog not found: {CATALOG}")
    tree = build_tree()
    missing = (
        catalog_category_canonicals()
        - tree_catalog_tags(tree)
        - merchandising_catalog_folds()
    )
    if missing:
        sample = ", ".join(sorted(missing)[:12])
        raise SystemExit(f"{len(missing)} catalog categories missing from tree, e.g. {sample}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(tree, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    parents = build_parent_index(tree)
    PARENTS_OUT.write_text(
        json.dumps(parents, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {OUT} ({len(tree['roots'])} L1 roots, "
        f"{len(catalog_category_canonicals())} catalog tags covered)"
    )
    print(
        f"Wrote {PARENTS_OUT} "
        f"({len(parents['parent'])} unique parents, {len(parents['homes'])} homes)"
    )


if __name__ == "__main__":
    main()
