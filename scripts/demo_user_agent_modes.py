"""Small terminal demo for the four ScenarioUserAgent initial-message modes.

Examples:
    python scripts/demo_user_agent_modes.py
    python scripts/demo_user_agent_modes.py --samples 3 --seed 42

Modes 2-4 use the provider configured in the repository .env file.
Mode 1 is deterministic and does not call an LLM.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluator.local_evaluator import (  # noqa: E402
    coarse_category,
    catalog_index,
    load_jsonl,
    materialize_hidden_fields,
)
from evaluator.user_agent import OpenAICompatibleClient, ScenarioUserAgent  # noqa: E402


def short(value: object, limit: int = 180) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo only the four Buyer initial-message modes")
    parser.add_argument("--samples", type=int, default=3, help="number of random samples (default: 3)")
    parser.add_argument("--seed", type=int, default=None, help="random seed for reproducible samples")
    parser.add_argument("--dataset", default=str(ROOT / "data" / "public_set.jsonl"))
    parser.add_argument("--catalog", default=str(ROOT / "data" / "catalog.jsonl"))
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be at least 1")

    samples = load_jsonl(args.dataset)
    if not samples:
        raise RuntimeError("dataset is empty")
    _, categories, products = catalog_index(args.catalog)
    rng = random.Random(args.seed)
    chosen = rng.sample(samples, min(args.samples, len(samples)))

    # Constructing this once also shows which real provider the demo will use.
    client = OpenAICompatibleClient.from_environment()
    print("ScenarioUserAgent initial-message demo")
    print(f"samples={len(chosen)}, seed={args.seed}")
    print(f"provider={os.environ.get('CONVERGE_LLM_PROVIDER', 'from .env/default')}")
    print(f"model={client.model if client else '(no LLM client; Mode 1 only)'}")
    print("Note: only initial_message() is called; starter Agent is not run.\n")

    for index, raw_sample in enumerate(chosen, start=1):
        target = str(raw_sample["ground_truth"]["parent_asin"])
        card, behavior = materialize_hidden_fields(raw_sample, products)
        sample = {**raw_sample, "intent_card": card, "behavior": behavior}
        category = coarse_category(categories.get(target, []))
        print(f"=== Sample {index}: {raw_sample.get('sample_id')} / {raw_sample.get('scenario_type')} ===")
        print(f"category: {category}")
        print(f"hard constraint: {short((card.get('hard_constraints') or ['(none)'])[0])}")
        for mode in (1, 2, 3, 4):
            buyer = ScenarioUserAgent(mode=mode)
            disclosed: set[str] = set()
            message = buyer.initial_message(sample, category, disclosed)
            print(f"Mode {mode}: {message}")
        print()


if __name__ == "__main__":
    main()
