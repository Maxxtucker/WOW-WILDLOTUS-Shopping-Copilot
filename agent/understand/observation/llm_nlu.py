"""Purpose: Ollama JSON client for natural-language observation.

Input: host/model/timeout from env plus one user message and compact session context.
Output: ObservationExtract, or None on timeout/parse/network failure.
Role: HTTP only. Rewrites color/material aliases (word-class gates in parallel),
walks the category tree, caps a bloated category list, extracts attributes,
then judges whether the original utterance disclosed a category or attribute.
Agent nlu mode constructs the client once.
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from ...domain import MATERIALS
from ...progress import emit, skip_nodes
from ..mode import MODE_NLU, current_understand_mode
from .category_cap import cap_category_payload
from .disclosure import apply_disclosure
from .category_scope import (
    filter_layer_decision,
    node_adds_unstated_audience,
)
from .category_tree import (
    CategoryLayerDecision,
    CategoryNode,
    load_category_tree,
    walk_category_tree,
)
from .rewrite import AliasHit, rewrite_for_nlu
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
from .slots.attributes.category import cite_category_node, node_category_canonicals

if TYPE_CHECKING:
    from ..state.session import SessionState

DEFAULT_MODEL = "qwen3.5:4b"
DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT = 30.0
NUM_PREDICT = 4096
NUM_PREDICT_CATEGORY = 512
NUM_PREDICT_ALIAS = 256
NUM_CTX = 8192
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _attribute_system_prompt() -> str:
    colors = ", ".join(CLOSED_COLORS)
    materials = ", ".join(MATERIALS)
    systems = ", ".join(SIZE_SYSTEMS)
    kinds = ", ".join(SIZE_KINDS)
    letters = ", ".join(APPAREL_LETTERS)
    units = ", ".join(SIZE_UNITS)
    return f"""\
You extract this turn's shopping attributes from one customer message.
Do not decide override, buying, browsing, or product category. Return JSON with exactly these keys:
constraints, empty.

Attribute names (use these strings only):
material, color, size, style, brand, budget, feature, use_case, other.

Do not emit category. Do not invent a product-type phrase.

constraints is a list of objects. Omit null fields. Shape:
{{"attribute": "<name>", "surface": "<span from the message>", "is_hard": true|false, "surfaces": ["<optional alternative spans>"], "canonical": ["<mapped values>"], "amount": <number>, "op": "lte"|"gte"|"eq", "system": "us"|"uk"|"eu", "kind": "shoe"|"apparel"|"dimension", "unit": "in", "length": <number>, "width": <number>, "height": <number>, "weight": <number>}}

Value types:
- color: canonical MUST be a JSON array of buckets from: {colors}. You choose the nearest bucket (for example navy → blue). grey and gray are the same bucket. Alternatives (blue or orange or pink) are ONE constraint with canonical: ["blue", "orange", "pink"]. Do not emit three color objects. surface is the shopper phrase, copied from the message. Optional surfaces lists each alternative span.
- material: canonical MUST be a JSON array of buckets from: {materials}. Same OR rule as color (leather or canvas → one object, canonical: ["leather", "canvas"]).
- budget: keep a number in amount. op is lte for under/max, gte for over/min, else eq. surface is a copied span or the digits that appear in the message.
- size: copy surface from the message. Set kind to one of: {kinds}. Code does not infer shoe vs apparel from product words.
  shoe: footwear (shoes, boots, sandals). system is one of: {systems} when named. amount is the number. EUR maps to eu. Do not guess US/UK/EU.
  apparel: clothes and pants. Letter sizes: canonical MUST be a one-item array from: {letters}. You choose the bucket (extra small → xs, 2XL → xxl). Numeric clothing (US 4, waist 32) uses amount and optional system; that is not a shoe size.
  dimension: object length/width/height and optional weight (3 x 3 inches, 21 cm, 1.52 pounds, 24 oz). Copy the original numbers from the message into length, width, height, and weight. Do not convert. Do not invent L/W/H when the shopper only named a weight. Stored size unit is {units} after code converts cm/mm to inches. Weight is stored in pounds after code converts oz/kg/g.
  If more than one shoe/clothing scale is named, system is omitted and surface keeps the full phrase. If the product type is unclear, omit kind.
