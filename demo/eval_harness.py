"""Demo-only public_set selection and official local-evaluator wrap.

Measures the process Agent. Does not live in agent/ and does not change
evaluator/. Hidden intent cards stay inside official helper calls.
"""

from __future__ import annotations

import random
import re
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evaluator.local_evaluator import (
    MAX_TURNS,
    TOP_K,
    catalog_index,
    coarse_category,
    customer_reply,
    evaluate,
    initial_message,
    load_jsonl,
    materialize_hidden_fields,
    metric_summary,
    normalize_recommendations,
)
from evaluator.scenario_evaluator import OpenAICompatibleClient, ScenarioEvaluator

_REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SET_PATH = _REPO_ROOT / "data" / "public_set.jsonl"
CATALOG_PATH = _REPO_ROOT / "data" / "catalog.jsonl"

EVALUATORS = (
    {
        "id": "local",
        "label": "Local evaluator",
        "path": "evaluator/local_evaluator.py",
        "enabled": True,
    },
    {
        "id": "scenario",
        "label": "Scenario evaluator",
        "path": "evaluator/scenario_evaluator.py",
        "enabled": True,
    },
    {
        "id": "hosted",
        "label": "Hosted evaluator",
        "path": "",
        "enabled": False,
    },
)

RUNNABLE_EVALUATORS = frozenset({"local", "scenario"})

_SAMPLE_ID_RE = re.compile(r"(?:public_)?(\d+)$", re.IGNORECASE)

_samples: list[dict] | None = None
_catalog: tuple[set[str], dict[str, list[str]], dict[str, dict]] | None = None
_load_lock = threading.Lock()


def load_public_set(path: Path | None = None) -> list[dict]:
    """Return public_set rows. Cached for the default path."""

    global _samples
    source = path or PUBLIC_SET_PATH
    if path is None:
        with _load_lock:
            if _samples is None:
                _samples = load_jsonl(source)
            return list(_samples)
    return load_jsonl(source)


def get_catalog_bundle(
    path: Path | None = None,
) -> tuple[set[str], dict[str, list[str]], dict[str, dict]]:
    """catalog_index for the demo catalog. Cached for the default path."""

    global _catalog
    source = path or CATALOG_PATH
    if path is None:
        with _load_lock:
            if _catalog is None:
                _catalog = catalog_index(source)
            return _catalog
    return catalog_index(source)


def sample_summaries(samples: list[dict] | None = None) -> list[dict]:
    """Safe picker rows: no ground_truth or intent cards."""

    rows = samples if samples is not None else load_public_set()
    out: list[dict] = []
    for index, sample in enumerate(rows, start=1):
        out.append(
            {
                "index": index,
                "sample_id": str(sample.get("sample_id") or ""),
                "scenario_type": str(sample.get("scenario_type") or ""),
                "difficulty_bucket": str(sample.get("difficulty_bucket") or ""),
                "category_bucket": str(sample.get("category_bucket") or ""),
            }
        )
    return out


def _parse_bound(value: object, samples: list[dict]) -> int:
    """Return a 0-based index from a 1-based line number or sample_id."""

    text = str(value or "").strip()
    if not text:
        raise ValueError("empty range bound")
    if text.isdigit():
        number = int(text)
        if 1 <= number <= len(samples):
            return number - 1
        raise ValueError(f"index {number} is outside 1..{len(samples)}")
    match = _SAMPLE_ID_RE.search(text)
    wanted = text
    if match and not text.lower().startswith("public_"):
        wanted = f"public_{match.group(1).zfill(4)}"
    for index, sample in enumerate(samples):
        if str(sample.get("sample_id") or "") == wanted:
            return index
        if str(sample.get("sample_id") or "") == text:
            return index
    raise ValueError(f"unknown sample {text!r}")


