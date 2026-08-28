# Understand NLU path

This page records how observation extracts category, constraints, override, and track. It is the design note for local Ollama NLU. Layer READMEs stay the short collaboration maps: [`agent/understand/README.md`](../../agent/understand/README.md), [`agent/understand/observation/README.md`](../../agent/understand/observation/README.md), [`slots/README.md`](../../agent/understand/observation/slots/README.md). Pipeline context: [`agent_pipeline.md`](agent_pipeline.md).

Official kit tests and the published public-set numbers use **regex** observation (`understand_mode="regex"`). `Agent()` itself defaults to **nlu**.

## What observe does

`observe` does not parse. It asks `hybrid_extract` for one frozen `ObservationExtract`, then `_apply_extract` writes `SessionState` (slots, `active_constraints`, category, override, track). Apply order is still constraints before override so catalog copy that contains `instead` / `forget` cannot reset intent.

```text
begin_turn
    observe
        hybrid_extract  → ObservationExtract   (no session writes)
        _apply_extract  → SessionState
```

Production hybrid has two sources only: the local model, or regex. Tests stub `agent.understand.observation.hybrid.extract_with_llm` with `unittest.mock.patch`. There is no extractor hook on `observe` or `Agent`.

## Mode

Process-wide pin in [`agent/understand/mode.py`](../../agent/understand/mode.py). Values: `nlu` | `regex`.

Resolve order (first match wins):

1. `Agent(..., understand_mode=...)` or `configure_understand(...)`
2. `AGENT_UNDERSTAND_MODE`
3. `AGENT_NLU_ENABLED` in `{0, false, no, off}` → `regex`
4. default `nlu`

`current_understand_mode()` returns the pin if set, otherwise the env resolve. `reset_understand_mode()` clears the pin (tests).

## Agent startup (nlu only)

[`agent/orchestrator.py`](../../agent/orchestrator.py):

1. Unless the keyword is already `regex`, load [`scripts/nlu.env`](../../scripts/nlu.env) into `os.environ` (does not run on import).
2. `configure_understand(resolve_understand_mode(understand_mode))`.
3. If mode is `nlu`: [`ensure_llm_runtime()`](../../agent/understand/observation/runtime.py) then `warmup_nlu()`.

Runtime is best-effort and must not raise from `Agent.__init__`:

- GET `{host}/api/tags` with a short timeout.
- If down: prepend the usual Windows Ollama install dir to `PATH`, spawn `ollama serve` detached, wait until tags succeed (about 20s).
- POST `/api/generate` with `num_predict=1` so the configured model loads. **No `ollama pull`.**

If the daemon never comes up, later turns fail the extract three times and use regex.

Keyword `understand_mode="regex"` skips the env file and does not start Ollama. Kit tests do that.

## Per-turn extract

[`hybrid_extract`](../../agent/understand/observation/hybrid.py):

```text
if mode is nlu:
    for attempt in 1..3:          # NLU_ATTEMPTS
        extract_with_llm(...)     # None = timeout, connection, empty/non-JSON
        if extract: return it
regex classify.py
```

Protocol-looking messages still go to the model in nlu mode. `regex_is_high_confidence` is diagnostic only.

One `extract_with_llm` call is one `inspect()`: chat JSON, then up to three **span-repair** rounds inside that attempt ([`MAX_REPAIR_ROUNDS`](../../agent/understand/observation/slots/pipeline.py)). Repair is not a fourth outer retry.

Ollama options: `NUM_PREDICT=4096`, `NUM_CTX=8192`, `temperature=0`. If `done_reason=length`, `_complete` retries once at `NUM_PREDICT * 2`.

The HTTP client is [`llm_nlu.py`](../../agent/understand/observation/llm_nlu.py). It does not write session state. Model context is category, locked constraint strings, and `last_ask` plus the current message.

## After extract

Typed slots on the extract become `state.typed_constraints`. Retrieve does **not** store flattened search pairs on session; [`retrieve/from_slots.py`](../../agent/retrieve/from_slots.py) builds groups from `typed_constraints` (OR inside a slot, AND across slots) at retrieve time. Empty slots fall back to `ranking_constraints` strings.

Slot grounding (cite vs classify, size kinds, OR lists): [slots/README.md](../../agent/understand/observation/slots/README.md).

## Regex shapes (fallback and kit tests)

Same templates as before, in `classify.py` / intention parsers:

| Shape | Result |
| --- | --- |
| `I'm looking for X. A key requirement is: Y.` | category X, locked Y, gate open |
| `I'm looking for X, but I'm still exploring.` | category X only |
| `I'm looking for X. {rest}` | category X; rest is leftover hint, gate closed |
| `For that, what matters is: A; B.` | locked constraints (semicolon restore) |
| Override phrasing | clear leftover, open gate, write the new constraint |
| Empty / no preference | write nothing |

## Env and scripts

| Key | Role |
| --- | --- |
| `AGENT_NLU_MODEL` | Ollama model (default `qwen3.5:4b`) |
| `AGENT_NLU_HOST` | default `http://127.0.0.1:11434` |
| `AGENT_NLU_TIMEOUT` | HTTP timeout seconds |
| `AGENT_UNDERSTAND_MODE` | `nlu` or `regex` if Agent does not pass a keyword |
| `AGENT_NLU_ENABLED` | `0`/`false`/`off` forces regex when mode is not pinned |

Do not set these as user/system environment variables if you want kit tests to stay isolated. File: `scripts/nlu.env`. Load in PowerShell: `. .\scripts\load_nlu_env.ps1`.

| Script | Role |
| --- | --- |
| `scripts/nlu_console.py` | Interactive observe only (no retrieve). Live path configures nlu and calls `ensure_llm_runtime`. `--no-live` is regex. |
| `scripts/nlu_probe.py --live` | Fixture spans vs live model |

## Tests

- [`tests/test_agent.py`](../../tests/test_agent.py): `setUpModule` + `Agent(..., understand_mode="regex")`. Protocol `begin_turn` stays regex and offline.
- [`tests/test_nlu.py`](../../tests/test_nlu.py): regex by default in hybrid tests; nlu tests `configure_understand("nlu")` and patch `hybrid.extract_with_llm`. Three `None` returns then regex. Agent nlu constructs with `ensure_llm_runtime` mocked. No live Ollama in CI.

## Files

| Path | Role |
| --- | --- |
| `agent/understand/mode.py` | Resolve and pin mode |
| `agent/understand/observation/hybrid.py` | NLU attempts then regex |
| `agent/understand/observation/llm_nlu.py` | Chat client, prompts, parse |
| `agent/understand/observation/runtime.py` | Daemon ping / spawn / model load |
| `agent/understand/observation/coordinator.py` | Apply extract to session |
| `agent/orchestrator.py` | Keyword, env load, runtime warmup |
