#!/usr/bin/env python3
"""Interactive console: one production turn, stage by stage, then the agent reply.

Type shopper utterances. With a catalog, each turn runs ``TurnPipeline``
(understand → intention router → retrieve → rank → clarify → respond) and
prints what each stage did plus the customer-facing message and titled
recommendations. Does not read public_set.jsonl.

From repo root (PowerShell):

    . .\\scripts\\load_nlu_env.ps1
    python scripts/nlu_console.py

``--no-retrieve`` skips the catalog (extract + override writeback only).
``--no-live`` is regex understand; router/retrieve/decide still run when
the catalog loads. ``/raw on`` dumps the same data as JSON.

The live NLU client only sees category, locked typed-slot surfaces (or
``/constraints`` strings when slots are empty), and last_ask — not the full
transcript.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, TextIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.intent_router import (
    apply_delta,
    apply_override_decision,
    as_override_decision,
    classify_override,
    warmup_intent_router,
)
from agent.pipeline import TurnPipeline
from agent.retrieve.catalog import CatalogRetriever
from agent.retrieve.catalog.index_path import resolve_index_path
from agent.retrieve.from_slots import exact_pool_groups
from agent.trace import TRACE_TOP, TurnTrace, build_router_trace, build_retrieve_trace
from agent.understand.mode import MODE_NLU, MODE_REGEX, configure_understand
from agent.understand.observation.hybrid import extract_from_regex, regex_is_high_confidence
from agent.understand.observation.llm_nlu import (
    OllamaNluClient,
    load_nlu_env,
    set_nlu_client,
)
from agent.understand.observation.runtime import ensure_llm_runtime
from agent.understand.observation.schema import ObservationExtract
from agent.understand.observation.slots import collect_failures
from agent.understand.state import SessionState

HELP = """
Commands (prefix /). Anything else is this turn's shopper message.

  /help                 this text
  /state                typed slots + NLU context + last stage summaries
  /reset                empty session (keeps apply/raw settings)
  /category TEXT        set category (empty TEXT clears)
  /constraints A; B     set locked constraints (semicolon-separated)
  /hint TEXT            set leftover provisional hint
  /ask ATTR             set last asked attribute (color, material, ...)
  /intention buying|browsing|override|clear
  /gate open|closed
  /history-add TEXT     append a prior utterance without extracting
  /paste                multiline message; end with a line that is only .
  /mode all|nlu|regex   extract preview (/apply none or --no-retrieve)
  /apply nlu|regex|hybrid|none
                        nlu/hybrid: production hybrid extract (NLU then regex).
                        regex: regex understand only.
                        none: preview extract, do not advance the session.
                        With a catalog the turn is TurnPipeline (decide included).
                        --no-retrieve: override writeback only; no recommendations.
  /pool                 last exact-pool sample (or exact is None)
  /raw on|off           also print the turn as JSON
  /quit                 exit