def select_samples(
    mode: str,
    *,
    samples: list[dict] | None = None,
    sample_id: str | None = None,
    start: str | int | None = None,
    end: str | int | None = None,
    n: int | None = None,
    rng: random.Random | None = None,
) -> list[dict]:
    """Pick a public_set slice. ``samples`` is injectable for tests."""

    rows = list(samples) if samples is not None else load_public_set()
    kind = (mode or "").strip().lower()
    if kind == "all":
        if not rows:
            raise ValueError("public_set is empty")
        return rows
    if kind == "one":
        index = _parse_bound(sample_id, rows)
        return [rows[index]]
    if kind == "range":
        left = _parse_bound(start, rows)
        right = _parse_bound(end, rows)
        if left > right:
            raise ValueError("range start is after end")
        return rows[left : right + 1]
    if kind == "random":
        try:
            count = int(n or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("random N must be an integer") from exc
        if count < 1:
            raise ValueError("random N must be at least 1")
        if count > len(rows):
            raise ValueError(f"random N {count} is larger than {len(rows)} samples")
        picker = rng if rng is not None else random.Random()
        return picker.sample(rows, count)
    raise ValueError(f"unknown selection mode {mode!r}")


def group_metrics(sessions: list[dict]) -> dict:
    """Same efficiency / technical_score formula as official evaluate()."""

    overall = metric_summary(sessions)
    if not sessions or overall.get("mttc") is None:
        return {
            **overall,
            "efficiency": 0.0,
            "recommended_technical_score": 0.0,
            "scenario_metrics": {},
            "sessions": sessions,
        }
    efficiency = max(0.0, min(1.0, (11.0 - float(overall["mttc"])) / 10.0))
    technical_score = (
        0.50 * overall["hit_rate_at_10"]
        + 0.30 * overall["mrr"]
        + 0.20 * efficiency
    )
    grouped: dict[str, list[dict]] = defaultdict(list)
    for session in sessions:
        grouped[str(session.get("scenario_type") or "")].append(session)
    return {
        **overall,
        "efficiency": round(efficiency, 6),
        "recommended_technical_score": round(technical_score, 6),
        "scenario_metrics": {
            name: metric_summary(grouped[name]) for name in sorted(grouped)
        },
        "sessions": sessions,
    }


def parse_buyer_mode(value: object) -> int:
    """Return Buyer mode 1-4. Empty values default to Mode 1."""

    if value is None or value == "":
        return 1
    try:
        mode = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("buyerMode must be 1, 2, 3, or 4") from exc
    if mode not in {1, 2, 3, 4}:
        raise ValueError("buyerMode must be 1, 2, 3, or 4")
    return mode


def buyer_has_llm_client() -> bool:
    """True when Modes 2-4 can call a configured OpenAI-compatible client."""

    return OpenAICompatibleClient.from_environment() is not None


def run_official_evaluate(agent: Any, samples: list[dict]) -> dict:
    """One official evaluate() call on the selected rows."""

    catalog_ids, categories, products = get_catalog_bundle()
    return evaluate(agent, samples, catalog_ids, categories, products)


def run_evaluate_with_buyer(
    agent: Any,
    samples: list[dict],
    mode: int = 1,
    *,
    catalog_ids: set[str] | None = None,
    categories: dict[str, list[str]] | None = None,
    products: dict[str, dict] | None = None,
) -> dict:
    """Same control flow as official evaluate(), with ScenarioEvaluator Buyer lines.

    Override turns still use ``behavior.override.message``. Scoring matches
    official ``evaluate()``. Catalog defaults to the demo bundle.
    """

    buyer = ScenarioEvaluator(mode=parse_buyer_mode(mode))
    if catalog_ids is None or categories is None or products is None:
        catalog_ids, categories, products = get_catalog_bundle()
    sessions: list[dict] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    for sample in samples:
        session_id = f"public_{uuid.uuid4().hex}"
        agent.reset(session_id, sample["user_profile"])
        target = str(sample["ground_truth"]["parent_asin"])
        effective_intent_card, effective_behavior = materialize_hidden_fields(
            sample, products
        )
        effective_sample = {
            **sample,
            "intent_card": effective_intent_card,
            "behavior": effective_behavior,
        }
        disclosed: set[str] = set()
        boundary_used = False
        override_applied = sample["scenario_type"] != "intent_override"
        user_message = buyer.initial_message(
            effective_sample,
            coarse_category(categories.get(target, [])),
            disclosed,
        )
        hit_turn: int | None = None
        best_rank: int | None = None
        for turn in range(1, MAX_TURNS + 1):
            try:
                response = agent.respond(session_id, user_message, turn, TOP_K)
            except Exception:
                response = {"message": "", "ask_attribute": None, "recommendations": []}
            if not isinstance(response, dict) or not isinstance(response.get("message"), str):
                response = {"message": "", "ask_attribute": None, "recommendations": []}
            usage = response.get("usage")
            if isinstance(usage, dict):
                if isinstance(usage.get("prompt_tokens"), int) and usage["prompt_tokens"] >= 0:
                    total_prompt_tokens += usage["prompt_tokens"]
                if isinstance(usage.get("completion_tokens"), int) and usage["completion_tokens"] >= 0:
                    total_completion_tokens += usage["completion_tokens"]
            ranked = normalize_recommendations(response.get("recommendations"), catalog_ids)
            if override_applied and target in ranked:
                best_rank = ranked.index(target) + 1
                hit_turn = turn
                break
            if turn == MAX_TURNS:
                break
            override = effective_sample.get("behavior", {}).get("override") or {}
            if not override_applied and turn + 1 == int(override.get("turn", 3)):
                override_applied = True
                new_value = str(override.get("new_value", ""))
                if new_value:
                    disclosed.add(new_value)
                user_message = str(
                    override.get("message", "Actually, please ignore my earlier preference.")
                )
            else:
                user_message, boundary_used = buyer.customer_reply(
                    effective_sample,
                    response.get("ask_attribute"),
                    disclosed,
                    boundary_used,
                )
        sessions.append({
            "sample_id": sample["sample_id"],
            "scenario_type": sample["scenario_type"],
            "hit": hit_turn is not None,
            "first_hit_turn": hit_turn,
            "best_rank": best_rank,
            "reciprocal_rank": 0.0 if best_rank is None else 1.0 / best_rank,
        })

    overall = metric_summary(sessions)
    efficiency = max(0.0, min(1.0, (11.0 - float(overall["mttc"])) / 10.0))
    technical_score = 0.50 * overall["hit_rate_at_10"] + 0.30 * overall["mrr"] + 0.20 * efficiency
    grouped: dict[str, list[dict]] = defaultdict(list)
    for session in sessions:
        grouped[session["scenario_type"]].append(session)
    return {
        **overall,
        "efficiency": round(efficiency, 6),
        "recommended_technical_score": round(technical_score, 6),
        "reported_token_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
        },
        "scenario_metrics": {name: metric_summary(grouped[name]) for name in sorted(grouped)},
        "sessions": sessions,
    }


