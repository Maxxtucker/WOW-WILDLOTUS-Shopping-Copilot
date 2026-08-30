"""Demo-only public_set selection and evaluator backends.

Measures the process Agent. Does not live in agent/ and does not change
evaluator/. Hidden intent cards stay inside evaluator helper calls. The
``local_evaluator`` backend uses the frozen deterministic evaluator; the
``agent_evaluator`` backend keeps the same scoring loop but generates customer
messages with :class:`evaluator.user_agent.ScenarioUserAgent`.
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
from evaluator.user_agent import ScenarioUserAgent

_REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SET_PATH = _REPO_ROOT / "data" / "public_set.jsonl"
CATALOG_PATH = _REPO_ROOT / "data" / "catalog.jsonl"

EVALUATORS = (
    {
        "id": "local_evaluator",
        "label": "local_evaluator",
        "path": "evaluator/local_evaluator.py",
        "enabled": True,
    },
    {
        "id": "agent_evaluator",
        "label": "agent_evaluator",
        "path": "evaluator/user_agent.py",
        "enabled": True,
    },
)

# Keep accepting the short IDs used by older open browser tabs and scripts.
_EVALUATOR_ALIASES = {
    "local": "local_evaluator",
    "agent": "agent_evaluator",
}


def normalize_evaluator(value: object) -> str:
    """Return a supported evaluator ID, preserving a useful error value."""

    raw = str(value or "").strip().casefold()
    return _EVALUATOR_ALIASES.get(raw, raw)


def evaluator_is_supported(value: object) -> bool:
    return normalize_evaluator(value) in {"local_evaluator", "agent_evaluator"}

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


def run_official_evaluate(agent: Any, samples: list[dict]) -> dict:
    """Run one selected evaluator backend on the selected rows."""

    return run_evaluate(agent, samples, "local_evaluator")


def run_evaluate(agent: Any, samples: list[dict], evaluator: object = "local_evaluator") -> dict:
    """Run either the frozen local loop or the ScenarioUserAgent loop."""

    evaluator_id = normalize_evaluator(evaluator)
    if evaluator_id not in {"local_evaluator", "agent_evaluator"}:
        raise ValueError(f"unsupported evaluator backend: {evaluator!r}")
    catalog_ids, categories, products = get_catalog_bundle()
    if evaluator_id == "local_evaluator":
        return evaluate(agent, samples, catalog_ids, categories, products)
    if evaluator_id == "agent_evaluator":
        return _evaluate_with_buyer(
            agent, samples, catalog_ids, categories, products, ScenarioUserAgent()
        )
    # The supported set is validated above; this branch keeps static type
    # checkers aware that every evaluator ID has an explicit dispatch.
    raise AssertionError(f"unhandled evaluator backend: {evaluator_id}")


def _evaluate_with_buyer(
    agent: Any,
    samples: list[dict],
    catalog_ids: set[str],
    categories: dict[str, list[str]],
    products: dict[str, dict],
    buyer: ScenarioUserAgent,
) -> dict:
    """Run the official scoring contract with a pluggable Buyer generator.

    This is deliberately kept in the demo harness: the contest evaluator
    remains the frozen deterministic reference implementation. The target,
    normalization, turn limit, override timing, and metric formulas mirror
    that reference; only the customer message source changes.
    """

    sessions: list[dict] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    for sample in samples:
        session_id = f"public_{uuid.uuid4().hex}"
        agent.reset(session_id, sample.get("user_profile") or {})
        target = str(sample["ground_truth"]["parent_asin"])
        card, behavior = materialize_hidden_fields(sample, products)
        effective_sample = {**sample, "intent_card": card, "behavior": behavior}
        disclosed: set[str] = set()
        boundary_used = False
        override_applied = sample["scenario_type"] != "intent_override"
        category = coarse_category(categories.get(target, []))
        buyer.reset(session_id, effective_sample, category)
        user_message = buyer.initial_message(session_id, disclosed)
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
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens")
                if isinstance(prompt_tokens, int) and prompt_tokens >= 0:
                    total_prompt_tokens += prompt_tokens
                if isinstance(completion_tokens, int) and completion_tokens >= 0:
                    total_completion_tokens += completion_tokens
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
                override_message = str(
                    override.get("message", "Actually, please ignore my earlier preference.")
                )
                user_message = buyer.override_message(
                    session_id, override_message, new_value
                )
            else:
                user_message, boundary_used = buyer.customer_reply(
                    session_id,
                    response.get("ask_attribute"),
                    disclosed,
                    boundary_used,
                )
        sessions.append(
            {
                "sample_id": sample["sample_id"],
                "scenario_type": sample["scenario_type"],
                "hit": hit_turn is not None,
                "first_hit_turn": hit_turn,
                "best_rank": best_rank,
                "reciprocal_rank": 0.0 if best_rank is None else 1.0 / best_rank,
            }
        )

    # Reuse the same summary helper as the step-through UI.  Besides keeping
    # the formulas in one place, this handles an empty injected sample list
    # without trying to convert ``mttc=None`` to float.
    summary = group_metrics(sessions)
    return {
        **summary,
        "reported_token_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
        },
    }


@dataclass
class StepState:
    """One Next click = one official customer turn + Agent.respond."""

    samples: list[dict]
    catalog_ids: set[str]
    categories: dict[str, list[str]]
    products: dict[str, dict]
    evaluator: str = "local_evaluator"
    buyer: ScenarioUserAgent | None = None
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

    @property
    def current_sample(self) -> dict:
        return self.samples[self.sample_index]

    @property
    def remaining(self) -> int:
        return max(0, len(self.samples) - self.sample_index)


def start_step_run(samples: list[dict], evaluator: object = "local_evaluator") -> StepState:
    if not samples:
        raise ValueError("no samples selected")
    catalog_ids, categories, products = get_catalog_bundle()
    evaluator_id = normalize_evaluator(evaluator)
    if evaluator_id not in {"local_evaluator", "agent_evaluator"}:
        raise ValueError(f"unsupported evaluator backend: {evaluator!r}")
    state = StepState(
        samples=list(samples),
        catalog_ids=catalog_ids,
        categories=categories,
        products=products,
        evaluator=evaluator_id,
        buyer=ScenarioUserAgent() if evaluator_id == "agent_evaluator" else None,
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
    if state.buyer is None:
        state.pending_message = initial_message(state.effective, category, state.disclosed)
    else:
        state.buyer.reset(state.session_id, state.effective, category)
        state.pending_message = state.buyer.initial_message(state.session_id, state.disclosed)
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
        override_message = str(
            override.get("message", "Actually, please ignore my earlier preference.")
        )
        state.pending_message = (
            state.buyer.override_message(state.session_id, override_message, new_value)
            if state.buyer is not None
            else override_message
        )
    else:
        if state.buyer is None:
            state.pending_message, state.boundary_used = customer_reply(
                state.effective,
                payload.get("ask_attribute"),
                state.disclosed,
                state.boundary_used,
            )
        else:
            state.pending_message, state.boundary_used = state.buyer.customer_reply(
                state.session_id,
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
