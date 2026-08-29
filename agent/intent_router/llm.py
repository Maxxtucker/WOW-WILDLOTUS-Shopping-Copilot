"""Purpose: independent Ollama JSON client for intention routing.

Input: host/model/timeout from the same env as observation NLU.
Output: override bool, or buying/browsing label. None on transport/parse failure.
Role: separate process-wide client from observation.extract. No regex fallback.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from ..understand.observation.llm_nlu import (
    DEFAULT_HOST,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    nlu_host,
    nlu_model,
    nlu_timeout,
)

if TYPE_CHECKING:
    from ..understand.state.session import SessionState

ATTEMPTS = 3
NUM_PREDICT = 256
NUM_CTX = 8192
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

OVERRIDE_SYSTEM = """\
You decide whether this customer message replaces an earlier shopping preference.
Return a JSON object with exactly one key: override (boolean).

override is true only when the shopper throws out a previous need and states a new one.
override is false for: adding constraints, answering a clarification, exploring, empty or no-preference replies, or product copy that happens to contain instead/forget.
Do not invent constraints. Do not mention products or ASINs.
"""

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


def classify_override(state: SessionState) -> bool:
    """True when the model says this turn replaces an earlier preference."""

    client = get_intent_router_client()
    user = _override_user_prompt(state)
    for _ in range(ATTEMPTS):
        payload = client.complete(OVERRIDE_SYSTEM, user)
        _credit(state, client)
        if payload is None:
            continue
        value = payload.get("override")
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            return value.strip().lower() == "true"
    return False


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


def _override_user_prompt(state: SessionState) -> str:
    locked = "; ".join(state.active_constraints) if state.active_constraints else "(none)"
    history = " | ".join(state.message_history[-4:]) if state.message_history else "(none)"
    return (
        f"Current category: {state.category or '(none)'}\n"
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
