"""Purpose: drop category branches that add an audience the shopper did not state.

Input: shopper message plus a tree node (label / id).
Output: True when the node names kids/women/men/... and the message does not.
Role: LLM category layers may still pick Kids Shoes because they share "shoe".
This check is the cheap half of "broader or equal": do not add gender, age, or
plus-size meaning that is absent from the utterance. L1 department roots are
not filtered here (empty ids vs a too-narrow child is the model's job).
"""

from __future__ import annotations

import re

from .category_tree import CategoryLayerDecision, CategoryNode, load_category_tree

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)

# One frozenset is one restriction family. A node that uses a family is kept
# only when the shopper message also uses that family.
_AUDIENCE_FAMILIES: tuple[frozenset[str], ...] = (
    frozenset({"kid", "kids", "child", "children"}),
    frozenset({"boy", "boys"}),
    frozenset({"girl", "girls"}),
    frozenset({"woman", "women", "womens", "lady", "ladies"}),
    frozenset({"man", "men", "mens"}),
    frozenset({"baby", "infant", "newborn"}),
    frozenset({"toddler"}),
    frozenset({"youth", "junior", "juniors"}),
    frozenset({"plus"}),
    frozenset({"petite"}),
    frozenset({"maternity"}),
)


def _tokens(text: str) -> set[str]:
    return {match.group(0).casefold() for match in _TOKEN_RE.finditer(text or "")}


def node_adds_unstated_audience(message: str, node: CategoryNode) -> bool:
    """True when the node's label/id adds kids/gender/age the message omitted."""

    shopper = _tokens(message)
    node_tokens = _tokens(node.label) | _tokens(node.id.replace("_", " "))
    for family in _AUDIENCE_FAMILIES:
        if node_tokens & family and not shopper & family:
            return True
    return False


def pool_is_department_roots(children: tuple[CategoryNode, ...]) -> bool:
    roots = load_category_tree()
    if not roots or not children:
        return False
    return {node.id for node in children} == {node.id for node in roots}


def filter_layer_decision(
    message: str,
    children: tuple[CategoryNode, ...],
    decision: CategoryLayerDecision,
) -> CategoryLayerDecision:
    """Drop unstated-audience ids. Empty ids after the drop means stop."""

    if pool_is_department_roots(children):
        return decision
    by_id = {node.id: node for node in children}
    by_fold = {node.id.casefold(): node for node in children}
    by_label = {node.label.casefold(): node for node in children}
    kept: list[str] = []
    seen: set[str] = set()
    for raw in decision.ids:
        key = str(raw or "").strip()
        if not key:
            continue
        node = (
            by_id.get(key)
            or by_fold.get(key.casefold())
            or by_label.get(key.casefold())
        )
        if node is None or node.id in seen:
            continue
        if node_adds_unstated_audience(message, node):
            continue
        seen.add(node.id)
        kept.append(node.id)
    return CategoryLayerDecision(ids=tuple(kept), stop=decision.stop or not kept)
