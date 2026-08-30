"""Purpose: judge whether this utterance disclosed a category or attribute direction.

Input: the original shopper sentence plus this turn's grounded category/attribute rows.
Output: keep the extract, or void it when the utterance disclosed neither.
Role: last understand NLU node after category + attributes. Not a fold_category check.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from ...progress import emit
from .schema import ObservationExtract

DISCLOSURE_ATTEMPTS = 3
NUM_PREDICT_DISCLOSURE = 256

CompleteFn = Callable[..., dict[str, Any] | None]

_DISCLOSURE_PROMPT = """\
You judge whether this shopper utterance discloses a product category or any specific attribute direction.
The category and attribute rows below are what another extractor guessed from this turn. They may be wrong.

Return JSON only: {"empty": true} or {"empty": false}

empty is true only when the utterance itself does not name a product type or category and does not state any specific attribute direction (color, material, size, brand, style, budget, feature, use, or similar).
Acknowledgements, hedges, "ok", "sure", "show more", "not sure", and replies that add no preference are empty true.
If the shopper named a product type or any constraint direction, even softly, empty is false.

Category rows are product type. Attribute rows are constraint directions.
Do not invent category or attributes. Do not decide override, buying, or browsing.
"""


def parse_disclosure_empty(payload: dict[str, Any] | None) -> bool | None:
    """Accept only ``{"empty": true|false}``. Extra keys or bad types are illegal."""

    if not isinstance(payload, dict):
        return None
    if set(payload.keys()) != {"empty"}:
        return None
    raw = payload["empty"]
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.strip().casefold() in {"true", "false"}:
        return raw.strip().casefold() == "true"
    return None


def disclosure_user_prompt(message: str, extract: ObservationExtract) -> str:
    lines = [f"User message: {message}", "", "Extracted category:"]
    category_slots = [slot for slot in extract.slots if slot.attribute == "category"]
    if category_slots:
        for slot in category_slots:
            lines.append(_slot_line(slot.surface, slot.canonical, slot.is_hard))
    elif extract.category:
        lines.append(_slot_line(extract.category, None, True))
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("Extracted attributes:")
    other_slots = [slot for slot in extract.slots if slot.attribute != "category"]
    if not other_slots:
        lines.append("- (none)")
    else:
        for slot in other_slots:
            canon = ", ".join(slot.canonical) if slot.canonical else "(none)"
            lines.append(
                f"- attribute={slot.attribute} surface={slot.surface!r} "
                f"canonical=[{canon}] hard={slot.is_hard}"
            )
    return "\n".join(lines)


def apply_disclosure(
    extract: ObservationExtract,
    message: str,
    *,
    complete: CompleteFn,
) -> ObservationExtract:
    """Void the extract when the utterance disclosed neither category nor attributes."""

    prompt = disclosure_user_prompt(message, extract)
    for attempt in range(1, DISCLOSURE_ATTEMPTS + 1):
        emit(
            "understand",
            "disclosure",
            "running",
            {"attempt": attempt},
        )
        try:
            payload = complete(
                prompt,
                system=_DISCLOSURE_PROMPT,
                num_predict=NUM_PREDICT_DISCLOSURE,
            )
        except StopIteration:
            payload = None
        flag = parse_disclosure_empty(payload)
        if flag is not None:
            emit(
                "understand",
                "disclosure",
                "completed",
                {"empty": flag, "attempt": attempt},
            )
            if flag:
                return ObservationExtract(
                    empty=True,
                    source="llm",
                    repair_rounds=extract.repair_rounds,
                    disclosure_empty=True,
                )
            return replace(extract, disclosure_empty=False)
        emit(
            "understand",
            "disclosure",
            "error",
            {"attempt": attempt, "why": "invalid disclosure JSON"},
        )
    emit(
        "understand",
        "disclosure",
        "completed",
        {"empty": False, "why": "fail-open after 3 invalid replies"},
    )
    return replace(extract, disclosure_empty=False)


def _slot_line(
    surface: str,
    canonical: tuple[str, ...] | None,
    is_hard: bool,
) -> str:
    canon = ", ".join(canonical) if canonical else "(none)"
    return f"- surface={surface!r} canonical=[{canon}] hard={is_hard}"
