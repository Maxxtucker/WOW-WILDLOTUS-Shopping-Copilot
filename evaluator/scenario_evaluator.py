"""Scenario evaluator Buyer for local dialogue simulation.

The public methods intentionally mirror the original evaluator helpers.  The
module is standalone: it generates Buyer messages, while the shopping agent
continues to own recommendations and ``ask_attribute`` decisions.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
from dataclasses import dataclass, field
from itertools import product
from threading import RLock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ALLOWED_ATTRIBUTES = {
    "category", "material", "color", "size", "style", "brand", "budget",
    "feature", "use_case", "other",
}

MATERIALS = (
    "cotton", "polyester", "nylon", "leather", "wool", "spandex", "silk",
    "rayon", "fabric",
)

# Each mode has a separate prompt.  The validators below remain authoritative;
# a model's claim that it preserved semantics is never accepted by itself.
MODE_PROMPTS = {
    2: """You are Mode 2, a controlled paraphrase Buyer.
Rewrite only the natural-language parts outside protected_keywords. Every
protected keyword must appear exactly as supplied, with the same spelling and
word order. Keep the same positive/negative intent and do not add another
preference, recommendation, product ID, or new requirement. Do not copy hidden
metadata into the message. Return only JSON: {\"message\": \"...\"}.""",
    3: """You are Mode 3, a natural Buyer who preserves the supplied structured
meaning. Rewrite the whole sentence naturally. Use a semantically equivalent
expression for important keywords when a synonym hint is supplied; do not
needlessly copy the canonical keyword. Preserve the same category, preference,
and positive/negative intent. Do not invent requirements, products, or
recommendations. Return only JSON: {\"message\": \"...\"}.""",
    4: """You are Mode 4, a Buyer whose English is not very good, but whose
shopping intent must remain the same. Rewrite the whole message while keeping
the same structured meaning. Simulate one or more of: a small grammar error,
a spelling error, unnatural word order, a missing article, or a long
circumlocution that explains a keyword instead of saying the keyword directly.
Do not reverse, remove, negate, or add a preference. Do not create conflict,
misleading information, or a recommendation. Keep the message grounded in the
shopping scenario. Return only JSON: {\"message\": \"...\"}.""",
}


# This small transparent vocabulary lets the local validator recognize common
# paraphrases without a second model call.  Unknown values use token overlap.
_SEMANTIC_ALIASES = {
    "men shoes": ("men's footwear", "male footwear"),
    "watches watch bands": ("watch straps", "timepiece straps"),
    "sandals flats": ("flat sandals", "open-toe flat shoes"),
    "leather": (
        "genuine hide", "real animal skin", "animal skin", "skin from animal",
        "hide material",
    ),
    "material:alloy": (
        "mixed metal", "metal mixture", "several metals mixed together",
        "made from several metals", "is made from several metal mixed together",
    ),
    "alloy": (
        "mixed metal", "metal mixture", "several metals mixed together",
        "made from several metals", "is made from several metal mixed together",
    ),
    "rubber sole": (
        "sole made of rubber", "rubber on the bottom", "rubber bottom",
        "rubber underneath",
    ),
    "triple moon pentagram symbol": (
        "three moon phases and a five-pointed star symbol",
        "triple moon and five-point star design",
        "three moons with a five point sign",
    ),
    "color: black": ("black color", "in black", "black shade"),
    "fabric": ("textile", "cloth material", "woven material"),
}

_WORD_ALIASES = {
    "shoe": ("footwear",),
    "shoes": ("footwear",),
    "jewelry": ("jewellery",),
    "necklaces": ("necklace",),
    "necklace": ("neckwear",),
    "men": ("men's", "male"),
    "women": ("women's", "female"),
    "woman": ("women's",),
    "man": ("men's",),
    "watches": ("timepieces",),
    "watch": ("timepiece",),
    "bands": ("straps",),
    "band": ("strap",),
    "sandals": ("open-toe footwear",),
    "flats": ("flat shoes",),
    "clothing": ("apparel",),
    "clothes": ("apparel",),
    "bags": ("carryalls",),
    "bag": ("carryall",),
    "accessories": ("accessory items",),
}

