"""Scenario-based Buyer agent for local dialogue simulation."""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
from dataclasses import dataclass, field
from threading import RLock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ALLOWED_ATTRIBUTES = {
    "category",
    "material",
    "color",
    "size",
    "style",
    "brand",
    "budget",
    "feature",
    "use_case",
    "other",
}

MATERIALS = (
    "cotton",
    "polyester",
    "nylon",
    "leather",
    "wool",
    "spandex",
    "silk",
    "rayon",
    "fabric",
)

MODE_PROMPTS = {
    2: """You are Mode 2, a paraphrase-only Buyer in a shopping dialogue.
Rewrite the supplied deterministic Buyer message into natural language, but
preserve its exact structured meaning. Keep every supplied category and answer
value verbatim; do not add, remove, negate, or replace a preference. You may
freely rewrite the surrounding natural language, including the opening,
sentence structure, and phrases such as 'what matters is'. For a buying
initial message, mention the supplied category and first hard constraint. For
an informative answer, include every supplied structured answer value exactly.
Return only a JSON object: {\"message\": \"...\"}. Do not return markdown or
extra keys.""",
    3: """You are Mode 3, a realistic Policy-Variant Buyer. Start from the
supplied deterministic answer and make a small, controlled variation: change
wording or answer order, answer only one of two available preferences, or add a
short clarification/hesitation. Keep exact product attribute values whenever
an answer is given, do not invent product IDs, and do not turn a normal answer
into an unrelated request. The result is a user message, not an assistant
response. Return only JSON with a string field named 'message' and optionally
boolean 'boundary_used'.""",
    4: """You are Mode 4, a difficult but plausible Buyer used for robustness
testing. The generated message MUST clearly exercise one of these behaviours:
missing, vague, misleading, no_preference, or conflicting. Do not merely make
the deterministic answer friendlier or add a weak hesitation such as 'I guess'.
Use the supplied difficulty_hint when present:

- missing: explicitly say you have not decided or omit the requested detail;
- vague: give only a broad qualitative answer without a precise value;
- misleading: state a plausible preference that points away from the known
  structured value;
- no_preference: explicitly say the attribute does not matter or ask the agent
  to choose;
- conflicting: state two incompatible requirements or reverse one preference.

Keep the message grounded in this shopping scenario, never reveal hidden labels
or product IDs, and do not write an assistant recommendation. Return only JSON
with a string field named 'message', optionally boolean 'boundary_used', and
optionally 'difficulty_type' set to one of the five names above.""",
}


def _canonical(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).casefold()).strip(" -;,.\t\n")


def _contains(value: str, expected: str) -> bool:
    return str(expected).casefold() in str(value).casefold()


def _flatten_constraints(sample: dict) -> list[str]:
    card = sample.get("intent_card") or {}
    values = [
        str(value)
        for value in [
            *(card.get("hard_constraints") or []),
            *(card.get("soft_preferences") or []),
        ]
    ]
    return list(dict.fromkeys(values))


def _classify_constraint(value: str) -> str:
    lowered = value.lower()
    if "budget" in lowered or re.search(r"(?:\$|<=|under)\s*\d", lowered):
        return "budget"
    if any(material in lowered for material in MATERIALS):
        return "material"
    if any(word in lowered for word in ("color", "black", "white", "blue", "red", "pink", "green")):
        return "color"
    if any(word in lowered for word in ("size", "sizing", "width", "wide", "narrow")):
        return "size"
    if any(word in lowered for word in ("department", "style", "fit", "sleeve", "neck")):
        return "style"
    if any(word in lowered for word in ("hiking", "running", "gym", "winter", "outdoor", "work")):
        return "use_case"
    return "feature"


def _mode1_initial_message(sample: dict, category: str, disclosed: set[str]) -> str:
    scenario = sample["scenario_type"]
    if scenario == "buying" and sample["intent_card"].get("hard_constraints"):
        constraint = str(sample["intent_card"]["hard_constraints"][0])
        disclosed.add(constraint)
        return f"I'm looking for {category}. A key requirement is: {constraint}."
    if scenario == "intent_override":
        old_value = str(sample["behavior"]["override"]["old_value"])
        return f"I'm looking for {category}. {old_value}"
    return f"I'm looking for {category}, but I'm still exploring."