- brand, style, use_case, feature, other: free strings. Copy a message span into surface. Alternatives (Nike or Adidas) are ONE constraint with canonical as a JSON array of the alternative strings. Do not emit one object per brand name.

Rules:
- surface MUST appear in the user message. Do not invent words. Each surfaces[] entry MUST also appear in the message.
- Extract only this message. Do not repeat constraints already in the locked list unless this message restates them.
- canonical is a JSON array for color, material, style, brand, feature, use_case, and other. Size letter canonical is a one-item array.
- canonical may differ from surface for color, material, and apparel letter mapping. Do not span-check canonical.
- Alternatives use one object and a canonical array. Do not emit one object per alternative for the same attribute.
- empty: true only for non-answers (no preference, use your judgment, not quite right). A product type with no color or size is empty false and constraints [].
- is_hard defaults to true. Set false only for the span whose wording is prefer / maybe / nice to have / also ok / better to be / still exploring. A preferably on color does not make size or budget soft. Do not infer hardness from product copy or catalog text.
- Do not mention products or ASINs.
"""


_CATEGORY_LAYER_PROMPT = """\
You assign this shopping message to catalog branches that can contain the shopper's product.
Return JSON only: {"ids": ["<id>"], "stop": false}

ids: copy 0 to 3 ids from the allowed list. Empty ids is allowed and is the right answer when no listed branch fits.
Do not pick a branch only because it shares a word (shoe vs kids shoe).

Keep a branch only when its product meaning is broader than or equal to the product the shopper named:
- Broader or equal is OK: "running shoes" may select Shoes or Clothing, Shoes & Jewelry.
- Narrower is not OK: do not add a restriction the message did not state (Kids, Boys, Girls, Women, Men, Baby, a sport or product type they did not name).
- "running shoes" → Shoes OK; Kids Shoes / Girls Sneakers not OK.
- "women's sandals" → Women and Sandals OK; Men's Sandals not OK.