_STOP_WORDS = {
    "a", "an", "and", "as", "at", "be", "for", "from", "i", "in", "is",
    "it", "material", "of", "on", "or", "the", "to", "with",
}
_WORD_RE = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)?", re.IGNORECASE)
_NEGATION_RE = re.compile(
    r"\b(?:not|no|never|without|don't|do not|doesn't|does not|didn't|"
    r"did not|can't|cannot|rather than|instead of|no longer)\b"
    r"[^.!?]{0,45}\b(?:leather|hide|alloy|metal|rubber|cotton|polyester|"
    r"nylon|wool|silk|black|footwear|shoes?)\b",
    re.IGNORECASE,
)


def _canonical(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).casefold()).strip(" -;,.\t\n")


def _contains(value: object, expected: object) -> bool:
    return str(expected).casefold() in str(value).casefold()


def _contains_exact(value: object, expected: object) -> bool:
    return str(expected) in str(value)


def _tokens(value: object) -> list[str]:
    return [token.casefold() for token in _WORD_RE.findall(str(value))]


def _core_tokens(value: object) -> list[str]:
    return [token for token in _tokens(value) if token not in _STOP_WORDS]


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
    """Build a verified TLS context, including common MSYS2 CA locations."""

    configured = _env_first(
        "CONVERGE_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    )
    candidates = [configured] if configured else []
    executable_root = os.path.abspath(os.path.join(os.path.dirname(sys.executable), "..", ".."))
    candidates.extend([
        os.path.join(executable_root, "usr", "ssl", "cert.pem"),
        os.path.join(executable_root, "usr", "ssl", "certs", "ca-bundle.crt"),
        r"C:\msys64\usr\ssl\cert.pem",
        r"C:\msys64\usr\ssl\certs\ca-bundle.crt",
    ])
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return ssl.create_default_context(cafile=candidate)
    return ssl.create_default_context()


class OpenAICompatibleClient:
    """Small standard-library client for DeepSeek, Qwen, or compatible APIs."""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 20.0) -> None:
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
            default_url, default_model = "https://api.openai.com/v1", "gpt-4o-mini"
        elif provider in {"deepseek", "deep-seek", "dp"}:
            api_key = _env_first("CONVERGE_LLM_API_KEY", "DEEPSEEK_API_KEY", "DP_API_KEY")
            default_url, default_model = "https://api.deepseek.com/v1", "deepseek-chat"
        elif provider in {"qwen", "dashscope", "ds"}:
            api_key = _env_first("CONVERGE_LLM_API_KEY", "DASHSCOPE_API_KEY", "DS_API_KEY", "QWEN_API_KEY")
            default_url, default_model = "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"
        else:
            api_key = _env_first(
                "CONVERGE_LLM_API_KEY", "DASHSCOPE_API_KEY", "DS_API_KEY", "QWEN_API_KEY",
                "DEEPSEEK_API_KEY", "DP_API_KEY", "OPENAI_API_KEY",
            )
            if _env_first("DASHSCOPE_API_KEY", "DS_API_KEY", "QWEN_API_KEY"):
                default_url, default_model = "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"
            elif _env_first("DEEPSEEK_API_KEY", "DP_API_KEY"):
                default_url, default_model = "https://api.deepseek.com/v1", "deepseek-chat"
            else:
                default_url, default_model = "https://api.openai.com/v1", "gpt-4o-mini"
        if not api_key:
            return None
        base_url = _env_first("CONVERGE_LLM_BASE_URL", "DASHSCOPE_BASE_URL", "OPENAI_BASE_URL") or default_url
        model = _env_first("CONVERGE_LLM_MODEL") or default_model
        try:
            timeout = max(1.0, float(_env_first("CONVERGE_LLM_TIMEOUT") or "20"))
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
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        request = Request(
            endpoint,
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
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


LOCAL_NLU_MODEL = "qwen3.5:4b"
LOCAL_NLU_HOST = "http://127.0.0.1:11434"


def parse_llm_mode(value: object = None) -> str:
    """Return ``remote`` or ``local``. Empty values use CONVERGE_LLM_BACKEND."""

    _load_dotenv()
    raw = value if value not in (None, "") else os.environ.get("CONVERGE_LLM_BACKEND", "remote")
    mode = str(raw).strip().casefold()
    if mode not in {"remote", "local"}:
        raise ValueError("llm_mode must be remote or local")
    return mode


def remote_llm_configured() -> bool:
    """True only when both remote URL and model env vars are set."""

    _load_dotenv()
    return bool(_env_first("CONVERGE_LLM_BASE_URL") and _env_first("CONVERGE_LLM_MODEL"))


def resolve_buyer_llm_backend(llm_mode: object = None) -> str:
    """Pick the Buyer LLM backend after applying the remote-env fallback."""

    if parse_llm_mode(llm_mode) == "local":
        return "local"
    return "remote" if remote_llm_configured() else "local"


def _ollama_message_text(envelope: object) -> str:
    if not isinstance(envelope, dict):
        return ""
    message = envelope.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    if isinstance(envelope.get("response"), str):
        return envelope["response"]
    return ""


class OllamaBuyerClient:
    """Ollama /api/chat client for Buyer Modes 2-4. Same model pin as NLU."""

    def __init__(self, host: str, model: str, timeout: float = 60.0) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._ready = False

    @classmethod
    def from_environment(cls) -> OllamaBuyerClient:
        from agent.understand.observation.llm_nlu import (
            load_nlu_env,
            nlu_host,
            nlu_model,
            nlu_timeout,
        )

        load_nlu_env()
        return cls(nlu_host(), nlu_model(), nlu_timeout())

    def complete(self, system_prompt: str, payload: dict) -> tuple[dict | None, dict]:
        if not self._ready:
            from agent.understand.observation.runtime import ensure_llm_runtime

            ensure_llm_runtime()
            self._ready = True
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0.8, "num_predict": 300},
        }
        request = Request(
            f"{self.host}/api/chat",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                envelope = json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            return None, {}
        if isinstance(envelope, dict) and envelope.get("error"):
            return None, {}
        return _parse_json_object(_ollama_message_text(envelope)), {}


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _canonical(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(str(value))
    return result


def _semantic_aliases(value: str) -> list[str]:
    normalized = _canonical(value)
    aliases = list(_SEMANTIC_ALIASES.get(normalized, ()))
    if normalized.startswith("material:"):
        material = normalized.split(":", 1)[1].strip()
        aliases.extend(_SEMANTIC_ALIASES.get(material, ()))
    tokens = _core_tokens(value)
    if len(tokens) <= 6:
        choices = [tuple([token, *_WORD_ALIASES.get(token, ())]) for token in tokens]
        for combination in product(*choices):
            aliases.append(" ".join(combination))
    else:
        for index, token in enumerate(tokens):
            for alias in _WORD_ALIASES.get(token, ()):
                replaced = list(tokens)
                replaced[index] = alias
                aliases.append(" ".join(replaced))
    return _dedupe([value, *aliases])


def _preferred_alias(value: str) -> str:
    aliases = _semantic_aliases(value)
    for alias in aliases[1:]:
        if _canonical(alias) != _canonical(value):
            return alias
    tokens = _core_tokens(value)
    if tokens:
        candidate = " ".join(_WORD_ALIASES.get(token, (token,))[0] for token in tokens)
        if candidate and _canonical(candidate) != _canonical(value):
            return candidate
    # For an unknown domain phrase there is no safe deterministic synonym.
    # Retain the canonical value rather than inventing a potentially different
    # meaning; normal LLM output can still supply a validated paraphrase.
    return str(value)


def _descriptor(value: str) -> str:
    normalized = _canonical(value)
    descriptors = {
        "leather": "comes from real animal skin",
        "material:alloy": "is made from several metal mixed together",
        "alloy": "is made from several metal mixed together",
        "rubber sole": "has rubber on the bottom part",
        "triple moon pentagram symbol": "shows three moon phases and a five point star sign",
        "color: black": "has the black color",
        "fabric": "is made from cloth textile material",
    }
    if normalized in descriptors:
        return descriptors[normalized]
    if normalized.startswith("material:"):
        material = normalized.split(":", 1)[1].strip()
        return f"is made from {material} material"
    return f"has the {value} detail that I mean"


def _semantic_evidence(value: str, message: str) -> bool:
    if _contains(message, value):
        return True
    aliases = _semantic_aliases(value)
    if any(_contains(message, alias) for alias in aliases[1:]):
        return True
    core = _core_tokens(value)
    if not core:
        return True
    message_tokens = set(_tokens(message))
    present = sum(token in message_tokens for token in core)
    return present >= max(1, (len(core) + 1) // 2)


def _contains_negative_change(message: str) -> bool:
    return bool(_NEGATION_RE.search(message))


def _unexpected_exact_values(sample: dict, expected: list[str], message: str) -> bool:
    expected_normalized = {_canonical(value) for value in expected}
    return any(
        _canonical(value) not in expected_normalized and _contains(message, value)
        for value in _flatten_constraints(sample)
    )


def _semantic_intent(kind: str, base: str, scenario_type: object) -> str:
    """Describe the non-value speech act that must survive a rewrite."""

    lowered = base.casefold()
    if kind == "initial":
        return "exploring" if str(scenario_type) in {"browsing", "boundary"} else "state_requirement"
    if "no additional preference" in lowered:
        return "no_additional_preference"
    if "no preference for" in lowered:
        return "no_preference"
    if "not quite right" in lowered:
        return "request_specific_question"
    if "what matters is" in lowered:
        return "state_requirement"
    return "preserve_message_intent"


def _intent_preserved(session: _BuyerSession, kind: str, base: str, message: str) -> bool:
    intent = _semantic_intent(kind, base, session.sample.get("scenario_type"))
    text = message.casefold()
    if intent == "exploring":
        return any(signal in text for signal in (
            "explor", "brows", "looking around", "checking", "still see",
            "not decided", "not sure", "compare", "options",
        ))
    if intent == "no_additional_preference":
        return bool(re.search(
            r"\b(?:no|not|don't|do not|doesn't|does not|haven't|have not)\b"
            r"[^.!?]{0,55}\b(?:additional|another|other|more|extra|specific|strong)\b"
            r"[^.!?]{0,35}\b(?:preference|requirement|need|detail)",
            text,
        ))
    if intent == "no_preference":
        return any(signal in text for signal in (
            "no preference", "don't mind", "do not mind", "doesn't matter",
            "does not matter", "not picky", "flexible", "up to you",
            "you decide", "your judgment", "decide for me",
        ))
    if intent == "request_specific_question":
        return (
            any(signal in text for signal in ("ask", "question", "tell you"))
            and any(signal in text for signal in ("specific", "one", "attribute", "detail"))
        )
    return True


def _protected_keywords(
    session: _BuyerSession,
    kind: str,
    ask_attribute: str | None,
    semantic_values: list[str],
) -> list[str]:
    if kind == "initial":
        result = [session.category]
        scenario = session.sample.get("scenario_type")
        if scenario == "buying":
            constraints = session.sample.get("intent_card", {}).get("hard_constraints") or []
            if constraints:
                result.append(str(constraints[0]))
        elif scenario == "intent_override":
            result.append(str(session.sample.get("behavior", {}).get("override", {}).get("old_value", "")))
        return _dedupe(result)
    # ``ask_attribute`` is protocol metadata used to select the answer; it is
    # not itself a user preference keyword.  The actual protected words are
    # the structured values that the original reply would disclose.
    return _dedupe(list(semantic_values))


def _semantic_targets(
    session: _BuyerSession,
    kind: str,
    semantic_values: list[str],
) -> list[dict]:
    values: list[str] = []
    if kind == "initial":
        values.append(session.category)
        scenario = session.sample.get("scenario_type")
        if scenario == "buying":
            constraints = session.sample.get("intent_card", {}).get("hard_constraints") or []
            if constraints:
                values.append(str(constraints[0]))
        elif scenario == "intent_override":
            values.append(str(session.sample.get("behavior", {}).get("override", {}).get("old_value", "")))
    else:
        values.extend(semantic_values)
    return [
        {
            "canonical_value": value,
            "synonym_hints": _semantic_aliases(value)[1:],
            "description_hint": _descriptor(value),
        }
        for value in _dedupe(values)
    ]


@dataclass
class _BuyerSession:
    sample: dict
    category: str
    last_usage: dict = field(default_factory=dict)


class ScenarioEvaluator:
    """Generate Buyer messages for four controlled scenario modes."""

    def __init__(
        self,
        mode: int | str | None = None,
        client: object | None = None,
        llm_mode: str | None = None,
    ) -> None:
        _load_dotenv()
        raw_mode = mode if mode is not None else os.environ.get("CONVERGE_USER_MODE", "1")
        try:
            self.mode = int(raw_mode)
        except (TypeError, ValueError) as exc:
            raise ValueError("CONVERGE_USER_MODE must be 1, 2, 3, or 4") from exc
        if self.mode not in {1, 2, 3, 4}:
            raise ValueError("mode must be 1, 2, 3, or 4")
        self.llm_mode = parse_llm_mode(llm_mode)
        self.llm_backend: str | None = None
        if self.mode == 1:
            self.client = None
        else:
            self.llm_backend = resolve_buyer_llm_backend(self.llm_mode)
            if client is not None:
                self.client = client
            elif self.llm_backend == "local":
                self.client = OllamaBuyerClient.from_environment()
            else:
                self.client = OpenAICompatibleClient.from_environment()
        self.sessions: dict[str, _BuyerSession] = {}
        self._lock = RLock()

    @property
    def llm_enabled(self) -> bool:
        return self.mode != 1 and self.client is not None

    def reset(self, session_id: str, sample: dict, category: str) -> None:
        if not session_id:
            raise ValueError("session_id must be non-empty")
        with self._lock:
            self.sessions[session_id] = _BuyerSession(dict(sample), str(category))

    def initial_message(
        self,
        sample_or_session_id: dict | str,
        category_or_disclosed: str | set[str],
        disclosed: set[str] | None = None,
    ) -> str:
        if isinstance(sample_or_session_id, str):
            if disclosed is not None or not isinstance(category_or_disclosed, set):
                raise TypeError("session form is initial_message(session_id, disclosed)")
            session = self._session(sample_or_session_id)
            target_disclosed = category_or_disclosed
        else:
            if disclosed is None or not isinstance(category_or_disclosed, str):
                raise TypeError("compatibility form is initial_message(sample, category, disclosed)")
            session = _BuyerSession(dict(sample_or_session_id), category_or_disclosed)
            target_disclosed = disclosed

        before = set(target_disclosed)
        shadow = set(target_disclosed)
        base = _mode1_initial_message(session.sample, session.category, shadow)
        if self.mode == 1:
            target_disclosed.update(shadow)
            return base
        semantic_values = list(shadow - before)
        protected = _protected_keywords(session, "initial", None, semantic_values)
        shaped = self._shape(session, "initial", base, None, semantic_values, protected)
        message = shaped.get("message") if shaped else None
        if self.mode == 2:
            if not self._mode2_safe(session, "initial", base, protected, message) or _canonical(message) == _canonical(base):
                message = self._mode2_fallback(session)
        elif self.mode == 3:
            if not self._mode3_safe(session, "initial", base, message, [], None):
                message = self._mode3_fallback(session, "initial", None, semantic_values)
        else:
            if not self._mode4_safe(session, "initial", base, message, [], None):
                message = self._mode4_fallback(session, "initial", None, base, semantic_values)

        self._record_exact_values_in_message(session.sample, str(message), target_disclosed)
        target_disclosed.update(shadow)
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
            session = _BuyerSession(dict(sample_or_session_id), "")
        before = set(disclosed)
        shadow = set(disclosed)
        base, base_boundary = _mode1_customer_reply(session.sample, ask_attribute, shadow, boundary_used)
        if self.mode == 1:
            disclosed.update(shadow)
            return base, base_boundary

        attribute = ask_attribute if isinstance(ask_attribute, str) else None
        semantic_values = list(shadow - before)
        protected = _protected_keywords(session, "reply", attribute, semantic_values)
        shaped = self._shape(session, "reply", base, attribute, semantic_values, protected)
        message = shaped.get("message") if shaped else None
        if self.mode == 2:
            if not self._mode2_safe(session, "reply", base, protected, message) or _canonical(message) == _canonical(base):
                message = self._mode2_fallback_reply(base, attribute, semantic_values, base_boundary)
        elif self.mode == 3:
            if not self._mode3_safe(session, "reply", base, message, semantic_values, attribute):
                message = self._mode3_fallback(session, "reply", attribute, semantic_values)
        else:
            if not self._mode4_safe(session, "reply", base, message, semantic_values, attribute):
                message = self._mode4_fallback(session, "reply", attribute, base, semantic_values)

        self._record_exact_values_in_message(session.sample, str(message), disclosed)
        # All accepted/fallback messages preserve the deterministic semantic
        # answer, even when Modes 3-4 express its values using synonyms or a
        # description.  Keep the original disclosure state in sync.
        disclosed.update(shadow)
        return str(message), base_boundary

    def _session(self, session_id: str) -> _BuyerSession:
        with self._lock:
            try:
                return self.sessions[session_id]
            except KeyError as exc:
                raise RuntimeError("reset must be called before using the scenario evaluator") from exc

    def _shape(
        self,
        session: _BuyerSession,
        kind: str,
        base_message: str,
        ask_attribute: str | None,
        semantic_values: list[str],
        protected_keywords: list[str],
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
            "protected_keywords": protected_keywords,
            "structured_answer_values": semantic_values,
            "semantic_targets": _semantic_targets(session, kind, semantic_values),
            "semantic_intent": _semantic_intent(
                kind, base_message, session.sample.get("scenario_type")
            ),
            "profile": session.sample.get("user_profile") or {},
        }
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
    def _mode2_safe(
        session: _BuyerSession,
        kind: str,
        base: str,
        protected: list[str],
        message: object,
    ) -> bool:
        if not ScenarioEvaluator._valid_message(message):
            return False
        text = str(message)
        if not all(_contains_exact(text, keyword) for keyword in protected if keyword):
            return False
        if _contains_negative_change(text):
            return False
        if _unexpected_exact_values(session.sample, [value for value in protected if value], text):
            return False
        if not _intent_preserved(session, kind, base, text):
            return False
        lowered = base.casefold()
        if "no additional preference for" in lowered:
            return "additional preference" in text.casefold()
        if "no preference for" in lowered:
            return "preference" in text.casefold()
        if "not quite right" in lowered:
            return "not quite right" in text.casefold() or "specific attribute" in text.casefold()
        return True

    @staticmethod
    def _mode3_safe(
        session: _BuyerSession,
        kind: str,
        base: str,
        message: object,
        semantic_values: list[str] | None = None,
        ask_attribute: str | None = None,
    ) -> bool:
        if not ScenarioEvaluator._valid_message(message):
            return False
        text = str(message)
        if _contains_negative_change(text):
            return False
        targets = (
            _semantic_targets(session, "initial", [])
            if kind == "initial"
            else [{"canonical_value": value} for value in (semantic_values or [])]
        )
        if not all(_semantic_evidence(target["canonical_value"], text) for target in targets):
            return False
        expected = [target["canonical_value"] for target in targets]
        if _unexpected_exact_values(session.sample, expected, text):
            return False
        if not _intent_preserved(session, kind, base, text):
            return False
        if _canonical(text) == _canonical(base):
            return False
        protected = _protected_keywords(session, kind, ask_attribute, list(semantic_values or []))
        # When there are semantic keywords, Mode 3 must replace at least one
        # with an equivalent expression.  No-value speech acts (for example,
        # no preference) only need a full-sentence rewrite.
        return (
            any(not _contains(text, keyword) for keyword in protected if keyword)
            if protected
            else True
        )

    @staticmethod
    def _mode4_safe(
        session: _BuyerSession,
        kind: str,
        base: str,
        message: object,
        semantic_values: list[str] | None = None,
        ask_attribute: str | None = None,
    ) -> bool:
        if not ScenarioEvaluator._mode3_safe(session, kind, base, message, semantic_values, ask_attribute):
            return False
        text = str(message)
        grammar_or_spelling = bool(re.search(
            r"\b(?:I am look|I looking|it have|which come|a shoes|need a [a-z]+s|"
            r"this is want|more better|does not matters|I wants)\b",
            text,
            re.IGNORECASE,
        ))
        circumlocution = bool(re.search(
            r"\b(?:the thing|the one|which comes|which come|made from|comes from|"
            r"material that|the detail that|you know|the kind of)\b",
            text,
            re.IGNORECASE,
        ))
        return grammar_or_spelling or circumlocution

    @staticmethod
    def _mode2_fallback(session: _BuyerSession) -> str:
        scenario = session.sample.get("scenario_type")
        category = session.category
        if scenario == "buying":
            constraints = session.sample.get("intent_card", {}).get("hard_constraints") or []
            if constraints:
                return f"I want to find {category}, and my main requirement is: {constraints[0]}."
        if scenario == "intent_override":
            old = session.sample.get("behavior", {}).get("override", {}).get("old_value", "")
            return f"I am trying to find {category}. {old}"
        return f"I am hoping to find {category}, but I am still looking around."

    @staticmethod
    def _mode2_fallback_reply(base: str, ask_attribute: str | None, semantic_values: list[str], boundary: bool) -> str:
        if semantic_values:
            return "The important points for me are: " + "; ".join(semantic_values) + "."
        if boundary and ask_attribute:
            return f"I don't mind which {ask_attribute} it is; please decide for me."
        if "additional preference for" in base.casefold() and ask_attribute:
            return f"I do not have any other specific preference for {ask_attribute}."
        if "not quite right" in base.casefold():
            return "These options do not feel right yet; please ask about one specific attribute."
        if ask_attribute:
            return f"I do not have a particular preference for {ask_attribute}."
        return "I am still unsure; please ask me about one specific attribute."

    @staticmethod
    def _mode3_fallback(session: _BuyerSession, kind: str, ask_attribute: str | None, semantic_values: list[str]) -> str:
        if kind == "initial":
            category = _preferred_alias(session.category)
            scenario = session.sample.get("scenario_type")
            if scenario == "buying":
                constraints = session.sample.get("intent_card", {}).get("hard_constraints") or []
                if constraints:
                    return f"I'm shopping for {category}, and {_preferred_alias(str(constraints[0]))} is what I need."
            if scenario == "intent_override":
                old = session.sample.get("behavior", {}).get("override", {}).get("old_value", "")
                return f"I'm trying to find {category}. {_preferred_alias(str(old))}"
            return f"I'm shopping for {category}, and I'm still checking the details."
        if semantic_values:
            return "The main things I care about are: " + "; ".join(_preferred_alias(value) for value in semantic_values) + "."
        if session.sample.get("scenario_type") == "boundary" and ask_attribute:
            return f"I'm flexible about {ask_attribute}; please use your judgment."
        if ask_attribute:
            return f"I do not have another strong preference for {ask_attribute}."
        return "These choices are not working for me yet; ask about one clear attribute."

    @staticmethod
    def _mode4_fallback(
        session: _BuyerSession,
        kind: str,
        ask_attribute: str | None,
        base: str,
        semantic_values: list[str],
    ) -> str:
        if kind == "initial":
            category = _preferred_alias(session.category)
            scenario = session.sample.get("scenario_type")
            constraints = session.sample.get("intent_card", {}).get("hard_constraints") or []
            if scenario == "buying" and constraints:
                return f"I am look for {category}, and I need the thing which {_descriptor(str(constraints[0]))}, okay."
            if scenario == "intent_override":
                old = session.sample.get("behavior", {}).get("override", {}).get("old_value", "")
                return f"I am look for {category}. {old} This one is what I mean."
            return f"I am look for {category}, but I still checking what detail is important."
        if not ask_attribute:
            return "These options is not right yet, please ask me one specific attribute."
        if session.sample.get("scenario_type") == "boundary":
            return f"I don't have no special preference for {ask_attribute}; you decide it for me, please."
        if "no additional preference" in base.casefold():
            return f"I don't have any other special preference for {ask_attribute}, maybe."
        if semantic_values:
            descriptions = [_descriptor(value) for value in semantic_values]
            return (
                f"For this {ask_attribute}, I want the thing which "
                + ", and also the one which ".join(descriptions)
                + ", but my English not very good."
            )
        return f"For {ask_attribute}, I don't have another special preference, maybe."

    @staticmethod
    def _valid_message(message: object) -> bool:
        return isinstance(message, str) and 0 < len(message.strip()) <= 2000

    @staticmethod
    def _record_exact_values_in_message(sample: dict, message: str, disclosed: set[str]) -> None:
        for value in _flatten_constraints(sample):
            if _contains(message, value):
                disclosed.add(value)


def initial_message(sample: dict, category: str, disclosed: set[str]) -> str:
    """Backward-compatible deterministic Mode 1 helper."""

    return _mode1_initial_message(sample, category, disclosed)


def customer_reply(
    sample: dict,
    ask_attribute: object,
    disclosed: set[str],
    boundary_used: bool,
) -> tuple[str, bool]:
    """Backward-compatible deterministic Mode 1 helper."""

    return _mode1_customer_reply(sample, ask_attribute, disclosed, boundary_used)


__all__ = [
    "OllamaBuyerClient",
    "OpenAICompatibleClient",
    "ScenarioEvaluator",
    "customer_reply",
    "initial_message",
    "parse_llm_mode",
    "remote_llm_configured",
    "resolve_buyer_llm_backend",
]