def _mode1_customer_reply(
    sample: dict,
    ask_attribute: object,
    disclosed: set[str],
    boundary_used: bool,
) -> tuple[str, bool]:
    attribute = ask_attribute if isinstance(ask_attribute, str) else None
    if sample["scenario_type"] == "boundary" and not boundary_used and attribute:
        return f"I don't have a preference for {attribute}; please use your judgment.", True
    if not attribute:
        return "Those options are not quite right yet. Ask me about one specific attribute.", boundary_used
    if attribute not in ALLOWED_ATTRIBUTES:
        attribute = "other"
    constraints = _flatten_constraints(sample)
    matches = [
        value
        for value in constraints
        if value not in disclosed
        and (attribute == "other" or _classify_constraint(value) == attribute)
    ][:2]
    if not matches:
        return f"I don't have an additional preference for {attribute}.", boundary_used
    disclosed.update(matches)
    return "For that, what matters is: " + "; ".join(matches) + ".", boundary_used


def _parse_json_object(value: object) -> dict | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _load_dotenv() -> None:
    """Load the repository .env without overwriting real environment vars."""

    configured_path = os.environ.get("CONVERGE_DOTENV_PATH")
    dotenv_path = (
        configured_path
        if configured_path
        else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    )
    try:
        with open(dotenv_path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key.strip()):
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(key, value)


def _tls_context() -> ssl.SSLContext:
    """Build a verified TLS context, including the MSYS2 CA-bundle location."""

    configured = _env_first(
        "CONVERGE_CA_BUNDLE",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    )
    candidates = [configured] if configured else []
    executable_root = os.path.abspath(os.path.join(os.path.dirname(sys.executable), "..", ".."))
    candidates.extend(
        [
            os.path.join(executable_root, "usr", "ssl", "cert.pem"),
            os.path.join(executable_root, "usr", "ssl", "certs", "ca-bundle.crt"),
            r"C:\msys64\usr\ssl\cert.pem",
            r"C:\msys64\usr\ssl\certs\ca-bundle.crt",
        ]
    )
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return ssl.create_default_context(cafile=candidate)
    return ssl.create_default_context()


