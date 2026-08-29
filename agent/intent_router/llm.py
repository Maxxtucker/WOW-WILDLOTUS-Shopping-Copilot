"""Purpose: independent Ollama JSON client for intention routing.

Input: host/model/timeout from the same env as observation NLU.
Output: OverrideDecision (level 0/1/2), or buying/browsing label.
Role: separate process-wide client from observation.extract. No regex fallback.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..understand.observation.category_fold import fold_category
from ..understand.observation.llm_nlu import (
    DEFAULT_HOST,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    nlu_host,
    nlu_model,
    nlu_timeout,
)
from .writeback import delta_has_category, incoming_category

if TYPE_CHECKING:
    from ..understand.state.session import SessionState

ATTEMPTS = 3
NUM_PREDICT = 256
NUM_CTX = 8192
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

OVERRIDE_L1_SYSTEM = """\
You judge whether this shopper utterance discards ALL committed typed constraints.
Return JSON only: {"full": true} or {"full": false}

full is true only when this turn names a new product type that is far from the prior category, or an explicit full start-over with a distant product type (sandals → backpack).
full is false when this turn has no category, only changes attributes (material, color, …), only adds alternatives, or the new category is close to the old one (same family after folding: running shoes ↔ formal shoes; sandals ↔ women sandals).
"ignore my earlier preference" and "what I need is: polyester" are not a full reset.
Do not invent constraints. Do not mention ASINs.

Examples:
- Prior: sandals + leather. Message: ignore my earlier preference. What I need is: polyester. → {"full": false}
- Prior: sandals. Message: Forget sandals. I want a backpack now. → {"full": true}
- Prior: running shoes. Message: I want formal shoes instead. → {"full": false}
"""

OVERRIDE_L2_SYSTEM = """\
You judge whether this utterance replaces some committed preferences.
Return JSON only: {"override": true} or {"override": false}

override is true only when they clearly overturn or replace a committed attribute, or swap to a close-family category (navy instead of pink; forget leather, I want polyester; formal shoes instead of running shoes).
override is false when they only add or supplement preferences ("also black and blue"), keep the old fields, answer a question, hedge, or quote catalog copy that happens to say instead/forget.
Stock phrases such as "ignore my earlier preference" are not enough unless they also replace a named attribute.
This is not a full reset (that was already judged false). Do not invent constraints. Do not mention ASINs.
"""

OVERRIDE_SYSTEM = OVERRIDE_L1_SYSTEM


@dataclass(frozen=True)
class OverrideDecision:
    """0 = accumulate, 1 = full reset, 2 = replace fields present in this turn's delta."""

    level: int = 0

    @property
    def overridden(self) -> bool:
        return self.level in {1, 2}


def as_override_decision(raw: object) -> OverrideDecision:
    """Accept OverrideDecision or a bool mock (True → L1, False → accumulate)."""

    if isinstance(raw, OverrideDecision):
        return raw
    if raw is True:
        return OverrideDecision(1)
    return OverrideDecision(0)

ROUTE_SYSTEM = """\
You choose buying vs browsing for retrieval after constraints were accumulated.
Return a JSON object with exactly one key: intention, whose value is "buying" or "browsing".

buying: the shopper has an actionable purchase goal (a specific type and/or locked requirements), even if it took several turns to say. A much smaller candidate pool than before also supports buying.
browsing: the goal is still vague (coarse category, exploring, few or no locked needs) or the candidate pool is still very large.
This is not an evaluator scenario label. Do not mention products or ASINs.
"""


