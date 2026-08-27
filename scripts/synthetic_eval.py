#!/usr/bin/env python3
"""Generate protocol-level sessions and run repeated 800-session evaluations.

The generated sessions contain only a target ASIN, a scenario, and an aggregate
profile.  Intent cards and customer replies are materialized by the unchanged
official evaluator at evaluation time, so this tool does not leak public labels
into the Agent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluator.local_evaluator import Agent as EvaluatorAgent
from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl


SCENARIO_COUNTS = {
    "buying": 320,
    "browsing": 320,
    "intent_override": 120,
    "boundary": 40,
}
SCENARIOS = tuple(SCENARIO_COUNTS)
PROFILE_TEMPLATES = (
    ("fit", "comfort", "durability"),
    ("material", "style", "quality"),
    ("weather", "warmth", "comfort"),
    ("value", "durability", "versatility"),
    ("color", "style", "fit"),
    ("performance", "comfort", "lightweight"),
)


def _profile(index: int, scenario: str) -> dict[str, object]:
    """Create an aggregate profile independent of the target product.

    The profile is intentionally not derived from catalog metadata.  This gives
    the baseline a cold-start-like profile while still exercising the API field.
    """

    digest = hashlib.sha256(f"profile:{index}:{scenario}".encode()).digest()
    tags = PROFILE_TEMPLATES[digest[0] % len(PROFILE_TEMPLATES)]
    rating = 1.0 + (digest[1] % 41) / 10.0
    frequency = ("0-1", "2-3", "3-4", "5+")[digest[2] % 4]
    style = ("critical", "mixed", "usually positive")[digest[3] % 3]
    return {
        "average_prior_rating": round(rating, 1),
        "preference_tags": list(tags),
        "purchase_frequency": f"{frequency} prior purchases",
        "rating_style": style,
        "summary": f"Prior purchases emphasize {', '.join(tags)}; ratings are {style}.",
    }


def iter_catalog_asins(catalog_path: str | Path) -> Iterable[str]:
    with Path(catalog_path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                product = json.loads(line)
                asin = str(product["parent_asin"]).strip()
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValueError(f"Invalid catalog row at line {line_number}") from exc
            if asin:
                yield asin


def generate_seeds(catalog_path: str | Path, output_path: str | Path) -> int:
    """Write exactly four scenario seeds per catalog product."""

    count = 0
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for index, asin in enumerate(iter_catalog_asins(catalog_path)):
            for scenario in SCENARIOS:
                seed = {
                    "sample_id": f"synthetic_{index:05d}_{scenario}",
                    "scenario_type": scenario,
                    "category_bucket": "clothing",
                    "difficulty_bucket": "synthetic",
                    "ground_truth": {"parent_asin": asin},
                    "user_profile": _profile(index, scenario),
                }
                handle.write(json.dumps(seed, ensure_ascii=True, separators=(",", ":")) + "\n")
                count += 1
    return count


class TracingAgent:
    """Proxy that preserves the official evaluator contract and records asks."""

    def __init__(self, catalog_path: str | Path) -> None:
        self.inner = EvaluatorAgent(catalog_path)
        self.responses: dict[str, list[dict[str, object]]] = defaultdict(list)

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.inner.reset(session_id, user_profile)
        self.responses.pop(session_id, None)

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        response = self.inner.respond(session_id, user_message, turn, top_k)
        self.responses[session_id].append(
            {
                "turn": int(turn),
                "ask_attribute": response.get("ask_attribute"),
                "recommendation_count": len(response.get("recommendations") or []),
            }
        )
        return response

    def clear_sessions(self) -> None:
        # The evaluator uses fresh random session IDs.  Clearing after each
        # round prevents the 100-round experiment from retaining old state.
        self.inner.sessions.clear()
        self.responses.clear()


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "stdev": None, "min": None, "p05": None, "p95": None, "max": None}
    return {
        "count": len(values),
        "mean": round(statistics.fmean(values), 6),
        "stdev": round(statistics.stdev(values), 6) if len(values) > 1 else 0.0,
        "min": round(min(values), 6),
        "p05": round(_quantile(values, 0.05) or 0.0, 6),
        "p95": round(_quantile(values, 0.95) or 0.0, 6),
        "max": round(max(values), 6),
    }


def _round_sample(
    seeds_by_scenario: dict[str, list[dict]],
    rng: random.Random,
) -> list[dict]:
    selected: list[dict] = []
    for scenario, count in SCENARIO_COUNTS.items():
        # random.sample makes every round a without-replacement draw inside a
        # scenario while preserving the requested competition proportions.
        selected.extend(rng.sample(seeds_by_scenario[scenario], count))
    rng.shuffle(selected)
    return selected


def evaluate_rounds(
    catalog_path: str | Path,
    seeds_path: str | Path,
    output_path: str | Path,
    *,
    rounds: int,
    seed: int,
    sample_size: int = 800,
) -> dict[str, object]:
    expected_size = sum(SCENARIO_COUNTS.values())
    if sample_size != expected_size:
        raise ValueError(f"sample_size must remain {expected_size} for the configured 40/40/15/5 mix")
    if rounds < 1:
        raise ValueError("rounds must be positive")

    all_seeds = load_jsonl(seeds_path)
    seeds_by_scenario: dict[str, list[dict]] = {scenario: [] for scenario in SCENARIOS}
    for item in all_seeds:
        scenario = str(item.get("scenario_type", ""))
        if scenario in seeds_by_scenario:
            seeds_by_scenario[scenario].append(item)
    if any(not values for values in seeds_by_scenario.values()):
        raise ValueError("seed file is missing one or more scenarios")

    catalog_ids, categories, products = catalog_index(catalog_path)
    agent = TracingAgent(catalog_path)
    rng = random.Random(seed)
    round_rows: list[dict[str, object]] = []
    scenario_metrics: dict[str, list[dict[str, float]]] = defaultdict(list)
    ask_counts: Counter[str] = Counter()
    ask_counts_by_scenario: dict[str, Counter[str]] = defaultdict(Counter)
    ask_counts_by_turn: Counter[str] = Counter()
    started = time.perf_counter()

    for round_number in range(1, rounds + 1):
        selected = _round_sample(seeds_by_scenario, rng)
        result = evaluate(agent, selected, catalog_ids, categories, products)
        row = {
            "round": round_number,
            "sample_count": len(selected),
            "hit_rate_at_10": result["hit_rate_at_10"],
            "mrr": result["mrr"],
            "mttc": result["mttc"],
            "efficiency": result["efficiency"],
            "recommended_technical_score": result["recommended_technical_score"],
            "scenario_metrics": result["scenario_metrics"],
        }
        round_rows.append(row)
        for scenario, metrics in result["scenario_metrics"].items():
            scenario_metrics[scenario].append(metrics)
        for session_id, traces in agent.responses.items():
            sample_scenario = None
            # Session IDs are random, so map the trace through the response
            # count only; scenario-level ask counts are computed from the
            # evaluator session rows below.
            _ = session_id
            for trace in traces:
                attribute = trace["ask_attribute"]
                label = "None" if attribute is None else str(attribute)
                ask_counts[label] += 1
                ask_counts_by_turn[f"{trace['turn']}:{label}"] += 1
        for sample_session in result["sessions"]:
            sample_scenario = str(sample_session["scenario_type"])
            # The tracing proxy does not receive sample IDs, so scenario ask
            # counts are intentionally reported only in aggregate by turn.
            _ = sample_scenario
        agent.clear_sessions()

    elapsed = time.perf_counter() - started
    output = {
        "experiment": "synthetic_protocol_repeated_draw",
        "catalog_product_count": len(catalog_ids),
        "seed_count": len(all_seeds),
        "rounds": rounds,
        "sample_size": sample_size,
        "scenario_mix": {key: value / sample_size for key, value in SCENARIO_COUNTS.items()},
        "draw_seed": seed,
        "elapsed_seconds": round(elapsed, 3),
        "round_metrics": round_rows,
        "aggregate_metrics": {
            metric: _summary([float(row[metric]) for row in round_rows])
            for metric in ("hit_rate_at_10", "mrr", "mttc", "efficiency", "recommended_technical_score")
        },
        "scenario_metric_distributions": {
            scenario: {
                metric: _summary([float(row[metric]) for row in rows])
                for metric in ("hit_rate_at_10", "mrr", "mttc")
            }
            for scenario, rows in sorted(scenario_metrics.items())
        },
        "ask_attribute_counts": dict(sorted(ask_counts.items())),
        "ask_attribute_by_turn": dict(sorted(ask_counts_by_turn.items(), key=lambda item: (int(item[0].split(":", 1)[0]), item[0]))),
        "notes": [
            "Seeds are generated from catalog products and official scenario rules; no public labels are read.",
            "Each round samples 320 buying, 320 browsing, 120 intent_override, and 40 boundary sessions.",
            "This is a protocol-level synthetic stress test, not a private leaderboard estimate.",
        ],
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="write four seeds per catalog product")
    generate.add_argument("--catalog", default="data/catalog.jsonl")
    generate.add_argument("--output", default="data/synthetic_200k.jsonl")

    evaluate_parser = subparsers.add_parser("evaluate", help="sample and evaluate repeated 800-session rounds")
    evaluate_parser.add_argument("--catalog", default="data/catalog.jsonl")
    evaluate_parser.add_argument("--seeds", default="data/synthetic_200k.jsonl")
    evaluate_parser.add_argument("--output", default="artifacts/synthetic_eval.json")
    evaluate_parser.add_argument("--rounds", type=int, default=100)
    evaluate_parser.add_argument("--seed", type=int, default=20260827)
    evaluate_parser.add_argument("--sample-size", type=int, default=800)

    args = parser.parse_args()
    if args.command == "generate":
        count = generate_seeds(args.catalog, args.output)
        print(json.dumps({"output": str(args.output), "seed_count": count}, indent=2))
        return
    result = evaluate_rounds(
        args.catalog,
        args.seeds,
        args.output,
        rounds=args.rounds,
        seed=args.seed,
        sample_size=args.sample_size,
    )
    print(json.dumps({key: value for key, value in result.items() if key not in {"round_metrics", "ask_attribute_by_turn"}}, indent=2))


if __name__ == "__main__":
    main()