class OpenAICompatibleClient:
    """Small standard-library client for Qwen/DashScope or OpenAI endpoints."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 20.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_environment(cls) -> OpenAICompatibleClient | None:
        _load_dotenv()
        provider = (_env_first("CONVERGE_LLM_PROVIDER") or "").casefold()
        if provider in {"openai", "openai-compatible"}:
            api_key = _env_first("CONVERGE_LLM_API_KEY", "OPENAI_API_KEY")
            default_url = "https://api.openai.com/v1"
            default_model = "gpt-4o-mini"
        elif provider in {"deepseek", "deep-seek", "dp"}:
            api_key = _env_first(
                "CONVERGE_LLM_API_KEY",
                "DEEPSEEK_API_KEY",
                "DP_API_KEY",
            )
            default_url = "https://api.deepseek.com/v1"
            default_model = "deepseek-chat"
        elif provider in {"qwen", "dashscope", "ds"}:
            api_key = _env_first(
                "CONVERGE_LLM_API_KEY",
                "DASHSCOPE_API_KEY",
                "DS_API_KEY",
                "QWEN_API_KEY",
            )
            default_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            default_model = "qwen-plus"
        else:
            api_key = _env_first(
                "CONVERGE_LLM_API_KEY",
                "DASHSCOPE_API_KEY",
                "DS_API_KEY",
                "QWEN_API_KEY",
                "DEEPSEEK_API_KEY",
                "DP_API_KEY",
                "OPENAI_API_KEY",
            )
            if _env_first("DASHSCOPE_API_KEY", "DS_API_KEY", "QWEN_API_KEY"):
                default_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
                default_model = "qwen-plus"
            elif _env_first("DEEPSEEK_API_KEY", "DP_API_KEY"):
                default_url = "https://api.deepseek.com/v1"
                default_model = "deepseek-chat"
            else:
                default_url = "https://api.openai.com/v1"
                default_model = "gpt-4o-mini"
        if not api_key:
            return None
        base_url = _env_first(
            "CONVERGE_LLM_BASE_URL",
            "DASHSCOPE_BASE_URL",
            "OPENAI_BASE_URL",
        ) or default_url
        model = _env_first("CONVERGE_LLM_MODEL") or default_model
        raw_timeout = _env_first("CONVERGE_LLM_TIMEOUT") or "20"
        try:
            timeout = max(1.0, float(raw_timeout))
        except ValueError:
            timeout = 20.0
        return cls(api_key, base_url, model, timeout)

    def complete(self, system_prompt: str, payload: dict) -> tuple[dict | None, dict]:
        endpoint = self.base_url
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        request_payload = {
            "model": self.model,
            "temperature": 0.8,
            "max_tokens": 300,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
        }
        request = Request(
            endpoint,
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout, context=_tls_context()) as response:
                body = json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            return None, {}
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None, body.get("usage") if isinstance(body, dict) else {}
        return _parse_json_object(content), body.get("usage") or {}


@dataclass
class _BuyerSession:
    sample: dict
    category: str
    last_usage: dict = field(default_factory=dict)


class ScenarioUserAgent:
    """Generate Buyer messages while retaining the original helper contract.

    reset accepts the materialized evaluator sample and category. Then
    initial_message and customer_reply have the same arguments and return
    values as the original local-evaluator functions, with LLM shaping enabled
    for modes 2-4.
    """

    def __init__(
        self,
        mode: int | str | None = None,
        client: object | None = None,
    ) -> None:
        _load_dotenv()
        raw_mode = mode if mode is not None else os.environ.get("CONVERGE_USER_MODE", "1")
        try:
            self.mode = int(raw_mode)
        except (TypeError, ValueError) as exc:
            raise ValueError("CONVERGE_USER_MODE must be 1, 2, 3, or 4") from exc
        if self.mode not in {1, 2, 3, 4}:
            raise ValueError("mode must be 1, 2, 3, or 4")
        self.client = client if client is not None else (
            OpenAICompatibleClient.from_environment() if self.mode != 1 else None
        )
        self.sessions: dict[str, _BuyerSession] = {}
        self._lock = RLock()

    @property
    def llm_enabled(self) -> bool:
        return self.mode != 1 and self.client is not None

    def reset(self, session_id: str, sample: dict, category: str) -> None:
        if not session_id:
            raise ValueError("session_id must be non-empty")
        with self._lock:
            self.sessions[session_id] = _BuyerSession(
                sample=dict(sample),
                category=str(category),
            )

    def initial_message(
        self,
        sample_or_session_id: dict | str,
        category_or_disclosed: str | set[str],
        disclosed: set[str] | None = None,
    ) -> str:
        """Return the initial Buyer message.

        The preferred compatibility form is ``(sample, category, disclosed)``
        matching the original evaluator helper. For callers that want explicit
        per-session storage, ``reset(session_id, sample, category)`` followed
        by ``(session_id, disclosed)`` is also supported.
        """
        if isinstance(sample_or_session_id, str):
            if disclosed is not None or not isinstance(category_or_disclosed, set):
                raise TypeError("session form is initial_message(session_id, disclosed)")
            session = self._session(sample_or_session_id)
            target_disclosed = category_or_disclosed
        else:
            if disclosed is None or not isinstance(category_or_disclosed, str):
                raise TypeError("compatibility form is initial_message(sample, category, disclosed)")
            session = _BuyerSession(sample=dict(sample_or_session_id), category=category_or_disclosed)
            target_disclosed = disclosed
        before = set(target_disclosed)
        shadow = set(target_disclosed)
        base = _mode1_initial_message(session.sample, session.category, shadow)
        if self.mode == 1:
            target_disclosed.update(shadow)
            return base
        shaped = self._shape(
            session,
            "initial",
            base,
            None,
            shadow - before,
        )
        message = shaped.get("message") if shaped else None
        if not self._valid_message(message) or (
            self.mode == 2
            and not self._mode2_initial_is_safe(session, str(message))
        ):
            if self.mode == 4:
                return self._mode4_fallback(session, "initial", None)
            target_disclosed.update(shadow)
            return base
        if self.mode == 4 and not self._mode4_is_difficult(
            session, "initial", None, str(message), shaped
        ):
            return self._mode4_fallback(session, "initial", None)
        if self.mode == 3 and _canonical(str(message)) == _canonical(base):
            return self._mode3_fallback(session, "initial", None, [])
        self._record_exact_values_in_message(session.sample, str(message), target_disclosed)
        return str(message)

    def customer_reply(
        self,
        sample_or_session_id: dict | str,
        ask_attribute: object,
        disclosed: set[str],
        boundary_used: bool,
    ) -> tuple[str, bool]:
        if isinstance(sample_or_session_id, str):
            session = self._session(sample_or_session_id)
        else:
            session = _BuyerSession(sample=dict(sample_or_session_id), category="")
        before = set(disclosed)
        shadow = set(disclosed)
        base, base_boundary = _mode1_customer_reply(
            session.sample,
            ask_attribute,
            shadow,
            boundary_used,
        )
        if self.mode == 1:
            disclosed.update(shadow)
            return base, base_boundary
        semantic_values = list(shadow - before)
        shaped = self._shape(
            session,
            "reply",
            base,
            ask_attribute if isinstance(ask_attribute, str) else None,
            semantic_values,
            boundary_used=boundary_used,
        )
        message = shaped.get("message") if shaped else None
        if not self._valid_message(message):
            if self.mode == 4:
                return self._mode4_fallback(session, "reply", ask_attribute), base_boundary
            disclosed.update(shadow)
            return base, base_boundary
        message = str(message)
        if self.mode == 2 and not self._mode2_reply_is_safe(
            base,
            semantic_values,
            message,
        ):
            disclosed.update(shadow)
            return base, base_boundary
        if self.mode == 4 and not self._mode4_is_difficult(
            session, "reply", ask_attribute if isinstance(ask_attribute, str) else None,
            message, shaped,
        ):
            return self._mode4_fallback(
                session, "reply", ask_attribute if isinstance(ask_attribute, str) else None,
            ), base_boundary
        if self.mode == 3 and _canonical(message) == _canonical(base):
            return self._mode3_fallback(
                session,
                "reply",
                ask_attribute if isinstance(ask_attribute, str) else None,
                semantic_values,
            ), base_boundary
        self._record_exact_values_in_message(session.sample, message, disclosed)
        generated_boundary = bool(shaped.get("boundary_used")) if isinstance(shaped, dict) else False
        if not generated_boundary and re.search(
            r"\bno (?:a )?preference for\s+[a-z_]+",
            message,
            re.IGNORECASE,
        ):
            generated_boundary = True
        if session.sample.get("scenario_type") == "boundary":
            return message, boundary_used or generated_boundary
        return message, boundary_used

    def _session(self, session_id: str) -> _BuyerSession:
        with self._lock:
            try:
                return self.sessions[session_id]
            except KeyError as exc:
                raise RuntimeError(
                    "reset must be called before using the user agent"
                ) from exc

    def _shape(
        self,
        session: _BuyerSession,
        kind: str,
        base_message: str,
        ask_attribute: str | None,
        semantic_values: object,
        *,
        boundary_used: bool = False,
    ) -> dict | None:
        if not self.client or self.mode == 1:
            return None
        payload = {
            "mode": self.mode,
            "turn_kind": kind,
            "scenario_type": session.sample.get("scenario_type"),
            "category": session.category,
            "ask_attribute": ask_attribute,
            "deterministic_message": base_message,
            "structured_answer_values": (
                list(semantic_values)
                if isinstance(semantic_values, (list, tuple, set))
                else semantic_values
            ),
            "boundary_used": boundary_used,
            "profile": session.sample.get("user_profile") or {},
        }
        if self.mode == 4:
            payload["difficulty_hint"] = self._mode4_hint(
                session,
                kind,
                ask_attribute,
            )
        try:
            result = self.client.complete(MODE_PROMPTS[self.mode], payload)
        except Exception:
            return None
        if isinstance(result, tuple):
            shaped, usage = result
        else:
            shaped, usage = result, {}
        session.last_usage = usage if isinstance(usage, dict) else {}
        return _parse_json_object(shaped)

    @staticmethod
    def _mode4_hint(
        session: _BuyerSession,
        kind: str,
        ask_attribute: str | None,
    ) -> str:
        if kind == "initial":
            return "missing"
        if session.sample.get("scenario_type") == "boundary":
            return "no_preference"
        return {
            "material": "misleading",
            "color": "no_preference",
            "budget": "conflicting",
            "size": "missing",
            "feature": "vague",
            "use_case": "vague",
            "style": "conflicting",
        }.get(ask_attribute or "other", "vague")

    @classmethod
    def _mode4_is_difficult(
        cls,
        session: _BuyerSession,
        kind: str,
        ask_attribute: str | None,
        message: str,
        shaped: dict | None,
    ) -> bool:
        """Reject ordinary paraphrases so Mode 4 cannot silently become Mode 3."""

        text = message.casefold()
        declared = shaped.get("difficulty_type") if isinstance(shaped, dict) else None
        if declared is not None and declared not in {
            "missing", "vague", "misleading", "no_preference", "conflicting",
        }:
            return False
        signals = {
            "missing": (
                "not sure", "undecided", "haven't decided", "have not decided",
                "don't know", "do not know", "no idea", "not thought about",
            ),
            "vague": (
                "something", "somewhat", "kind of", "sort of", "reasonable",
                "decent", "good enough", "more or less", "in general", "roughly",
            ),
            "misleading": (
                "actually", "instead", "rather", "synthetic", "vegan", "plastic",
                "faux", "fake", "non-leather",
            ),
            "no_preference": (
                "no preference", "doesn't matter", "do not mind", "don't mind",
                "not picky", "up to you", "use your judgment", "you decide",
                "anything is fine", "either is fine", "i'm flexible", "im flexible",
            ),
            "conflicting": (
                " but ", "however", "although", "at the same time", "on the one hand",
                "both", "can't have", "cannot have", "as well as",
            ),
        }
        if declared in signals and any(signal in text for signal in signals[declared]):
            return True
        return any(any(signal in text for signal in group) for group in signals.values())

    @staticmethod
    def _mode4_fallback(
        session: _BuyerSession,
        kind: str,
        ask_attribute: str | None,
    ) -> str:
        """Keep the promised Mode 4 boundary even if the LLM is unavailable."""

        if kind == "initial":
            return (
                f"I'm looking for {session.category}, but I haven't decided exactly "
                "what details I need yet."
            )
        if not ask_attribute:
            return "I'm not sure how to answer that; I haven't decided what matters yet."
        hint = ScenarioUserAgent._mode4_hint(session, kind, ask_attribute)
        if hint == "no_preference":
            return f"I don't have a firm preference for {ask_attribute}; please choose what seems best."
        if hint == "conflicting":
            return (
                f"For {ask_attribute}, I want the best quality, but I also need to keep "
                "the cost very low."
            )
        if hint == "misleading":
            return (
                f"I mentioned one thing earlier, but actually I'd rather have a "
                f"synthetic option for {ask_attribute}."
            )
        return f"I'm not sure about {ask_attribute}; something reasonable is probably fine."

    @staticmethod
    def _mode3_fallback(
        session: _BuyerSession,
        kind: str,
        ask_attribute: str | None,
        semantic_values: list[str],
    ) -> str:
        """Guarantee a small Mode 3 variation when the LLM echoes the base."""

        if kind == "initial":
            constraints = session.sample.get("intent_card", {}).get("hard_constraints") or []
            if constraints:
                return f"I'm shopping for {session.category}; the main requirement is {constraints[0]}."
            return f"I'm shopping for {session.category}, and I'm still exploring the details."
        if semantic_values:
            return "My main priority here is: " + "; ".join(semantic_values) + "."
        if not ask_attribute:
            return "I'm still unsure; could you ask me about one specific attribute?"
        if session.sample.get("scenario_type") == "boundary":
            return f"I'm flexible about {ask_attribute}; please use your judgment."
        return f"I don't have any other strong preference for {ask_attribute}."

    @staticmethod
    def _valid_message(message: object) -> bool:
        return isinstance(message, str) and 0 < len(message.strip()) <= 2000

    @staticmethod
    def _mode2_initial_is_safe(session: _BuyerSession, message: str) -> bool:
        scenario = session.sample.get("scenario_type")
        if scenario == "buying":
            constraints = session.sample.get("intent_card", {}).get("hard_constraints") or []
            soft_preferences = session.sample.get("intent_card", {}).get("soft_preferences") or []
            return (
                bool(constraints)
                and _contains(message, constraints[0])
                and _contains(message, session.category)
                and not any(
                    _contains(message, value)
                    for value in soft_preferences
                    if str(value).casefold() != str(constraints[0]).casefold()
                )
            )
        if scenario == "intent_override":
            old = session.sample.get("behavior", {}).get("override", {}).get("old_value", "")
            return (
                _contains(message, session.category)
                and _contains(message, old)
            )
        return _contains(message, session.category)

    @staticmethod
    def _mode2_reply_is_safe(
        base: str,
        semantic_values: list[str],
        message: str,
    ) -> bool:
        lowered = base.casefold()
        if "what matters is:" in lowered:
            return all(_contains(message, value) for value in semantic_values)
        if "no additional preference for" in lowered:
            return "additional preference" in message.casefold()
        if "no preference for" in lowered:
            return "preference" in message.casefold()
        if "not quite right" in lowered:
            return "not quite right" in message.casefold() or "specific attribute" in message.casefold()
        return True

    @staticmethod
    def _record_exact_values_in_message(
        sample: dict,
        message: str,
        disclosed: set[str],
    ) -> None:
        for value in _flatten_constraints(sample):
            if _contains(message, value):
                disclosed.add(value)


def initial_message(sample: dict, category: str, disclosed: set[str]) -> str:
    """Backward-compatible Mode 1 helper from evaluator.local_evaluator."""

    return _mode1_initial_message(sample, category, disclosed)


def customer_reply(
    sample: dict,
    ask_attribute: object,
    disclosed: set[str],
    boundary_used: bool,
) -> tuple[str, bool]:
    """Backward-compatible Mode 1 helper from evaluator.local_evaluator."""

    return _mode1_customer_reply(sample, ask_attribute, disclosed, boundary_used)


__all__ = [
    "OpenAICompatibleClient",
    "ScenarioUserAgent",
    "customer_reply",
    "initial_message",
]