@dataclass
class StepState:
    """One Next click = one official customer turn + Agent.respond."""

    samples: list[dict]
    catalog_ids: set[str]
    categories: dict[str, list[str]]
    products: dict[str, dict]
    sample_index: int = 0
    session_id: str = ""
    effective: dict = field(default_factory=dict)
    target: str = ""
    disclosed: set[str] = field(default_factory=set)
    boundary_used: bool = False
    override_applied: bool = True
    pending_message: str = ""
    turn: int = 1
    finished: list[dict] = field(default_factory=list)
    hit_turn: int | None = None
    best_rank: int | None = None
    cancelled: bool = False
    buyer: ScenarioEvaluator | None = None

    @property
    def current_sample(self) -> dict:
        return self.samples[self.sample_index]

    @property
    def remaining(self) -> int:
        return max(0, len(self.samples) - self.sample_index)


def start_step_run(
    samples: list[dict],
    buyer_mode: int | None = None,
) -> StepState:
    if not samples:
        raise ValueError("no samples selected")
    catalog_ids, categories, products = get_catalog_bundle()
    state = StepState(
        samples=list(samples),
        catalog_ids=catalog_ids,
        categories=categories,
        products=products,
        buyer=ScenarioEvaluator(mode=parse_buyer_mode(buyer_mode)) if buyer_mode is not None else None,
    )
    _begin_sample(state)
    return state