class IntentRouterClient:
    """One-process Ollama chat client for routing only."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.last_error: str | None = None
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0

    @classmethod
    def from_env(cls) -> IntentRouterClient:
        return cls(host=nlu_host(), model=nlu_model(), timeout=nlu_timeout())

    def complete(self, system: str, user_content: str) -> dict | None:
        self.last_error = None
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "format": "json",
            "think": False,
            "options": {
                "temperature": 0.0,
                "num_predict": NUM_PREDICT,
                "num_ctx": NUM_CTX,
            },
        }
        request = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except TimeoutError:
            self.last_error = f"timeout after {self.timeout:g}s"
            return None
        except (urllib.error.URLError, OSError) as exc:
            self.last_error = f"connection failed: {exc}"
            return None
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            self.last_error = "Ollama envelope was not JSON"
            return None
        if isinstance(envelope, dict) and envelope.get("error"):
            self.last_error = str(envelope.get("error"))
            return None
        if isinstance(envelope, dict):
            prompt_tokens = envelope.get("prompt_eval_count")
            completion_tokens = envelope.get("eval_count")
            if isinstance(prompt_tokens, int) and prompt_tokens >= 0:
                self.last_prompt_tokens = prompt_tokens
            if isinstance(completion_tokens, int) and completion_tokens >= 0:
                self.last_completion_tokens = completion_tokens
        content = _message_text(envelope)
        parsed = _loads_json_object(content)
        if parsed is not None:
            return parsed
        snippet = content[:180].replace("\n", " ")
        self.last_error = (
            f"empty model content" if not content else f"content was not JSON: {snippet!r}"
        )
        return None


_client: IntentRouterClient | None = None


def warmup_intent_router() -> IntentRouterClient:
    global _client
    if _client is None:
        _client = IntentRouterClient.from_env()
    return _client


def get_intent_router_client() -> IntentRouterClient:
    return warmup_intent_router()


def _credit(state: SessionState, client: IntentRouterClient) -> None:
    state.router_prompt_tokens += client.last_prompt_tokens
    state.router_completion_tokens += client.last_completion_tokens


def has_committed_intent(state: SessionState) -> bool:
    """True when session memory already holds a committed shopping need."""

    if (state.category or "").strip():
        return True
    if state.active_constraints or state.legacy_hints or state.typed_constraints:
        return True
    return False


def categories_distant(prior: str | None, incoming: str | None) -> bool:
    """True when folded category tokens share nothing (sandal vs backpack)."""

    prior_fold = fold_category(prior)
    incoming_fold = fold_category(incoming)
    if not prior_fold or not incoming_fold:
        return False
    if prior_fold == incoming_fold:
        return False
    if set(prior_fold.split()) & set(incoming_fold.split()):
        return False
    return True


def should_keep_l1(state: SessionState) -> bool:
    """Keep L1 only when this turn changes category and it is far from the prior."""

    if not delta_has_category(state.turn_delta):
        return False
    return categories_distant(state.category, incoming_category(state.turn_delta))


def classify_override(state: SessionState) -> OverrideDecision:
    """Return L1 / L2 / accumulate. Skips both LLMs when nothing is committed."""

    if not has_committed_intent(state):
        return OverrideDecision(0)
    client = get_intent_router_client()
    user = _override_user_prompt(state)
    full = _bool_from_client(state, client, OVERRIDE_L1_SYSTEM, user, "full")
    if full is True and should_keep_l1(state):
        return OverrideDecision(1)
    partial = _bool_from_client(state, client, OVERRIDE_L2_SYSTEM, user, "override")
    if partial is True:
        return OverrideDecision(2)
    return OverrideDecision(0)


def _bool_from_client(
    state: SessionState,
    client: IntentRouterClient,
    system: str,
    user: str,
    key: str,
) -> bool | None:
    """Parse a single-key bool JSON. None after three illegal replies."""

    for _ in range(ATTEMPTS):
        payload = client.complete(system, user)
        _credit(state, client)
        parsed = _parse_bool_key(payload, key)
        if parsed is not None:
            return parsed
    return None


def _parse_bool_key(payload: dict | None, key: str) -> bool | None:
    if not isinstance(payload, dict) or set(payload.keys()) != {key}:
        return None
    raw = payload[key]
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.strip().casefold() in {"true", "false"}:
        return raw.strip().casefold() == "true"
    return None


def classify_route(
    state: SessionState,
    *,
    pool_before: int | None,
    pool_after: int | None,
    ratio: float | None,
) -> str:
    """Return buying or browsing. Defaults to browsing after failed extracts."""

    client = get_intent_router_client()
    user = _route_user_prompt(state, pool_before, pool_after, ratio)
    for _ in range(ATTEMPTS):
        payload = client.complete(ROUTE_SYSTEM, user)
        _credit(state, client)
        if payload is None:
            continue
        value = str(payload.get("intention") or "").strip().lower()
        if value in {"buying", "browsing"}:
            return value
    return "browsing"


def _delta_summary(state: SessionState) -> str:
    delta = state.turn_delta
    if delta is None or delta.empty:
        return "(empty)"
    constraints = ", ".join(delta.constraints) if delta.constraints else "(none)"
    return (
        f"category={delta.category or '(none)'}; "
        f"hint={delta.provisional_hint or '(none)'}; "
        f"constraints={constraints}"
    )


def _this_turn_attributes(state: SessionState) -> str:
    delta = state.turn_delta
    if delta is None or delta.empty:
        return "(none)"
    names: list[str] = []
    seen: set[str] = set()
    for slot in delta.slots:
        name = str(getattr(slot, "attribute", "") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    if delta.category and "category" not in seen:
        names.append("category")
    if delta.constraints and not any(name != "category" for name in names):
        names.extend(delta.constraints)
    return ", ".join(names) if names else "(none)"


def _committed_inventory(state: SessionState) -> str:
    groups: dict[str, list[str]] = {}
    for slot in state.typed_constraints:
        name = str(getattr(slot, "attribute", "") or "").strip()
        surface = str(getattr(slot, "surface", "") or "").strip()
        if not name:
            continue
        groups.setdefault(name, [])
        if surface and surface not in groups[name]:
            groups[name].append(surface)
    if (state.category or "").strip() and "category" not in groups:
        groups["category"] = [state.category.strip()]
    if not groups and state.active_constraints:
        return "- strings: " + "; ".join(state.active_constraints)
    if not groups:
        leftover = "; ".join(state.legacy_hints) if state.legacy_hints else "(none)"
        return f"- leftover: {leftover}"
    return "\n".join(f"- {name}: {', '.join(values)}" for name, values in groups.items())


def _override_user_prompt(state: SessionState) -> str:
    locked = "; ".join(state.active_constraints) if state.active_constraints else "(none)"
    history = " | ".join(state.message_history[-4:]) if state.message_history else "(none)"
    delta = state.turn_delta
    turn_category = "(none)" if delta is None else (delta.category or "(none)")
    return (
        f"Committed inventory:\n{_committed_inventory(state)}\n"
        f"Prior category: {state.category or '(none)'}\n"
        f"This turn category: {turn_category}\n"
        f"This turn delta fields: {_this_turn_attributes(state)}\n"
        f"Locked constraints: {locked}\n"
        f"Leftover hints: {'; '.join(state.legacy_hints) or '(none)'}\n"
        f"Gate open: {state.gate_open}\n"
        f"Recent history: {history}\n"
        f"This turn delta: {_delta_summary(state)}\n"
        f"User message: {state.latest_message}"
    )


def _route_user_prompt(
    state: SessionState,
    pool_before: int | None,
    pool_after: int | None,
    ratio: float | None,
) -> str:
    locked = "; ".join(state.active_constraints) if state.active_constraints else "(none)"
    history = " | ".join(state.message_history[-4:]) if state.message_history else "(none)"
    ratio_text = "null" if ratio is None else f"{ratio:.4g}"
    before_text = "null" if pool_before is None else str(pool_before)
    after_text = "null" if pool_after is None else str(pool_after)
    return (
        f"Current category: {state.category or '(none)'}\n"
        f"Locked constraints: {locked}\n"
        f"Recent history: {history}\n"
        f"User message: {state.latest_message}\n"
        f"Candidate pool before this turn's delta: {before_text}\n"
        f"Candidate pool after this turn's delta: {after_text}\n"
        f"Ratio after/before: {ratio_text}"
    )


def _message_text(envelope: object) -> str:
    if not isinstance(envelope, dict):
        return ""
    message_obj = envelope.get("message")
    if not isinstance(message_obj, dict):
        return ""
    content = str(message_obj.get("content") or "").strip()
    thinking = str(message_obj.get("thinking") or "").strip()
    blob = content or thinking
    return _THINK_BLOCK_RE.sub("", blob).strip()


def _loads_json_object(content: str) -> dict | None:
    text = _THINK_BLOCK_RE.sub("", content.strip())
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None
