#!/usr/bin/env python3
"""Print one reproducible end-to-end public demonstration session."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluator.local_evaluator import (
    MAX_TURNS,
    catalog_index,
    coarse_category,
    customer_reply,
    initial_message,
    load_jsonl,
    materialize_hidden_fields,
    normalize_recommendations,
)
from starter.agent import Agent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", default="public_0002")
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    args = parser.parse_args()

    samples = load_jsonl(args.dataset)
    sample = next((item for item in samples if item["sample_id"] == args.sample), None)
    if sample is None:
        raise SystemExit(f"Unknown sample: {args.sample}")
    catalog_ids, categories, products = catalog_index(args.catalog)
    card, behavior = materialize_hidden_fields(sample, products)
    effective = {**sample, "intent_card": card, "behavior": behavior}
    target = str(sample["ground_truth"]["parent_asin"])

    agent = Agent(args.catalog)
    session_id = f"demo_{args.sample}"
    agent.reset(session_id, sample["user_profile"])
    disclosed: set[str] = set()
    boundary_used = False
    override_applied = sample["scenario_type"] != "intent_override"
    user_message = initial_message(
        effective,
        coarse_category(categories.get(target, [])),
        disclosed,
    )

    print(f"Sample: {args.sample} ({sample['scenario_type']})")
    for turn in range(1, MAX_TURNS + 1):
        print(f"\nCustomer [{turn}]: {user_message}")
        response = agent.respond(session_id, user_message, turn, 10)
        ranked = normalize_recommendations(response["recommendations"], catalog_ids)
        print(f"Agent [{turn}]: {response['message']}")
        print(f"ask_attribute={response['ask_attribute']!r}")
        print("recommendations=" + json.dumps(ranked))
        if override_applied and target in ranked:
            print(f"\nHIT: turn={turn}, rank={ranked.index(target) + 1}")
            return
        if turn == MAX_TURNS:
            break
        override = effective.get("behavior", {}).get("override") or {}
        if not override_applied and turn + 1 == int(override.get("turn", 3)):
            override_applied = True
            new_value = str(override.get("new_value", ""))
            if new_value:
                disclosed.add(new_value)
            user_message = str(override.get("message"))
        else:
            user_message, boundary_used = customer_reply(
                effective,
                response.get("ask_attribute"),
                disclosed,
                boundary_used,
            )
    print("\nMISS after turn 10")


if __name__ == "__main__":
    main()