def _begin_sample(state: StepState) -> None:
    sample = state.current_sample
    card, behavior = materialize_hidden_fields(sample, state.products)
    state.effective = {**sample, "intent_card": card, "behavior": behavior}
    state.target = str(sample["ground_truth"]["parent_asin"])
    state.session_id = f"eval_{uuid.uuid4().hex}"
    state.disclosed = set()
    state.boundary_used = False
    state.override_applied = sample["scenario_type"] != "intent_override"
    category = coarse_category(state.categories.get(state.target, []))
    if state.buyer is not None:
        state.pending_message = state.buyer.initial_message(
            state.effective, category, state.disclosed
        )
    else:
        state.pending_message = initial_message(
            state.effective, category, state.disclosed
        )
    state.turn = 1
    state.hit_turn = None
    state.best_rank = None


def _session_row(state: StepState) -> dict:
    sample = state.current_sample
    return {
        "sample_id": sample["sample_id"],
        "scenario_type": sample["scenario_type"],
        "hit": state.hit_turn is not None,
        "first_hit_turn": state.hit_turn,
        "best_rank": state.best_rank,
        "reciprocal_rank": 0.0 if state.best_rank is None else 1.0 / state.best_rank,
    }


def apply_step_response(state: StepState, response: dict | None) -> dict:
    """Advance after one Agent.respond. Matches official evaluate() control flow."""

    payload = response if isinstance(response, dict) else {}
    if not isinstance(payload.get("message"), str):
        payload = {"message": "", "ask_attribute": None, "recommendations": []}
    ranked = normalize_recommendations(
        payload.get("recommendations"), state.catalog_ids
    )
    if state.override_applied and state.target in ranked:
        state.best_rank = ranked.index(state.target) + 1
        state.hit_turn = state.turn
        return _finish_sample(state)
    if state.turn >= MAX_TURNS:
        return _finish_sample(state)
    override = state.effective.get("behavior", {}).get("override") or {}
    if not state.override_applied and state.turn + 1 == int(override.get("turn", 3)):
        state.override_applied = True
        new_value = str(override.get("new_value", ""))
        if new_value:
            state.disclosed.add(new_value)
        state.pending_message = str(
            override.get("message", "Actually, please ignore my earlier preference.")
        )
    elif state.buyer is not None:
        state.pending_message, state.boundary_used = state.buyer.customer_reply(
            state.effective,
            payload.get("ask_attribute"),
            state.disclosed,
            state.boundary_used,
        )
    else:
        state.pending_message, state.boundary_used = customer_reply(
            state.effective,
            payload.get("ask_attribute"),
            state.disclosed,
            state.boundary_used,
        )
    state.turn += 1
    return {
        "session_done": False,
        "group_done": False,
        "next_message": state.pending_message,
        "turn": state.turn,
        "session_id": state.session_id,
    }


def _finish_sample(state: StepState) -> dict:
    row = _session_row(state)
    state.finished.append(row)
    state.sample_index += 1
    if state.sample_index >= len(state.samples):
        return {
            "session_done": True,
            "group_done": True,
            "session": row,
            "session_id": state.session_id,
        }
    _begin_sample(state)
    return {
        "session_done": True,
        "group_done": False,
        "session": row,
        "next_message": state.pending_message,
        "turn": state.turn,
        "session_id": state.session_id,
    }
