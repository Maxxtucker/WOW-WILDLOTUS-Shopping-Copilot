#!/usr/bin/env python3
"""Interactive console for the understand NLU path.

Seed prior session fields yourself, type a shopper utterance, and compare
regex vs live Ollama vs the hybrid gate. Does not read public_set.jsonl.

From repo root (PowerShell):

    . .\\scripts\\load_nlu_env.ps1
    python scripts/nlu_console.py

The live client only sees category, locked constraints, and last_ask — not
the full transcript. Play turns (or /seed those fields) to supply context.
When NLU is connected, hybrid prefers the model even on protocol-like phrasing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, TextIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.understand.mode import MODE_NLU, MODE_REGEX, configure_understand
from agent.understand.observation.coordinator import _apply_extract
from agent.understand.observation.hybrid import extract_from_regex, regex_is_high_confidence
from agent.understand.observation.llm_nlu import OllamaNluClient, load_nlu_env
from agent.understand.observation.runtime import ensure_llm_runtime
from agent.understand.observation.schema import ObservationExtract, infer_track
from agent.understand.observation.slots import collect_failures
from agent.understand.state import SessionState

HELP = """
Commands (prefix /). Anything else is this turn's user message.

  /help                 this text
  /state                session fields sent to NLU + history
  /reset                empty session (keeps apply/raw settings)
  /category TEXT        set category (empty TEXT clears)
  /constraints A; B     set locked constraints (semicolon-separated)
  /hint TEXT            set leftover provisional hint
  /ask ATTR             set last asked attribute (color, material, ...)
  /track buying|browsing|clear
  /gate open|closed
  /history-add TEXT     append a prior utterance without extracting
  /paste                multiline message; end with a line that is only .
  /mode all|nlu|regex   what to run (default all)
  /apply nlu|regex|hybrid|none
                        what to write into SessionState after a turn
                        (hybrid prefers NLU when the model returned JSON)
  /raw on|off           print model JSON before span grounding
  /quit                 exit

The model does not receive message_history. Seed /category /constraints /ask
or play turns with /apply nlu so the next call sees updated locks.
""".strip()

APPLY_CHOICES = ("nlu", "regex", "hybrid", "none")
MODE_CHOICES = ("all", "nlu", "regex")


def split_constraints(text: str) -> list[str]:
    """Split a seed string on semicolons. Commas inside a span stay intact."""

    return [part.strip() for part in text.split(";") if part.strip()]


def labeled_constraints(values: tuple[str, ...] | list[str]) -> list[dict[str, str]]:
    """Label leftover string constraints when typed slots are absent."""

    from agent.domain import classify_constraint

    return [
        {"span": item, "attribute": classify_constraint(item)} for item in values
    ]


def labeled_slots(slots) -> list[dict[str, str]]:
    return [{"span": slot.surface, "attribute": slot.attribute} for slot in slots]


def labeled_locked(state: SessionState) -> list[dict[str, str]]:
    if state.typed_constraints:
        return labeled_slots(state.typed_constraints)
    return labeled_constraints(state.active_constraints)


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
        "provisional_hint": extract.provisional_hint,
        "constraints": (
            labeled_slots(extract.slots)
            if extract.slots
            else labeled_constraints(extract.constraints)
        ),
        "slots": slot_rows(extract),
        "override": extract.override,
        "override_value": extract.override_value,
        "track": extract.track or infer_track(extract),
        "repair_rounds": extract.repair_rounds,
    }
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
    if failures.override_value:
        dropped["override_value"] = payload.get("override_value")
    if failures.constraints:
        dropped["constraints"] = failures.constraints
    return dropped


def state_snapshot(state: SessionState) -> dict[str, Any]:
    return {
        "turn": state.turn,
        "category": state.category,
        "track": state.track,
        "active_constraints": labeled_locked(state),
        "legacy_hints": list(state.legacy_hints),
        "ranking_constraints": labeled_constraints(state.ranking_constraints),
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
            "locked_constraints": list(state.active_constraints),
            "last_ask": state.last_ask,
            "note": "Ollama sees only these three fields plus the current message.",
        },
    }


def _set_or_clear(raw: str) -> str | None:
    text = raw.strip()
    return text or None


class NluConsole:
    """Read-eval loop over one SessionState."""

    def __init__(
        self,
        client: OllamaNluClient | None,
        *,
        show_raw: bool = False,
        out: TextIO | None = None,
    ) -> None:
        self.client = client
        self.show_raw = show_raw
        self.out = sys.stdout if out is None else out
        self.mode = "all"
        self.apply_mode = "nlu" if client is not None else "regex"
        self.state = SessionState("nlu-console", {})

    def reset_session(self) -> None:
        self.state = SessionState("nlu-console", {})

    def _write(self, text: str) -> None:
        self.out.write(text if text.endswith("\n") else text + "\n")

    def print_json(self, payload: object) -> None:
        self._write(json.dumps(payload, indent=2, ensure_ascii=False))

    def run_turn(self, message: str) -> None:
        message = message.strip()
        if not message:
            return
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
                constraints=tuple(self.state.active_constraints),
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

        self.print_json(report)

        chosen: ObservationExtract | None
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
        _apply_extract(self.state, message, chosen)
        self._write(f"# applied {self.apply_mode} extract; turn={self.state.turn}")
        self.print_json(
            {
                "category": self.state.category,
                "constraints": labeled_locked(self.state),
                "typed_constraints": [
                    slot.as_dict() if hasattr(slot, "as_dict") else slot
                    for slot in self.state.typed_constraints
                ],
                "track": self.state.track,
                "last_ask": self.state.last_ask,
            }
        )

    def handle_command(self, line: str) -> bool:
        """Return False to exit the loop."""

        stripped = line.strip()
        if not stripped:
            return True
        if stripped in {"/quit", "/exit", "/q"}:
            return False
        if stripped in {"/help", "/h", "/?"}:
            self._write(HELP)
            return True
        if stripped == "/state":
            self.print_json(state_snapshot(self.state))
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
        if command == "/track":
            value = rest.casefold()
            if value in {"", "clear", "none"}:
                self.state.track = None
            elif value in {"buying", "browsing"}:
                self.state.track = value
            else:
                self._write("# track must be buying, browsing, or clear")
                return True
            self._write(f"# track = {self.state.track!r}")
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
            self.apply_mode = value
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
        self._write("# type /state after seeding, then a shopper sentence.")
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
    NluConsole(client, show_raw=args.raw).loop()


if __name__ == "__main__":
    main()