Turns 1-10 match the official session clock. /reset starts a new session.
""".strip()

APPLY_CHOICES = ("nlu", "regex", "hybrid", "none")
MODE_CHOICES = ("all", "nlu", "regex")
EXACT_SAMPLE = 15
RETRIEVE_TOP = TRACE_TOP
MAX_TURNS = 10
TOP_K = 10


def _is_json_primitive(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def format_console_json(payload: object, *, indent: int = 2) -> str:
    """Pretty-print JSON, but keep arrays of primitives on one line.

    Default ``json.dumps(indent=2)`` splits ``canonical: ["orange"]`` across
    three lines and fills the console with closing brackets.
    """

    def encode(value: object, level: int) -> str:
        pad = " " * (indent * level)
        child = " " * (indent * (level + 1))
        if isinstance(value, dict):
            if not value:
                return "{}"
            parts = [
                f"{child}{json.dumps(str(key), ensure_ascii=False)}: {encode(item, level + 1)}"
                for key, item in value.items()
            ]
            return "{\n" + ",\n".join(parts) + f"\n{pad}}}"
        if isinstance(value, (list, tuple)):
            items = list(value)
            if not items:
                return "[]"
            if all(_is_json_primitive(item) for item in items):
                return "[" + ", ".join(encode(item, level) for item in items) + "]"
            parts = [f"{child}{encode(item, level + 1)}" for item in items]
            return "[\n" + ",\n".join(parts) + f"\n{pad}]"
        return json.dumps(value, ensure_ascii=False)

    return encode(payload, 0)


def split_constraints(text: str) -> list[str]:
    """Split a seed string on semicolons. Commas inside a span stay intact."""

    return [part.strip() for part in text.split(";") if part.strip()]


def labeled_constraints(values: tuple[str, ...] | list[str]) -> list[dict[str, str]]:
    """Label leftover string constraints when typed slots are absent."""

    from agent.domain import classify_constraint

    return [
        {"span": item, "attribute": classify_constraint(item)} for item in values
    ]


def slot_rows(extract: ObservationExtract) -> list[dict[str, object]]:
    return [slot.as_dict() for slot in extract.slots]


def extract_as_dict(extract: ObservationExtract | None, *, elapsed_ms: float | None = None) -> dict[str, Any]:
    if extract is None:
        row: dict[str, Any] = {"ok": False}
        if elapsed_ms is not None:
            row["elapsed_ms"] = round(elapsed_ms, 1)
        return row
    row = {
        "ok": True,
        "empty": extract.empty,
        "source": extract.source,
        "category": extract.category,
        "slots": slot_rows(extract),
        "repair_rounds": extract.repair_rounds,
    }
    if extract.provisional_hint:
        row["provisional_hint"] = extract.provisional_hint
    if elapsed_ms is not None:
        row["elapsed_ms"] = round(elapsed_ms, 1)
    return row


def grounding_drops(
    payload: dict[str, Any] | None,
    extract: ObservationExtract | None,
    message: str = "",
) -> dict[str, Any]:
    """Show values that still fail surface grounding after parse/repair."""

    if not payload or extract is None:
        return {}
    failures = collect_failures(payload, message)
    dropped: dict[str, Any] = {}
    if failures.category:
        dropped["category"] = payload.get("category")
    if failures.provisional_hint:
        dropped["provisional_hint"] = payload.get("provisional_hint")
    if failures.constraints:
        dropped["constraints"] = failures.constraints
    return dropped


def hard_groups_payload(state: SessionState) -> list[dict[str, Any]]:
    return [
        {"attribute": attribute, "values": list(values)}
        for attribute, values in exact_pool_groups(state)
    ]


def router_payload(state: SessionState, exact: set[str] | None) -> dict[str, Any]:
    return build_router_trace(state, exact)


def retrieve_payload(
    hits: list,
    exact: set[str] | None,
    exact_lenient: set[str] | None = None,
) -> dict[str, Any]:
    return build_retrieve_trace(hits, exact, exact_lenient=exact_lenient)


def state_snapshot(state: SessionState) -> dict[str, Any]:
    return {
        "turn": state.turn,
        "category": state.category,
        "intention": state.intention,
        "turn_delta": None
        if state.turn_delta is None
        else {
            "category": state.turn_delta.category,
            "slots": [
                slot.as_dict() if hasattr(slot, "as_dict") else slot
                for slot in state.turn_delta.slots
            ],
            "empty": state.turn_delta.empty,
            "source": state.turn_delta.source,
        },
        "candidate_count": state.candidate_count,
        "preference_tags": list(state.preference_tags),
        "last_ask": state.last_ask,
        "gate_open": state.gate_open,
        "override_seen": state.override_seen,
        "message_history": list(state.message_history),
        "typed_constraints": [
            slot.as_dict() if hasattr(slot, "as_dict") else slot
            for slot in state.typed_constraints
        ],
        "model_context": {
            "category": state.category,
            "locked_constraints": list(state.locked_constraint_strings()),
            "last_ask": state.last_ask,
            "note": "Ollama sees only these three fields plus the current message.",
        },
    }


def _set_or_clear(raw: str) -> str | None:
    text = raw.strip()
    return text or None


def _slot_brief(slot: dict[str, Any]) -> str:
    attribute = str(slot.get("attribute") or "?")
    canonical = slot.get("canonical")
    if isinstance(canonical, list) and canonical:
        value = "/".join(str(item) for item in canonical)
    elif slot.get("amount") is not None:
        amount = slot["amount"]
        system = slot.get("system")
        op = slot.get("op") or "eq"
        if system:
            value = f"{str(system).upper()} {amount}"
        else:
            value = f"{op} {amount}"
    else:
        value = str(slot.get("surface") or "").strip()
    return f"{attribute}={value}" if value else attribute


def _group_slots(slots: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    soft: list[str] = []
    for slot in slots:
        text = _slot_brief(slot)
        if slot.get("is_hard", True):
            hard.append(text)
        else:
            soft.append(text)
    return hard, soft


def recommendation_display(
    retriever: CatalogRetriever | None, slate: list[str]
) -> list[str]:
    """Human lines for the slate. Official recommendations stay ASIN-only."""

    lines: list[str] = []
    for index, parent_asin in enumerate(slate, start=1):
        title = parent_asin
        extra = ""
        if retriever is not None:
            product = retriever.get_product(parent_asin) or {}
            title = str(product.get("title") or parent_asin)
            store = product.get("store")
            price = product.get("price")
            bits: list[str] = [parent_asin]
            if store:
                bits.append(str(store))
            if price not in (None, ""):
                bits.append(f"${price}")
            extra = "   " + "  ".join(bits)
        lines.append(f"{index}. {title}{extra}")
    return lines


def format_chatbot_turn(
    trace: TurnTrace, retriever: CatalogRetriever | None = None
) -> str:
    understand = trace.understand
    source = understand.get("source") or "empty"
    category = understand.get("category") or understand.get("session_category") or "-"
    gate = "open" if understand.get("gate_open") else "closed"
    hard, soft = _group_slots(list(understand.get("slots") or []))
    lines = [
        "--- understand ---",
        f"source={source}  category={category}  gate={gate}",
    ]
    if hard:
        lines.append("hard: " + ", ".join(hard))
    if soft:
        lines.append("soft: " + ", ".join(soft))

    router = trace.router
    exact = router.get("exact")
    recall = "exact pool" if exact is not None else "hybrid recall"
    lines.extend(
        [
            "",
            "--- router ---",
            f"intention={router.get('intention')}  exact={exact}  ({recall})",
        ]
    )

    retrieve = trace.retrieve
    top = list(retrieve.get("top") or [])
    top_bit = ""
    if top:
        first = top[0]
        top_bit = f"   top {first.get('parent_asin')} score={first.get('score')}"
    lines.extend(
        [
            "",
            "--- retrieve ---",
            f"{retrieve.get('hit_count', 0)} hits{top_bit}",
        ]
    )

    ranking = list((trace.ranking or {}).get("top") or [])
    lines.extend(["", "--- ranking ---"])
    if ranking:
        first = ranking[0]
        lines.append(
            f"#1 {first.get('parent_asin')}  p={first.get('probability')}"
        )
    else:
        lines.append("(empty)")

    decide = trace.decide
    ask = decide.get("ask_attribute")
    slate = list(decide.get("slate") or [])
    planned = list(decide.get("planned_slate") or [])
    gate_note = "sequential gate" if decide.get("gated") else "planner slate"
    lines.extend(
        [
            "",
            "--- decide ---",
            f"ask={ask}  slate={len(slate)}  planned={len(planned)}  ({gate_note})",
        ]
    )
    reason = decide.get("reason")
    if reason:
        lines.append(str(reason))

    response = trace.response
    lines.extend(["", "--- agent ---", str(response.get("message") or "")])
    recs = [
        str(item.get("parent_asin"))
        for item in response.get("recommendations") or []
        if isinstance(item, dict) and item.get("parent_asin")
    ]
    if recs:
        lines.append("")
        lines.extend(recommendation_display(retriever, recs))
    return "\n".join(lines)


def _trace_as_json(trace: TurnTrace) -> dict[str, Any]:
    payload = {
        "understand": trace.understand,
        "router": trace.router,
        "retrieve": trace.retrieve,
        "ranking": trace.ranking,
        "decide": trace.decide,
        "response": trace.response,
    }
    if trace.exact is not None:
        payload["exact"] = len(trace.exact)
        payload["exact_sample"] = sorted(trace.exact)[:EXACT_SAMPLE]
    return payload


class NluConsole:
    """Read-eval loop over one SessionState."""

    def __init__(
        self,
        client: OllamaNluClient | None,
        *,
        show_raw: bool = False,
        out: TextIO | None = None,
        retriever: CatalogRetriever | None = None,
    ) -> None:
        self.client = client
        self.show_raw = show_raw
        self.out = sys.stdout if out is None else out
        self.retriever = retriever
        self.pipeline = None if retriever is None else TurnPipeline(retriever)
        self.mode = "all"
        self.apply_mode = "nlu" if client is not None else "regex"
        self.state = SessionState("nlu-console", {})
        self.last_exact: set[str] | None = None
        self.last_router: dict[str, Any] | None = None
        self.last_retrieve: dict[str, Any] | None = None
        self.last_trace: TurnTrace | None = None
        self._sync_understand_mode()
        if client is not None:
            set_nlu_client(client)

    def _sync_understand_mode(self) -> None:
        if self.apply_mode == "regex" or self.client is None:
            configure_understand(MODE_REGEX)
        elif self.apply_mode in {"nlu", "hybrid"}:
            configure_understand(MODE_NLU)
            if self.client is not None:
                set_nlu_client(self.client)

    def reset_session(self) -> None:
        self.state = SessionState("nlu-console", {})
        self.last_exact = None
        self.last_router = None
        self.last_retrieve = None
        self.last_trace = None

    def close(self) -> None:
        if self.retriever is not None:
            self.retriever.close()
            self.retriever = None
            self.pipeline = None

    def _write(self, text: str) -> None:
        self.out.write(text if text.endswith("\n") else text + "\n")

    def print_json(self, payload: object) -> None:
        self._write(format_console_json(payload))

    def _inspect_preview(self, message: str) -> dict[str, Any]:
        high_confidence = regex_is_high_confidence(message)
        regex_extract = extract_from_regex(self.state, message)
        nlu_payload: dict[str, Any] | None = None
        nlu_extract: ObservationExtract | None = None
        nlu_ms: float | None = None
        nlu_error: str | None = None

        want_nlu = self.mode in {"all", "nlu"}
        if want_nlu and self.client is None:
            nlu_error = "live NLU client is not connected"
        elif want_nlu:
            started = time.perf_counter()
            nlu_payload, nlu_extract = self.client.inspect(
                message,
                category=self.state.category,
                constraints=self.state.locked_constraint_strings(),
                last_ask=self.state.last_ask,
            )
            nlu_ms = (time.perf_counter() - started) * 1000
            if nlu_payload is None:
                nlu_error = (
                    getattr(self.client, "last_error", None)
                    or "Ollama returned no JSON (timeout, parse, or connection)"
                )

        if nlu_extract is not None:
            hybrid_choice = "nlu"
            hybrid_extract = nlu_extract
        elif high_confidence:
            hybrid_choice = "regex"
            hybrid_extract = regex_extract
        else:
            hybrid_choice = "regex_fallback"
            hybrid_extract = regex_extract

        report: dict[str, Any] = {
            "message": message,
            "regex_high_confidence": high_confidence,
            "hybrid_would_use": hybrid_choice,
        }
        if self.mode in {"all", "regex"}:
            report["regex"] = extract_as_dict(regex_extract)
        if self.mode in {"all", "nlu"}:
            nlu_row = extract_as_dict(nlu_extract, elapsed_ms=nlu_ms)
            if nlu_error:
                nlu_row["error"] = nlu_error
            drops = grounding_drops(nlu_payload, nlu_extract, message)
            if drops:
                nlu_row["dropped_ungrounded"] = drops
            report["nlu"] = nlu_row
            if self.show_raw and nlu_payload is not None:
                report["nlu_raw"] = nlu_payload
        report["_hybrid_extract"] = hybrid_extract
        report["_nlu_extract"] = nlu_extract
        report["_regex_extract"] = regex_extract
        report["_nlu_error"] = nlu_error
        return report

    def _remember_trace(self, trace: TurnTrace) -> None:
        self.last_trace = trace
        self.last_exact = None if trace.exact is None else set(trace.exact)
        self.last_router = dict(trace.router)
        self.last_retrieve = dict(trace.retrieve)

    def _run_pipeline_turn(self, message: str) -> None:
        assert self.pipeline is not None
        next_turn = self.state.turn + 1
        if next_turn > MAX_TURNS:
            self._write(
                f"# session already at turn {self.state.turn}. "
                "Official scoring stops at 10. Type /reset to start again."
            )
            return
        self._sync_understand_mode()
        _response, trace = self.pipeline.run_traced(
            self.state, message, next_turn, TOP_K
        )
        self._remember_trace(trace)
        self._write(format_chatbot_turn(trace, self.retriever))
        if self.show_raw:
            self.print_json(_trace_as_json(trace))

    def _run_writeback_turn(self, message: str) -> None:
        report = self._inspect_preview(message)
        hybrid_extract = report.pop("_hybrid_extract")
        nlu_extract = report.pop("_nlu_extract")
        regex_extract = report.pop("_regex_extract")
        nlu_error = report.pop("_nlu_error")
        self.print_json(report)

        if self.apply_mode == "none":
            self._write("# session unchanged (/apply none)")
            return
        if self.apply_mode == "nlu":
            chosen = nlu_extract
            if chosen is None:
                reason = nlu_error or "NLU extract missing"
                self._write(
                    f"# apply skipped: {reason}. "
                    "Regex is not applied (it can false-trigger override on words like actually / I want)."
                )
                return
        elif self.apply_mode == "regex":
            chosen = regex_extract
        else:
            chosen = hybrid_extract

        self.state.turn += 1
        self.state.latest_message = message
        self.state.message_history.append(message)
        self.state.turn_delta = None if chosen.empty else chosen
        if self.client is None:
            apply_delta(self.state)
        else:
            decision = as_override_decision(classify_override(self.state))
            if decision.overridden:
                apply_override_decision(self.state, decision)
                self.state.intention = "override"
            else:
                apply_delta(self.state)
        applied: dict[str, Any] = {
            "delta": None
            if self.state.turn_delta is None
            else {
                "category": self.state.turn_delta.category,
                "slots": slot_rows(self.state.turn_delta),
            },
            "session": {
                "category": self.state.category,
                "typed_constraints": [
                    slot.as_dict() if hasattr(slot, "as_dict") else slot
                    for slot in self.state.typed_constraints
                ],
                "intention": self.state.intention,
                "last_ask": self.state.last_ask,
            },
        }
        self._write(
            f"# applied {self.apply_mode} extract; turn={self.state.turn}. "
            "Decide skipped (--no-retrieve)."
        )
        self.print_json(applied)

    def run_turn(self, message: str) -> None:
        message = message.strip()
        if not message:
            return
        if self.apply_mode == "none":
            report = self._inspect_preview(message)
            report.pop("_hybrid_extract", None)
            report.pop("_nlu_extract", None)
            report.pop("_regex_extract", None)
            report.pop("_nlu_error", None)
            self.print_json(report)
            self._write("# session unchanged (/apply none)")
            return
        if self.pipeline is not None:
            self._run_pipeline_turn(message)
            return
        self._run_writeback_turn(message)

    def handle_command(self, line: str) -> bool:
        """Return False to exit the loop."""

        stripped = line.strip()
        if not stripped:
            return True
        if stripped in {"/quit", "/exit", "/q"}:
            self.close()
            return False
        if stripped in {"/help", "/h", "/?"}:
            self._write(HELP)
            return True
        if stripped == "/state":
            snap = state_snapshot(self.state)
            if self.last_router is not None:
                snap["router"] = self.last_router
            if self.last_retrieve is not None:
                snap["retrieve"] = self.last_retrieve
            if self.last_trace is not None:
                snap["decide"] = self.last_trace.decide
                snap["response"] = self.last_trace.response
            self.print_json(snap)
            return True
        if stripped == "/pool":
            if self.last_exact is None:
                self._write("# exact is None")
            else:
                self.print_json(
                    {
                        "exact": len(self.last_exact),
                        "sample": sorted(self.last_exact)[:EXACT_SAMPLE],
                    }
                )
            return True
        if stripped == "/reset":
            self.reset_session()
            self._write("# session cleared")
            return True
        if stripped == "/paste":
            self._write("# paste the utterance; finish with a line that is only .")
            self.run_turn(self._read_paste())
            return True

        command, _, rest = stripped.partition(" ")
        rest = rest.strip()
        if command == "/category":
            self.state.category = _set_or_clear(rest)
            self._write(f"# category = {self.state.category!r}")
            return True
        if command == "/constraints":
            self.state.active_constraints = split_constraints(rest)
            self._write(f"# constraints = {self.state.active_constraints!r}")
            return True
        if command == "/hint":
            hint = _set_or_clear(rest)
            self.state.legacy_hints = [hint] if hint else []
            self._write(f"# legacy_hints = {self.state.legacy_hints!r}")
            return True
        if command == "/ask":
            self.state.last_ask = _set_or_clear(rest)
            if self.state.last_ask and self.state.last_ask not in self.state.asked:
                self.state.asked.append(self.state.last_ask)
            self._write(f"# last_ask = {self.state.last_ask!r}")
            return True
        if command in {"/intention", "/track"}:
            value = rest.casefold()
            if value in {"", "clear", "none"}:
                self.state.intention = None
            elif value in {"buying", "browsing", "override"}:
                self.state.intention = value
            else:
                self._write("# intention must be buying, browsing, override, or clear")
                return True
            self._write(f"# intention = {self.state.intention!r}")
            return True
        if command == "/gate":
            value = rest.casefold()
            if value == "open":
                self.state.gate_open = True
            elif value == "closed":
                self.state.gate_open = False
            else:
                self._write("# gate must be open or closed")
                return True
            self._write(f"# gate_open = {self.state.gate_open}")
            return True
        if command == "/history-add":
            if not rest:
                self._write("# /history-add needs text")
                return True
            self.state.message_history.append(rest)
            self._write(f"# history length {len(self.state.message_history)}")
            return True
        if command == "/mode":
            value = rest.casefold()
            if value not in MODE_CHOICES:
                self._write(f"# mode must be one of {', '.join(MODE_CHOICES)}")
                return True
            self.mode = value
            self._write(f"# mode = {self.mode}")
            return True
        if command == "/apply":
            value = rest.casefold()
            if value not in APPLY_CHOICES:
                self._write(f"# apply must be one of {', '.join(APPLY_CHOICES)}")
                return True
            if value in {"nlu", "hybrid"} and self.client is None:
                self._write("# apply nlu/hybrid needs a live NLU client; staying on regex")
                return True
            self.apply_mode = value
            if value != "none":
                self._sync_understand_mode()
            self._write(f"# apply = {self.apply_mode}")
            return True
        if command == "/raw":
            value = rest.casefold()
            if value in {"on", "1", "true"}:
                self.show_raw = True
            elif value in {"off", "0", "false"}:
                self.show_raw = False
            else:
                self._write("# /raw on|off")
                return True
            self._write(f"# raw = {self.show_raw}")
            return True

        self._write(f"# unknown command {command!r}; /help")
        return True

    def _read_paste(self) -> str:
        lines: list[str] = []
        while True:
            try:
                chunk = input()
            except EOFError:
                break
            if chunk.strip() == ".":
                break
            lines.append(chunk)
        return "\n".join(lines)

    def loop(self) -> None:
        self._write(HELP)
        self._write("")
        if self.client is None:
            self._write("# live NLU off; regex only. Use /apply regex.")
        else:
            self._write(
                f"# live NLU on  model={self.client.model}  "
                f"host={self.client.host}  apply={self.apply_mode}"
            )
        if self.retriever is None:
            self._write("# retrieve off; apply is override writeback only. Decide skipped.")
        else:
            sidecar = (
                "attached" if self.retriever._slots_attached else "not attached"
            )
            self._write(
                f"# full pipeline on  catalog={self.retriever.catalog_path}  "
                f"sidecar={sidecar}"
            )
        self._write("# type a shopper sentence. /state shows memory. /raw on dumps JSON.")
        try:
            while True:
                try:
                    line = input(f"nlu t{self.state.turn}> ")
                except (EOFError, KeyboardInterrupt):
                    self._write("")
                    return
                stripped = line.strip()
                if stripped.startswith("/"):
                    if not self.handle_command(stripped):
                        return
                    continue
                self.run_turn(line)
        finally:
            self.close()


def _configure_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-live",
        action="store_true",
        help="Do not call Ollama; regex extracts only.",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Start with /raw on.",
    )
    parser.add_argument(
        "--catalog",
        default="data/catalog.jsonl",
        help="Catalog JSONL for the full pipeline (default data/catalog.jsonl).",
    )
    parser.add_argument(
        "--no-retrieve",
        action="store_true",
        help="Skip catalog load; apply is override writeback only.",
    )
    args = parser.parse_args()
    _configure_stdio()
    client: OllamaNluClient | None = None
    if args.no_live:
        configure_understand(MODE_REGEX)
    else:
        load_nlu_env()
        configure_understand(MODE_NLU)
        ensure_llm_runtime()
        client = OllamaNluClient.from_env()
        set_nlu_client(client)
        warmup_intent_router()
    retriever: CatalogRetriever | None = None
    if not args.no_retrieve:
        catalog_path = Path(args.catalog)
        if not catalog_path.is_file():
            print(f"# catalog not found ({catalog_path}); retrieve off", flush=True)
        else:
            print("# loading catalog index (reuses cache when unchanged)...", flush=True)
            retriever = CatalogRetriever(
                catalog_path,
                index_path=resolve_index_path(catalog_path),
            )
            if not retriever._slots_attached:
                print("# sidecar not attached; probe may return None", flush=True)
    NluConsole(client, show_raw=args.raw, retriever=retriever).loop()


if __name__ == "__main__":
    main()
