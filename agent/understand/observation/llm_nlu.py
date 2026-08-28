"""Purpose: Ollama JSON client for natural-language observation.

Input: host/model/timeout from env plus one user message and compact session context.
Output: ObservationExtract, or None on timeout/parse/network failure.
Role: HTTP only. Agent nlu mode constructs the client once. Does not write SessionState.
"""

from __future__ import annotations

import copy
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from ...domain import MATERIALS
from ..mode import MODE_NLU, current_understand_mode
from .schema import ObservationExtract, parse_observation_payload
from .slots import (
    APPAREL_LETTERS,
    CLOSED_COLORS,
    MAX_REPAIR_ROUNDS,
    SIZE_KINDS,
    SIZE_SYSTEMS,
    SIZE_UNITS,
    GroundingFailures,
    collect_failures,
    merge_repair_payload,
)

if TYPE_CHECKING:
    from ..state.session import SessionState

DEFAULT_MODEL = "qwen3.5:4b"
DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT = 30.0
NUM_PREDICT = 4096
NUM_CTX = 8192
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _system_prompt() -> str:
    colors = ", ".join(CLOSED_COLORS)
    materials = ", ".join(MATERIALS)
    systems = ", ".join(SIZE_SYSTEMS)
    kinds = ", ".join(SIZE_KINDS)
    letters = ", ".join(APPAREL_LETTERS)
    units = ", ".join(SIZE_UNITS)
    return f"""\
You extract shopping intent from one customer message.
Return a JSON object with exactly these keys:
category, provisional_hint, constraints, override, override_value, track, empty.

Attribute names (use these strings only):
category, material, color, size, style, brand, budget, feature, use_case, other.

category is a top-level copied span of the product type, not a constraint object.

constraints is a list of objects:
{{"attribute": "<name>", "surface": "<span from the message>", "surfaces": ["<optional alternative spans>"], "canonical": ["<mapped values>"] or null, "amount": <number or null>, "op": "lte"|"gte"|"eq"|null, "system": "<us|uk|eu or null>", "kind": "<shoe|apparel|dimension or null>", "unit": "<in|mm or null>", "length": <number or null>, "width": <number or null>, "height": <number or null>}}

Value types:
- color: canonical MUST be a JSON array of buckets from: {colors}. You choose the nearest bucket (for example navy → blue). grey and gray are the same bucket. Alternatives (blue or orange or pink) are ONE constraint with canonical: ["blue", "orange", "pink"]. Do not emit three color objects. surface is the shopper phrase, copied from the message. Optional surfaces lists each alternative span.
- material: canonical MUST be a JSON array of buckets from: {materials}. Same OR rule as color (leather or canvas → one object, canonical: ["leather", "canvas"]).
- budget: keep a number in amount. op is lte for under/max, gte for over/min, else eq. surface is a copied span or the digits that appear in the message. canonical is null.
- size: copy surface from the message. Set kind to one of: {kinds}. Code does not infer shoe vs apparel from product words.
  shoe: footwear (shoes, boots, sandals). system is one of: {systems} when named. amount is the number. canonical, unit, length, width, height are null. EUR maps to eu. Do not guess US/UK/EU.
  apparel: clothes and pants. Letter sizes: canonical MUST be a one-item array from: {letters}. You choose the bucket (extra small → xs, 2XL → xxl). Numeric clothing (US 4, waist 32) uses amount and optional system; that is not a shoe size.
  dimension: object length/width/height (3 x 3 inches, 21 cm). unit MUST be one of: {units}. You choose the bucket (cm → mm, inch → in). Copy the original numbers from the message into length, width, height. Do not write converted millimetres. system is null.
  If more than one shoe/clothing scale is named, system is null and surface keeps the full phrase. If the product type is unclear, kind is null. Do not treat a dress US size as a shoe size, or a letter as a box size.
- brand, style, use_case, feature, other: free strings. Copy a message span into surface. Alternatives (Nike or Adidas) are ONE constraint with canonical as a JSON array of the alternative strings. Optional surfaces lists each span. kind, system, unit, length, width, height are null.

Rules:
- surface MUST appear in the user message. Do not invent words. Each surfaces[] entry MUST also appear in the message.
- canonical is a JSON array for color, material, style, brand, feature, use_case, and other. Size letter canonical is a one-item array. Budget canonical is null.
- canonical may differ from surface for color, material, and apparel letter mapping. Do not span-check canonical.
- Alternatives use one object and a canonical array. Do not emit one object per alternative for the same attribute.
- system is us, uk, or eu when that label appears near the size number. Do not span-check system.
- kind is shoe, apparel, or dimension. Do not span-check kind.
- unit is in or mm. cm maps to mm. Do not span-check unit or converted millimetre amounts.
- empty: true for non-answers (no preference, use your judgment, not quite right).
- override: true only if the shopper replaces an earlier preference.
- track: "buying" if they locked a hard need; "browsing" if exploring or vague.
- Do not mention products or ASINs.
"""


_SYSTEM_PROMPT = _system_prompt()


def nlu_enabled() -> bool:
    """True when the process understand mode is nlu."""

    return current_understand_mode() == MODE_NLU