If no listed child is a valid broader-or-equal match, return {"ids": [], "stop": true}.
stop: true when ids is empty, when the listed nodes are already as specific as the message, or when you selected Unknown.
Use Unknown only if it is in the allowed list and the message is not about these categories.
Do not invent ids. Do not return attributes, products, or ASINs.
"""

_ATTRIBUTE_SYSTEM_PROMPT = _attribute_system_prompt()
_SYSTEM_PROMPT = _ATTRIBUTE_SYSTEM_PROMPT
_COLOR_WORD_PROMPT = """\
You check color alias pairs. Each pair is source → canonical.
Keep a pair only when BOTH strings are color or shade names (including uncommon pigments).
Do not judge whether the mapping is the right bucket.
Drop pairs where the source is a stopword or not a color word.
Return JSON only: {"keep": ["<source>", ...]}
Copy source strings from the list. Do not invent sources.
"""
_MATERIAL_WORD_PROMPT = """\
You check material alias pairs. Each pair is source → canonical.
Keep a pair only when BOTH strings are material, fiber, or fabric names.
Do not judge whether the mapping is the right bucket.
Drop pairs where the source is not a material word.
Return JSON only: {"keep": ["<source>", ...]}
Copy source strings from the list. Do not invent sources.
"""


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
        self._error_lock = threading.Lock()

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

        rewritten = rewrite_for_nlu(
            message,
            verify_color=self._verify_color_hits,
            verify_material=self._verify_material_hits,
        )
        picks = self._category_picks(message)
        category_rows = cap_category_payload(
            message,
            category_payload_from_nodes(picks, message),
            complete=self._complete,
        )
        emit("understand", "attribute_llm", "running")
        payload = self._complete(
            _user_prompt(rewritten, category, constraints, last_ask),
            system=_ATTRIBUTE_SYSTEM_PROMPT,
        )
        if payload is None:
            emit("understand", "attribute_llm", "error")
            skip_nodes("understand", "repair_1", "repair_2", "repair_3", "disclosure")
            return None, None
        emit("understand", "attribute_llm", "completed")
        working = copy.deepcopy(payload)
        _drop_category_constraints(working)
        if category_rows:
            working["category"] = category_rows
            working["empty"] = False
        repair_rounds = 0
        while repair_rounds < MAX_REPAIR_ROUNDS:
            failures = collect_failures(working, rewritten)
            if not failures:
                break
            repair_rounds += 1
            node = f"repair_{repair_rounds}"
            emit("understand", node, "running")
            repair = self._complete(
                _repair_prompt(rewritten, failures),
                system=_ATTRIBUTE_SYSTEM_PROMPT,
            )
            if repair is None:
                emit("understand", node, "error")
                break
            working = merge_repair_payload(working, repair, failures)
            _drop_category_constraints(working)
            if category_rows:
                working["category"] = category_rows
            emit("understand", node, "completed")
        skip_nodes(
            "understand",
            *[
                f"repair_{index}"
                for index in range(repair_rounds + 1, MAX_REPAIR_ROUNDS + 1)
            ],
        )
        extract = parse_observation_payload(
            working, rewritten, category_message=message
        )
        extract = apply_disclosure(
            replace(extract, repair_rounds=repair_rounds),
            message,
            complete=self._complete,
        )
        return working, extract

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

    def _category_picks(self, message: str) -> tuple[CategoryNode, ...]:
        return walk_category_tree(message, classify=self._classify_category_layer)

    def _verify_color_hits(self, hits: Sequence[AliasHit]) -> list[AliasHit]:
        return self._verify_alias_hits(hits, system=_COLOR_WORD_PROMPT)

    def _verify_material_hits(self, hits: Sequence[AliasHit]) -> list[AliasHit]:
        return self._verify_alias_hits(hits, system=_MATERIAL_WORD_PROMPT)

    def _verify_alias_hits(
        self,
        hits: Sequence[AliasHit],
        *,
        system: str,
    ) -> list[AliasHit]:
        pending = list(hits)
        if not pending:
            return []
        payload = self._complete(
            _alias_pairs_user_prompt(pending),
            system=system,
            num_predict=NUM_PREDICT_ALIAS,
        )
        if payload is None or "keep" not in payload:
            return pending
        raw_keep = payload.get("keep")
        if not isinstance(raw_keep, list):
            return pending
        allowed = {hit.phrase for hit in pending}
        keep = {
            str(item or "").strip().casefold()
            for item in raw_keep
            if str(item or "").strip().casefold() in allowed
        }
        return [hit for hit in pending if hit.phrase in keep]

    def _classify_category_layer(
        self,
        message: str,
        parent: CategoryNode | None,
        children: tuple[CategoryNode, ...],
    ) -> CategoryLayerDecision | None:
        del parent
        payload = self._complete(
            _category_layer_user_prompt(message, children),
            system=_CATEGORY_LAYER_PROMPT,
            num_predict=NUM_PREDICT_CATEGORY,
        )
        if payload is None:
            return None
        return filter_layer_decision(
            message, children, parse_category_layer_payload(payload)
        )

    def _chat(
        self,
        message: str,
        category: str | None,
        constraints: tuple[str, ...],
        last_ask: str | None,
    ) -> dict | None:
        return self._complete(
            _user_prompt(message, category, constraints, last_ask),
            system=_ATTRIBUTE_SYSTEM_PROMPT,
        )

    def _complete(
        self,
        user_content: str,
        *,
        system: str | None = None,
        num_predict: int | None = None,
    ) -> dict | None:
        predict = NUM_PREDICT if num_predict is None else num_predict
        system_content = _ATTRIBUTE_SYSTEM_PROMPT if system is None else system
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_content},
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
            self._set_last_error(f"timeout after {self.timeout:g}s")
            return None
        except (urllib.error.URLError, OSError) as exc:
            self._set_last_error(f"connection failed: {exc}")
            return None
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            self._set_last_error("Ollama envelope was not JSON")
            return None
        if isinstance(envelope, dict) and envelope.get("error"):
            self._set_last_error(str(envelope.get("error")))
            return None
        content = _message_text(envelope)
        parsed = _loads_json_object(content)
        if parsed is not None:
            self._set_last_error(None)
            return parsed
        done = envelope.get("done_reason") if isinstance(envelope, dict) else None
        if done == "length" and predict < NUM_PREDICT * 2:
            return self._complete(
                user_content,
                system=system_content,
                num_predict=predict * 2,
            )
        snippet = content[:180].replace("\n", " ")
        if not content:
            self._set_last_error(f"empty model content (done_reason={done!r})")
        else:
            self._set_last_error(
                f"content was not a JSON object (done_reason={done!r}): {snippet!r}"
            )
        return None

    def _set_last_error(self, message: str | None) -> None:
        with self._error_lock:
            self.last_error = message


def category_payload_from_nodes(
    nodes: tuple[CategoryNode, ...], message: str
) -> list[dict[str, Any]]:
    root_ids = {node.id for node in load_category_tree()}
    items: list[dict[str, Any]] = []
    for node in nodes:
        if node.id not in root_ids and node_adds_unstated_audience(message, node):
            continue
        cited = cite_category_node(
            message,
            label=node.label,
            node_id=node.id,
            tags=node.catalog_tags,
        )
        if not cited:
            continue
        canonicals = node_category_canonicals(
            message,
            label=node.label,
            node_id=node.id,
            tags=node.catalog_tags,
        )
        if not canonicals:
            continue
        items.append(
            {
                "surface": cited,
                "is_hard": True,
                "canonical": list(canonicals),
            }
        )
    return items


def parse_category_layer_payload(payload: dict[str, Any]) -> CategoryLayerDecision:
    raw_ids = payload.get("ids", payload.get("id"))
    ids: list[str] = []
    if isinstance(raw_ids, str):
        if raw_ids.strip():
            ids.append(raw_ids.strip())
    elif isinstance(raw_ids, list):
        for item in raw_ids:
            text = str(item or "").strip()
            if text:
                ids.append(text)
    stop_raw = payload.get("stop")
    if isinstance(stop_raw, str):
        stop = stop_raw.strip().casefold() in {"true", "1", "yes"}
    else:
        stop = bool(stop_raw)
    return CategoryLayerDecision(ids=tuple(ids), stop=stop)


def _drop_category_constraints(payload: dict[str, Any]) -> None:
    raw = payload.get("constraints")
    if not isinstance(raw, list):
        return
    kept: list[Any] = []
    for item in raw:
        if isinstance(item, dict):
            attribute = str(item.get("attribute") or item.get("name") or "").strip().casefold()
            if attribute in {"category", "categories"}:
                continue
        kept.append(item)
    payload["constraints"] = kept


def _alias_pairs_user_prompt(hits: Sequence[AliasHit]) -> str:
    lines = ["Pairs (source → canonical):"]
    for hit in hits:
        lines.append(f"- {hit.phrase} → {hit.replacement}")
    return "\n".join(lines)


def _category_layer_user_prompt(message: str, children: tuple[CategoryNode, ...]) -> str:
    lines = ["Allowed categories (id — label):"]
    for node in children:
        lines.append(f"- {node.id} — {node.label}")
    lines.append(
        "If none of the listed branches is a valid broader-or-equal match, "
        'return {"ids": [], "stop": true}.'
    )
    lines.append(f"User message: {message}")
    return "\n".join(lines)


def _repair_prompt(message: str, failures: GroundingFailures) -> str:
    failed_names: list[str] = []
    if failures.category:
        failed_names.append("category")
    if failures.provisional_hint:
        failed_names.append("provisional_hint")
    if failures.constraints:
        failed_names.append("constraints")
    failed_json = json.dumps(failures.constraints, ensure_ascii=False, default=str)
    return (
        "The previous JSON failed span checks. Return JSON with ONLY the failed keys.\n"
        "For constraints, return a list of slot objects. surface MUST appear in the user message.\n"
        "For color and material, canonical MUST be one of the closed lists in the system prompt; you choose the bucket.\n"
        "Do not emit category.\n"
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


def set_nlu_client(client: OllamaNluClient | None) -> None:
    """Install the process-wide NLU client. Console and tests inject here."""

    global _client
    _client = client


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
        constraints=state.locked_constraint_strings(),
        last_ask=state.last_ask,
    )
