#!/usr/bin/env python3
"""Print retrieval and dialog state for one generated synthetic session."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample_id")
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--seeds", default="data/synthetic_200k.jsonl")
    args = parser.parse_args()

    sample = next(
        (row for row in load_jsonl(args.seeds) if row["sample_id"] == args.sample_id),
        None,
    )
    if sample is None:
        raise SystemExit(f"Unknown sample: {args.sample_id}")

    catalog_ids, categories, products = catalog_index(args.catalog)
    card, behavior = materialize_hidden_fields(sample, products)
    effective = {**sample, "intent_card": card, "behavior": behavior}
    target = str(sample["ground_truth"]["parent_asin"])
    agent = Agent(args.catalog)
    session_id = f"diagnostic_{args.sample_id}"
    agent.reset(session_id, sample["user_profile"])
    disclosed: set[str] = set()
    boundary_used = False
    override_applied = sample["scenario_type"] != "intent_override"
    user_message = initial_message(
        effective,
        coarse_category(categories.get(target, [])),
        disclosed,
    )

    print(json.dumps({"sample": sample, "intent_card": card, "behavior": behavior}, indent=2))
    for turn in range(1, MAX_TURNS + 1):
        response = agent.respond(session_id, user_message, turn, 10)
        state = agent.sessions[session_id]
        hits = agent._retrieve(state)
        hit_ids = [hit.parent_asin for hit in hits]
        target_rank = hit_ids.index(target) + 1 if target in hit_ids else None
        ranked = normalize_recommendations(response["recommendations"], catalog_ids)
        print(
            json.dumps(
                {
                    "turn": turn,
                    "customer": user_message,
                    "gate_open": state.gate_open,
                    "constraints": state.ranking_constraints,
                    "excluded_count": len(state.excluded_asins),
                    "retrieval_count": len(hits),
                    "target_retrieval_rank": target_rank,
                    "ask_attribute": response["ask_attribute"],
                    "recommendations": ranked,
                    "target_recommended_rank": ranked.index(target) + 1 if target in ranked else None,
                },
                indent=2,
            )
        )
        if override_applied and target in ranked:
            break
        if turn == MAX_TURNS:
            continue
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


if __name__ == "__main__":
    main()
