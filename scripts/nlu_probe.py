#!/usr/bin/env python3
"""Probe local NLU against hand-written shopper utterances.

Does not read public_set.jsonl or clone evaluator templates. Default mode
checks that fixture spans are grounded and reports what regex-only extract
would capture. Pass --live to load ``scripts/nlu.env`` and call Ollama.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.understand.mode import MODE_NLU, configure_understand
from agent.understand.observation.hybrid import extract_from_regex, regex_is_high_confidence
from agent.understand.observation.llm_nlu import OllamaNluClient, load_nlu_env
from agent.understand.observation.schema import (
    ObservationExtract,
    infer_track,
    span_grounded,
)
from agent.understand.state import SessionState

# Hand-written natural-language cases. Expected values must appear in the message.
FIXTURES: tuple[dict[str, object], ...] = (
    {"id": "run_in", "message": "Need something I can run in.", "category": "run", "track": "browsing"},
    {"id": "leather_train", "message": "Need leather running shoes I can train in.", "category": "running shoes", "constraints": ["leather"], "track": "buying"},
    {"id": "under_budget", "message": "Looking for sandals, under $40.", "category": "sandals", "constraints": ["under $40"], "track": "buying"},
    {"id": "explore_boots", "message": "Just browsing winter boots, nothing locked in.", "category": "winter boots", "track": "browsing"},
    {"id": "gift_vague", "message": "Shopping for a gift, still figuring it out.", "track": "browsing"},
    {"id": "black_dress", "message": "I want a black dress for a wedding.", "category": "dress", "constraints": ["black", "wedding"], "track": "buying"},
    {"id": "cotton_tee", "message": "Cotton t-shirts, nothing fancy.", "category": "t-shirts", "constraints": ["Cotton"], "track": "buying"},
    {"id": "size_ten", "message": "These have to be size 10.", "constraints": ["size 10"], "track": "buying"},
    {"id": "no_pref", "message": "No preference on color.", "empty": True},
    {"id": "use_judgment", "message": "I don't have a preference; please use your judgment.", "empty": True},
    {"id": "not_quite", "message": "Not quite right, keep looking.", "empty": True},
    {"id": "waterproof_swap", "message": "Forget the blue ones — I want waterproof instead.", "constraints": ["waterproof"], "override": True, "track": "buying"},
    {"id": "changed_mind", "message": "Changed my mind, go with leather not suede.", "constraints": ["leather"], "override": True, "track": "buying"},
    {"id": "rather_silk", "message": "Rather silk than polyester.", "constraints": ["silk"], "override": True, "track": "buying"},
    {"id": "kids_sneakers", "message": "Sneakers for my kid, maybe navy.", "category": "Sneakers", "constraints": ["navy"], "track": "buying"},
    {"id": "wide_fit", "message": "I need a wide fit, my feet swell.", "constraints": ["wide fit"], "track": "buying"},
    {"id": "wool_coat", "message": "A wool coat for commuting in the rain.", "category": "coat", "constraints": ["wool"], "track": "buying"},
    {"id": "cheap_flip", "message": "Any cheap flip flops are fine.", "category": "flip flops", "track": "browsing"},
    {"id": "red_or_not", "message": "Red is okay but not required.", "track": "browsing"},
    {"id": "office_shoes", "message": "Something professional for the office.", "constraints": ["office"], "track": "buying"},
    {"id": "hiking", "message": "Hiking boots that can take mud.", "category": "Hiking boots", "track": "buying"},
    {"id": "budget_80", "message": "Keep it under $80 please.", "constraints": ["under $80"], "track": "buying"},
    {"id": "no_leather", "message": "Please not leather, I want canvas.", "constraints": ["canvas"], "track": "buying"},
    {"id": "still_looking", "message": "Still looking around, maybe sandals?", "category": "sandals", "track": "browsing"},
    {"id": "gold_hoops", "message": "Small gold hoops, nothing huge.", "constraints": ["gold"], "track": "buying"},
    {"id": "silk_scarf", "message": "A silk scarf if you have one.", "category": "scarf", "constraints": ["silk"], "track": "buying"},
    {"id": "belt_brown", "message": "Brown leather belt, 34 waist.", "category": "belt", "constraints": ["Brown leather"], "track": "buying"},
    {"id": "yoga_pants", "message": "Yoga pants, high waist, black.", "category": "Yoga pants", "constraints": ["high waist", "black"], "track": "buying"},
    {"id": "slippers", "message": "Cozy slippers for around the house.", "category": "slippers", "track": "browsing"},
    {"id": "replace_navy", "message": "Replace navy with olive.", "constraints": ["olive"], "override": True, "track": "buying"},
    {"id": "ignore_earlier", "message": "Ignore that, I need rubber soles.", "constraints": ["rubber soles"], "override": True, "track": "buying"},
    {"id": "color_later", "message": "Color doesn't matter yet.", "empty": True},
    {"id": "must_have_zip", "message": "Must have a zipper, not buttons.", "constraints": ["zipper"], "track": "buying"},
    {"id": "ankle_boots", "message": "Ankle boots, low heel.", "category": "Ankle boots", "constraints": ["low heel"], "track": "buying"},
    {"id": "summer_hat", "message": "A summer hat for the beach.", "category": "hat", "constraints": ["beach"], "track": "buying"},
    {"id": "watch_band", "message": "Just browsing watch bands.", "category": "watch bands", "track": "browsing"},
    {"id": "socks_wool", "message": "Wool hiking socks, pair of them.", "category": "socks", "constraints": ["Wool"], "track": "buying"},
    {"id": "jacket_light", "message": "Lightweight jacket, packable.", "category": "jacket", "constraints": ["Lightweight"], "track": "buying"},
    {"id": "new_plan_suede", "message": "New plan: suede loafers.", "category": "loafers", "constraints": ["suede"], "override": True, "track": "buying"},
    {"id": "additional_none", "message": "No additional preference.", "empty": True},
)


def _check_fixture(case: dict[str, object]) -> list[str]:
    message = str(case["message"])
    errors: list[str] = []
    category = case.get("category")
    if isinstance(category, str) and not span_grounded(category, message):
        errors.append(f"category {category!r} is not a span")
    for item in case.get("constraints") or ():
        if not span_grounded(str(item), message):
            errors.append(f"constraint {item!r} is not a span")
    override_value = case.get("override_value")
    if isinstance(override_value, str) and not span_grounded(override_value, message):
        errors.append(f"override_value {override_value!r} is not a span")
    return errors


def _regex_summary(message: str) -> dict[str, object]:
    state = SessionState("probe", {})
    extract = extract_from_regex(state, message)
    return {
        "high_confidence": regex_is_high_confidence(message),
        "category": extract.category,
        "constraints": list(extract.constraints),
        "override": extract.override,
        "track": infer_track(extract),
        "empty": extract.empty,
    }


def _extract_summary(extract: ObservationExtract | None, elapsed_ms: float) -> dict[str, object]:
    if extract is None:
        return {"ok": False, "error": "nlu_failed", "elapsed_ms": round(elapsed_ms, 1)}
    return {
        "ok": True,
        "empty": extract.empty,
        "category": extract.category,
        "constraints": list(extract.constraints),
        "override": extract.override,
        "override_value": extract.override_value,
        "track": infer_track(extract),
        "elapsed_ms": round(elapsed_ms, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call the local Ollama model. Loads scripts/nlu.env first.",
    )
    args = parser.parse_args()
    if args.live:
        load_nlu_env()
        configure_understand(MODE_NLU)

    fixture_errors = 0
    regex_hits = 0
    rows: list[dict[str, object]] = []
    client = OllamaNluClient.from_env() if args.live else None
    live_ok = 0
    live_fail = 0
    latencies: list[float] = []

    for case in FIXTURES:
        message = str(case["message"])
        errors = _check_fixture(case)
        if errors:
            fixture_errors += 1
        regex = _regex_summary(message)
        if regex["category"] or regex["constraints"] or regex["override"]:
            regex_hits += 1
        row: dict[str, object] = {
            "id": case["id"],
            "message": message,
            "fixture_errors": errors,
            "regex": regex,
        }
        if client is not None:
            started = time.perf_counter()
            extract = client.extract(message)
            elapsed_ms = (time.perf_counter() - started) * 1000
            latencies.append(elapsed_ms)
            summary = _extract_summary(extract, elapsed_ms)
            row["nlu"] = summary
            if extract is None:
                live_fail += 1
            else:
                live_ok += 1
        rows.append(row)

    report = {
        "fixture_count": len(FIXTURES),
        "fixture_errors": fixture_errors,
        "regex_structured_hits": regex_hits,
        "live": bool(args.live),
        "live_ok": live_ok,
        "live_fail": live_fail,
        "latency_ms": {
            "mean": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "max": round(max(latencies), 1) if latencies else None,
        },
        "cases": rows,
    }
    print(json.dumps(report, indent=2))
    if fixture_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
