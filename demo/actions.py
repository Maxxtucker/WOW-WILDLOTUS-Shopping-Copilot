"""Dynamic quick-reply chips from constraints + product trade-offs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import chainlit as cl

# Stable explore action — almost always shown last (unless a clarify trio fills the row).
MORE_LIKE_THIS = {
    "key": "more_like_this",
    "label": "More like this",
    "text": "More like this one would be nice",
    "icon": "heart",
    "tooltip": "More like this pick",
}

SOMETHING_DIFFERENT = {
    "key": "something_different",
    "label": "Something different",
    "text": "Maybe something different instead",
    "icon": "refresh-cw",
    "tooltip": "Try a different direction",
}

CHEAPER = {
    "key": "cheaper",
    "label": "Cheaper",
    "text": "I'd prefer something cheaper if possible",
    "icon": "arrow-down",
    "tooltip": "Show cheaper options",
}

NO_PREFERENCE = {
    "key": "no_preference",
    "label": "No preference",
    "text": "No strong preference — either is fine",
    "icon": "minus",
    "tooltip": "No preference on this",
}

# Phrase triggers → contextual refine actions (checked against dialog + product text).
_FEATURE_RULES: tuple[tuple[re.Pattern[str], dict[str, str], int], ...] = (
    (
        re.compile(r"breath|ventilat|airflow|mesh", re.I),
        {
            "key": "more_breathable",
            "label": "More breathable",
            "text": "I'd prefer something more breathable if possible",
            "icon": "wind",
            "tooltip": "Prioritize breathability",
        },
        10,
    ),
    (
        re.compile(r"cushion|plush|soft(er)?\s+land|gel\b|foam", re.I),
        {
            "key": "more_cushioned",
            "label": "More cushioning",
            "text": "I'd prefer something more cushioned if possible",
            "icon": "cloud",
            "tooltip": "Prioritize cushioning",
        },
        10,
    ),
    (
        re.compile(r"formal|dressy|elegant|dinner|wedding|black\s*tie", re.I),
        {
            "key": "more_formal",
            "label": "More formal",
            "text": "I'd prefer something a bit more formal if possible",
            "icon": "sparkles",
            "tooltip": "More formal options",
        },
        10,
    ),
    (
        re.compile(r"noise[\s-]*cancel|anc\b|quiet|commute", re.I),
        {
            "key": "better_noise",
            "label": "Better noise cancellation",
            "text": "I'd prefer better noise cancellation if possible",
            "icon": "headphones",
            "tooltip": "Stronger noise cancellation",
        },
        10,
    ),
    (
        re.compile(r"battery|charge\s*life|all[\s-]*day", re.I),
        {
            "key": "longer_battery",
            "label": "Longer battery",
            "text": "Longer battery would be nice to have if possible",
            "icon": "battery-charging",
            "tooltip": "Longer battery life",
        },
        10,
    ),
    (
        re.compile(r"light\s*weight|lighter|ultralight", re.I),
        {
            "key": "lighter",
            "label": "Lighter weight",
            "text": "I'd prefer a lighter option if possible",
            "icon": "feather",
            "tooltip": "Lighter weight",
        },
        10,
    ),
    (
        re.compile(r"trail|off[\s-]*road|hike", re.I),
        {
            "key": "more_trail",
            "label": "More trail-ready",
            "text": "I'd prefer something more trail-ready if possible",
            "icon": "mountain",
            "tooltip": "Better for trails",
        },
        8,
    ),
    (
        re.compile(r"waterproof|water[\s-]*resist|rain", re.I),
        {
            "key": "more_waterproof",
            "label": "More waterproof",
            "text": "I'd prefer something more waterproof if possible",
            "icon": "droplets",
            "tooltip": "More water resistance",
        },
        8,
    ),
    (
        re.compile(r"\bcolor|colour|black|white|blue|red|navy\b", re.I),
        {
            "key": "different_color",
            "label": "Different color",
            "text": "A different color would also be ok",
            "icon": "palette",
            "tooltip": "Try another color",
        },
        6,
    ),
)

_ASK_ATTRIBUTE_ACTIONS: dict[str, dict[str, str]] = {
    "budget": CHEAPER,
    "feature": {
        "key": "clarify_feature",
        "label": "Key feature",
        "text": "I'd prefer comfort as a feature if possible",
        "icon": "sparkles",
        "tooltip": "Name the feature that matters most",
    },
    "style": {
        "key": "different_style",
        "label": "Different style",
        "text": "I'd prefer a different style if possible",
        "icon": "refresh-cw",
        "tooltip": "Try another style",
    },
    "brand": {
        "key": "different_brand",
        "label": "Different brand",
        "text": "I'd prefer a different brand if possible",
        "icon": "store",
        "tooltip": "Try another brand",
    },
    "color": {
        "key": "different_color",
        "label": "Different color",
        "text": "A different color would also be ok",
        "icon": "palette",
        "tooltip": "Try another color",
    },
    "material": {
        "key": "different_material",
        "label": "Different material",
        "text": "I'd prefer a different material if possible",
        "icon": "layers",
        "tooltip": "Try another material",
    },
    "use_case": {
        "key": "clarify_use",
        "label": "Different use",
        "text": "Everyday wear would be nice to have if possible",
        "icon": "compass",
        "tooltip": "Adjust the use case",
    },
}

# When the agent asks a typed attribute, offer a focused A / B / no-pref row.
_CLARIFY_PROMPTS: dict[str, str] = {
    "feature": (
        "One thing would help me narrow this down:\n"
        "What matters more for your runs?"
    ),
    "style": (
        "One thing would help me narrow this down:\n"
        "What matters more — style or everyday comfort?"
    ),
    "budget": (
        "One thing would help me narrow this down:\n"
        "Should I prioritize a lower price?"
    ),
    "color": (
        "One thing would help me narrow this down:\n"
        "Do you have a color preference?"
    ),
    "material": (
        "One thing would help me narrow this down:\n"
        "Does material matter for this pick?"
    ),
    "brand": (
        "One thing would help me narrow this down:\n"
        "Do you want to stick to a preferred brand?"
    ),
    "use_case": (
        "One thing would help me narrow this down:\n"
        "What will you mainly use this for?"
    ),
}

_CLARIFY_ACTIONS: dict[str, tuple[dict[str, str], ...]] = {
    "feature": (
        {
            "key": "more_cushioned",
            "label": "More cushioning",
            "text": "I'd prefer something more cushioned if possible",
            "icon": "cloud",
            "tooltip": "Prioritize cushioning",
        },
        {
            "key": "lighter",
            "label": "Lighter weight",
            "text": "I'd prefer a lighter option if possible",
            "icon": "feather",
            "tooltip": "Prioritize lighter weight",
        },
        NO_PREFERENCE,
    ),
    "style": (
        {
            "key": "different_style",
            "label": "Different style",
            "text": "I'd prefer a different style if possible",
            "icon": "sparkles",
            "tooltip": "Prioritize style",
        },
        {
            "key": "everyday",
            "label": "Everyday comfort",
            "text": "Everyday comfort would be nice to have if possible",
            "icon": "heart",
            "tooltip": "Prioritize everyday comfort",
        },
        NO_PREFERENCE,
    ),
    "budget": (
        CHEAPER,
        {
            "key": "budget_ok",
            "label": "Budget is fine",
            "text": "My current budget is fine if possible",
            "icon": "check",
            "tooltip": "Keep the current budget",
        },
        NO_PREFERENCE,
    ),
    "color": (
        {
            "key": "different_color",
            "label": "Pick a color",
            "text": "I'd prefer black if possible",
            "icon": "palette",
            "tooltip": "Prefer a color",
        },
        {
            "key": "any_color",
            "label": "Any color",
            "text": "Any color is fine if possible",
            "icon": "check",
            "tooltip": "No color preference",
        },
        NO_PREFERENCE,
    ),
    "material": (
        {
            "key": "different_material",
            "label": "Different material",
            "text": "I'd prefer a different material if possible",
            "icon": "layers",
            "tooltip": "Prioritize material",
        },
        {
            "key": "material_flexible",
            "label": "Flexible",
            "text": "Material is flexible if possible",
            "icon": "check",
            "tooltip": "Material is flexible",
        },
        NO_PREFERENCE,
    ),
    "brand": (
        {
            "key": "different_brand",
            "label": "Preferred brand",
            "text": "I'd prefer a well-known brand if possible",
            "icon": "store",
            "tooltip": "Prefer a brand",
        },
        {
            "key": "brand_open",
            "label": "Keep it open",
            "text": "Brand can stay open if possible",
            "icon": "check",
            "tooltip": "No brand lock",
        },
        NO_PREFERENCE,
    ),
    "use_case": (
        {
            "key": "use_running",
            "label": "Running / jogging",
            "text": "I'd prefer this for running and jogging if possible",
            "icon": "compass",
            "tooltip": "Use for running",
        },
        {
            "key": "use_everyday",
            "label": "Everyday wear",
            "text": "Everyday wear would be nice to have if possible",
            "icon": "heart",
            "tooltip": "Everyday use",
        },
        NO_PREFERENCE,
    ),
}

_BUDGET_HINT = re.compile(
    r"\$\s*\d|\bunder\b|\bbudget\b|\bcheap(er)?\b|\baffordable\b|\bprice\b",
    re.I,
)


@dataclass(frozen=True)
class _Candidate:
    key: str
    label: str
    text: str
    icon: str
    tooltip: str
    priority: int


def clarification_prompt(
    ask_attribute: str | None,
    cards: list[dict[str, Any]],
) -> str | None:
    """Consumer-facing clarify sentence when we also have matching answer chips."""

    del cards
    if not ask_attribute:
        return None
    key = str(ask_attribute)
    # Only show a question when answer buttons exist (avoid mismatched copy).
    if key not in _CLARIFY_ACTIONS:
        return None
    return _CLARIFY_PROMPTS.get(key)


def _blob_from_state(state: Any) -> str:
    parts: list[str] = []
    if state is None:
        return ""
    latest = getattr(state, "latest_message", "") or ""
    parts.append(str(latest))
    history = getattr(state, "message_history", None) or []
    parts.extend(str(m) for m in history[-4:])
    for value in getattr(state, "ranking_constraints", ()) or ():
        parts.append(str(value))
    for slot in getattr(state, "typed_constraints", None) or []:
        surface = getattr(slot, "surface", None) or ""
        attribute = getattr(slot, "attribute", None) or ""
        parts.append(f"{attribute} {surface}")
    disclosed = getattr(state, "disclosed", None) or set()
    parts.extend(str(x) for x in disclosed)
    return "\n".join(parts)


def _blob_from_cards(cards: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for card in cards[:2]:
        parts.append(str(card.get("title") or ""))
        parts.append(str(card.get("blurb") or ""))
        parts.append(str(card.get("category") or ""))
        for tag in card.get("tags") or []:
            parts.append(str(tag))
    return "\n".join(parts)


def _budget_amount(state: Any) -> float | None:
    if state is None:
        return None
    best: float | None = None
    for slot in getattr(state, "typed_constraints", None) or []:
        if getattr(slot, "attribute", None) != "budget":
            continue
        amount = getattr(slot, "amount", None)
        if isinstance(amount, (int, float)):
            best = float(amount) if best is None else min(best, float(amount))
    return best


def _should_offer_cheaper(state: Any, cards: list[dict[str, Any]], dialog: str) -> bool:
    if "budget" in (getattr(state, "disclosed", None) or set()):
        return True
    if _budget_amount(state) is not None:
        return True
    if _BUDGET_HINT.search(dialog):
        return True
    budget = _budget_amount(state)
    if budget is not None and cards:
        price = cards[0].get("price")
        if isinstance(price, (int, float)) and float(price) >= 0.75 * budget:
            return True
    if len(cards) >= 2:
        p0 = cards[0].get("price")
        p1 = cards[1].get("price")
        if (
            isinstance(p0, (int, float))
            and isinstance(p1, (int, float))
            and float(p0) > float(p1) * 1.25
        ):
            return True
    return False


def _feature_candidates(dialog: str, product: str) -> list[_Candidate]:
    found: list[_Candidate] = []
    seen: set[str] = set()
    for pattern, action, priority in _FEATURE_RULES:
        if action["key"] in seen:
            continue
        in_dialog = bool(pattern.search(dialog))
        in_product = bool(pattern.search(product))
        if not in_dialog and not in_product:
            continue
        seen.add(action["key"])
        score = priority if in_dialog else max(1, priority - 2)
        found.append(
            _Candidate(
                key=action["key"],
                label=action["label"],
                text=action["text"],
                icon=action["icon"],
                tooltip=action["tooltip"],
                priority=score,
            )
        )
    return found


def _ask_candidate(ask_attribute: str | None) -> _Candidate | None:
    if not ask_attribute:
        return None
    action = _ASK_ATTRIBUTE_ACTIONS.get(str(ask_attribute))
    if not action:
        return None
    return _Candidate(
        key=action["key"],
        label=action["label"],
        text=action["text"],
        icon=action["icon"],
        tooltip=action["tooltip"],
        priority=4 if ask_attribute == "feature" else 7,
    )


def _tradeoff_candidates(cards: list[dict[str, Any]]) -> list[_Candidate]:
    if not cards:
        return []
    top = cards[0]
    out: list[_Candidate] = []
    rating = top.get("rating")
    if isinstance(rating, (int, float)) and float(rating) < 4.5:
        out.append(
            _Candidate(
                key="better_rated",
                label="Better rated",
                text="I'd prefer better rated options if possible",
                icon="star",
                tooltip="Higher rated picks",
                priority=5,
            )
        )
    out.append(
        _Candidate(
            key="different_style",
            label="Different style",
            text="I'd prefer a different style if possible",
            icon="refresh-cw",
            tooltip="Try another style",
            priority=3,
        )
    )
    return out


def _to_action(candidate: _Candidate | dict[str, str]) -> cl.Action:
    if isinstance(candidate, _Candidate):
        return cl.Action(
            name="quick_reply",
            payload={"text": candidate.text},
            label=candidate.label,
            icon=candidate.icon,
            tooltip=candidate.tooltip,
        )
    return cl.Action(
        name="quick_reply",
        payload={"text": candidate["text"]},
        label=candidate["label"],
        icon=candidate["icon"],
        tooltip=candidate["tooltip"],
    )


def _clarification_actions(ask_attribute: str | None) -> list[cl.Action] | None:
    if not ask_attribute:
        return None
    row = _CLARIFY_ACTIONS.get(str(ask_attribute))
    if not row:
        return None
    return [_to_action(item) for item in row[:3]]


def build_dynamic_actions(
    state: Any,
    cards: list[dict[str, Any]],
    *,
    ask_attribute: str | None = None,
    max_actions: int = 3,
) -> list[cl.Action]:
    """Return up to 3 chips: clarify trio, or contextual + More like this."""

    clarify = _clarification_actions(ask_attribute)
    if clarify:
        return clarify[:max_actions]

    dialog = _blob_from_state(state)
    product = _blob_from_cards(cards)
    last_message = ""
    if state is not None:
        last_message = str(getattr(state, "latest_message", "") or "").casefold()

    pool: list[_Candidate] = []
    seen: set[str] = set()

    def add(candidate: _Candidate | None) -> None:
        if candidate is None or candidate.key in seen:
            return
        if candidate.key in {MORE_LIKE_THIS["key"], SOMETHING_DIFFERENT["key"]}:
            return
        if last_message and (
            candidate.text.casefold() in last_message
            or last_message in candidate.text.casefold()
        ):
            return
        seen.add(candidate.key)
        pool.append(candidate)

    if _should_offer_cheaper(state, cards, dialog):
        add(
            _Candidate(
                key=CHEAPER["key"],
                label=CHEAPER["label"],
                text=CHEAPER["text"],
                icon=CHEAPER["icon"],
                tooltip=CHEAPER["tooltip"],
                priority=12,
            )
        )

    for candidate in _feature_candidates(dialog, product):
        add(candidate)

    add(_ask_candidate(ask_attribute))

    for candidate in _tradeoff_candidates(cards):
        add(candidate)

    pool.sort(key=lambda item: (-item.priority, item.label))

    # Requirement chips only — exploration lives under ProductShelf ("More like this").
    chosen = pool[:max_actions]
    if not chosen:
        chosen = [
            _Candidate(
                key=SOMETHING_DIFFERENT["key"],
                label=SOMETHING_DIFFERENT["label"],
                text=SOMETHING_DIFFERENT["text"],
                icon=SOMETHING_DIFFERENT["icon"],
                tooltip=SOMETHING_DIFFERENT["tooltip"],
                priority=1,
            )
        ]
    return [_to_action(item) for item in chosen[:max_actions]]
