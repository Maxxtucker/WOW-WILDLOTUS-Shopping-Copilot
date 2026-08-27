#!/usr/bin/env python3
"""Audit all catalog helpers against the unmodified official evaluator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.domain import (
    card_constraints,
    classify_constraint,
    coarse_category,
    intent_card,
)
from agent.retrieve.catalog import build_response_signature
from evaluator.local_evaluator import (
    classify_constraint as official_classify_constraint,
    coarse_category as official_coarse_category,
    intent_card as official_intent_card,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    args = parser.parse_args()

    counts = {"products": 0, "intent_card": 0, "category": 0, "classifier": 0}
    examples: list[str] = []
    with Path(args.catalog).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            product = json.loads(line)
            counts["products"] += 1
            official_card = official_intent_card(product)
            domain_card = intent_card(product)
            signature = build_response_signature(product)
            signature_card = {
                "target_category": signature.target_category,
                "hard_constraints": list(signature.hard_constraints),
                "soft_preferences": list(signature.soft_preferences),
            }
            if domain_card != official_card or signature_card != official_card:
                counts["intent_card"] += 1
                if len(examples) < 5:
                    examples.append(f"line {line_number}: intent_card")

            categories = product.get("categories") or []
            if coarse_category(categories) != official_coarse_category(categories):
                counts["category"] += 1
                if len(examples) < 5:
                    examples.append(f"line {line_number}: coarse_category")

            for constraint in card_constraints(domain_card):
                if classify_constraint(constraint) != official_classify_constraint(constraint):
                    counts["classifier"] += 1
                    if len(examples) < 5:
                        examples.append(f"line {line_number}: classify_constraint")

    print(json.dumps({**counts, "examples": examples}, indent=2))
    if any(counts[key] for key in ("intent_card", "category", "classifier")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