def nlu_model() -> str:
    return os.environ.get("AGENT_NLU_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def nlu_host() -> str:
    return os.environ.get("AGENT_NLU_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST


def nlu_timeout() -> float:
    raw = os.environ.get("AGENT_NLU_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        return max(0.5, float(raw))
    except ValueError:
        return DEFAULT_TIMEOUT


def nlu_env_file() -> Path:
    """Persistent local NLU settings. Not loaded until ``load_nlu_env`` is called."""

    return Path(__file__).resolve().parents[3] / "scripts" / "nlu.env"


def load_nlu_env(path: Path | None = None, *, overwrite: bool = False) -> dict[str, str]:
    """Copy KEY=VALUE lines from ``scripts/nlu.env`` into ``os.environ``.

    Importing this module does not load the file. Agent nlu startup and
    the NLU console call this explicitly.
    """

    source = path or nlu_env_file()
    loaded: dict[str, str] = {}
    if not source.is_file():
        return loaded
    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if not key:
            continue
        if key in os.environ and os.environ[key] != "" and not overwrite:
            loaded[key] = os.environ[key]
            continue
        os.environ[key] = value
        loaded[key] = value
    return loaded


class OllamaNluClient:
    """One-process Ollama chat client. Construct once; call extract per turn."""

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

    @classmethod
    def from_env(cls) -> OllamaNluClient:
        return cls(host=nlu_host(), model=nlu_model(), timeout=nlu_timeout())

    def inspect(
        self,
        message: str,
        *,
        category: str | None = None,
        constraints: tuple[str, ...] = (),
        last_ask: str | None = None,
    ) -> tuple[dict | None, ObservationExtract | None]:
        """Return merged model JSON plus the span-grounded extract. Either may be None."""

        payload = self._complete(
            _user_prompt(message, category, constraints, last_ask)
        )
        if payload is None:
            return None, None
        working = copy.deepcopy(payload)
        repair_rounds = 0
        while repair_rounds < MAX_REPAIR_ROUNDS:
            failures = collect_failures(working, message)
            if not failures:
                break
            repair_rounds += 1
            repair = self._complete(_repair_prompt(message, failures))
            if repair is None:
                break
            working = merge_repair_payload(working, repair, failures)
        extract = parse_observation_payload(working, message)
        return working, replace(extract, repair_rounds=repair_rounds)

    def extract(
        self,
        message: str,
        *,
        category: str | None = None,
        constraints: tuple[str, ...] = (),
        last_ask: str | None = None,
    ) -> ObservationExtract | None:
        _payload, parsed = self.inspect(
            message,
            category=category,
            constraints=constraints,
            last_ask=last_ask,
        )
        return parsed

    def _chat(
        self,
        message: str,
        category: str | None,
        constraints: tuple[str, ...],
        last_ask: str | None,
    ) -> dict | None:
        return self._complete(_user_prompt(message, category, constraints, last_ask))

    def _complete(self, user_content: str, *, num_predict: int | None = None) -> dict | None:
        self.last_error = None
        predict = NUM_PREDICT if num_predict is None else num_predict
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "format": "json",
            "think": False,
            "options": {
                "temperature": 0.0,
                "num_predict": predict,
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
        content = _message_text(envelope)
        parsed = _loads_json_object(content)
        if parsed is not None:
            return parsed
        done = envelope.get("done_reason") if isinstance(envelope, dict) else None
        if done == "length" and predict < NUM_PREDICT * 2:
            return self._complete(user_content, num_predict=predict * 2)
        snippet = content[:180].replace("\n", " ")
        if not content:
            self.last_error = f"empty model content (done_reason={done!r})"
        else:
            self.last_error = (
                f"content was not a JSON object (done_reason={done!r}): {snippet!r}"
            )
        return None


def _repair_prompt(message: str, failures: GroundingFailures) -> str:
    failed_names: list[str] = []
    if failures.category:
        failed_names.append("category")
    if failures.provisional_hint:
        failed_names.append("provisional_hint")
    if failures.override_value:
        failed_names.append("override_value")
    if failures.constraints:
        failed_names.append("constraints")
    failed_json = json.dumps(failures.constraints, ensure_ascii=False, default=str)
    return (
        "The previous JSON failed span checks. Return JSON with ONLY the failed keys.\n"
        "For constraints, return a list of slot objects. surface MUST appear in the user message.\n"
        "For color and material, canonical MUST be one of the closed lists in the system prompt; you choose the bucket.\n"
        f"Failed fields: {', '.join(failed_names) or '(none)'}\n"
        f"Failed constraint items: {failed_json}\n"
        f"User message: {message}"
    )


def _user_prompt(
    message: str,
    category: str | None,
    constraints: tuple[str, ...],
    last_ask: str | None,
) -> str:
    locked = "; ".join(constraints) if constraints else "(none)"
    return (
        f"Current category: {category or '(none)'}\n"
        f"Locked constraints: {locked}\n"
        f"Last asked attribute: {last_ask or '(none)'}\n"
        f"User message: {message}"
    )


def _message_text(envelope: object) -> str:
    """Visible model text, without think-blocks. Content is preferred over thinking."""

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


_client: OllamaNluClient | None = None


def warmup_nlu() -> OllamaNluClient | None:
    """Create the process-wide client when understand mode is nlu."""

    global _client
    if current_understand_mode() != MODE_NLU:
        _client = None
        return None
    if _client is None:
        _client = OllamaNluClient.from_env()
    return _client


def get_nlu_client() -> OllamaNluClient | None:
    return warmup_nlu()


def extract_with_llm(state: SessionState, message: str) -> ObservationExtract | None:
    client = get_nlu_client()
    if client is None:
        return None
    return client.extract(
        message,
        category=state.category,
        constraints=tuple(state.active_constraints),
        last_ask=state.last_ask,
    )
