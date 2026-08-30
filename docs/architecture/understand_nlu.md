# Understand NLU path

This page records how observation extracts this turn's category and constraint slots into `turn_delta`. Buying vs browsing vs override is **not** decided here; that is the intention router. Layer READMEs stay the short collaboration maps: [`agent/understand/README.md`](../../agent/understand/README.md), [`agent/understand/observation/README.md`](../../agent/understand/observation/README.md), [`slots/README.md`](../../agent/understand/observation/slots/README.md), [`agent/intent_router/README.md`](../../agent/intent_router/README.md). Pipeline context: [`agent_pipeline.md`](agent_pipeline.md).

Official kit tests and the published public-set numbers use **regex** observation (`understand_mode="regex"`). `Agent()` itself defaults to **nlu**. Kit tests mock the router LLM so they stay offline.

## What observe does

`observe` does not parse and does not commit constraints. It asks `hybrid_extract` for one frozen `ObservationExtract`, then stores it as `state.turn_delta`. The intention router commits after it classifies override.

```text
begin_turn
    observe
        hybrid_extract  → ObservationExtract   (no constraint writes)
        turn_delta      → extract, or None if empty
IntentRouter
    classify_override L1/L2 (independent Ollama client; no regex; skip if no prior intent)
    clear_typed+apply_delta, drop_typed+apply_delta, or apply_delta
    probe exact pool; maybe classify buying/browsing
```

The observation NLU prompt has no `track` key. Production hybrid has two sources only: the local model, or regex. Tests stub `agent.understand.observation.hybrid.extract_with_llm` with `unittest.mock.patch`. There is no extractor hook on `observe` or `Agent`.

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
3. If mode is `nlu`: [`ensure_llm_runtime()`](../../agent/understand/observation/runtime.py), `warmup_nlu()`, and `warmup_intent_router()`.

Runtime is best-effort and must not raise from `Agent.__init__`:

- GET `{host}/api/tags` with a short timeout.
- If down: prepend the usual Windows Ollama install dir to `PATH`, spawn `ollama serve` detached, wait until tags succeed (about 20s).
- POST `/api/generate` with `num_predict=1` so the configured model loads. **No `ollama pull`.**

If the daemon never comes up, later turns fail the extract three times and use regex. The router still has no regex fallback: three failed JSON extracts default to not-override and `browsing`.

Keyword `understand_mode="regex"` skips the env file and does not start Ollama. Kit tests do that and mock `classify_override` / `classify_route`.

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

One `extract_with_llm` call is one `inspect()`: casefold plus **parallel** color and material alias lookup, then up to two **word-class** chats (keep a pair only when both sides are color words or both are material words; the model does not score whether the dictionary bucket is correct). Identity pairs skip those chats. Surviving same-span hits concatenate `color material`. Then up to three **category-layer** chats on the **original** sentence: L1 lists every root; L2 concatenates children of all selected L1 nodes; L3 concatenates children of all selected L2 nodes (merchandising / promo shelves omitted). Each layer may return an empty id list (keep the broader parent). A pick is valid only when that branch is broader than or equal to the shopper's product (Shoes for running shoes; not Kids Shoes). Unstated audience words (kids, women, men, …) are dropped in code even if the model emits them. A selected node enters `delta` only when its label, slug, tag, or a content token from those strings is a span of the original message (`surface`). Then one **attribute** chat on the rewritten sentence, then up to three **span-repair** rounds on attributes ([`MAX_REPAIR_ROUNDS`](../../agent/understand/observation/slots/pipeline.py)). Repair is not a fourth outer retry. Regex observation does not rewrite and does not walk the tree.

Ollama options: `NUM_PREDICT=4096` for attributes, `NUM_PREDICT_CATEGORY=512` per layer, `NUM_PREDICT_ALIAS=256` for word-class gates, `NUM_CTX=8192`, `temperature=0`. If `done_reason=length`, `_complete` retries once at `NUM_PREDICT * 2`.

The HTTP client is [`llm_nlu.py`](../../agent/understand/observation/llm_nlu.py). It does not write session state. Category ids come from [`category_tree.json`](../../scripts/catalog_preprocess/aliases/category_tree.json) (promo leaves dropped at build and again at parse). Attribute JSON is `constraints` and `empty` only. Context is session category, locked constraint strings, and `last_ask` plus the **rewritten** message. `SessionState.latest_message` stays the original utterance.

Cited tree nodes keep `catalog_tags` as category slot `canonical` values (sidecar probe). Tags are `fold_category` keys. Uncited nodes are omitted from `delta`, including empty-tag leaves with no shopper span.

## After extract

Typed slots on the extract become `state.typed_constraints`, including optional category rows. Each slot has `is_hard` (must vs prefer; not a catalog fingerprint). Retrieve does **not** store flattened search pairs on session; [`retrieve/from_slots.py`](../../agent/retrieve/from_slots.py) builds **hard** groups for the exact pool and **soft** pairs for preferred scoring. Empty slots fall back to `active_constraints` strings (leftover hints are not hard).

Slot grounding (cite vs classify, size kinds, OR lists): [slots/README.md](../../agent/understand/observation/slots/README.md).

## Regex shapes (fallback and kit tests)

Same templates as before, in `classify.py` and `patterns.py`. They fill `turn_delta`. The router commits them (accumulate vs replace is an LLM decision, not these regexes):

| Shape | Extract |
| --- | --- |
| `I'm looking for X. A key requirement is: Y.` | hard category X, hard locked Y |
| `I'm looking for X, but I'm still exploring.` | hard category X only |
| `I'm looking for X. {rest}` | hard category X; rest is a leftover **soft** slot |
| `For that, what matters is: A; B.` | locked constraints (semicolon restore) |
| Override phrasing | hard new-need span as a constraint slot (router LLM still decides replace vs accumulate) |
| Empty / no preference | empty extract |

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
| `scripts/nlu_console.py` | Interactive shopper chatbot. With a catalog each turn is production `TurnPipeline` (understand → router → retrieve → rank → decide). Prints stage summaries plus the agent message and titled recommendations. `/raw` dumps JSON. `--no-retrieve` is extract + override writeback only. |
| `scripts/nlu_probe.py --live` | Fixture spans vs live model |

## Tests

- [`tests/test_agent.py`](../../tests/test_agent.py): `setUpModule` mocks the router LLM and pins `understand_mode="regex"`.
- [`tests/test_intent_router.py`](../../tests/test_intent_router.py): patches `classify_override` / `classify_route` / `probe_exact_pool`.
- [`tests/test_nlu.py`](../../tests/test_nlu.py): regex by default in hybrid tests; nlu tests `configure_understand("nlu")` and patch `hybrid.extract_with_llm`. Three `None` returns then regex. Agent nlu constructs with `ensure_llm_runtime` mocked. No live Ollama in CI.
- [`tests/test_category_nlu.py`](../../tests/test_category_nlu.py): committed tree, child→parent map, alias rewrite, mocked layered category HTTP.
- [`tests/test_nlu_console.py`](../../tests/test_nlu_console.py): patches console `classify_override` when retrieve is off; tiny-catalog tests exercise the full pipeline through the official reply.
- [`tests/test_pipeline_smoke.py`](../../tests/test_pipeline_smoke.py): one-turn `TurnPipeline` smoke (buying, browsing, miss exclusion, override, empty, turn 10, BM25 fallback, console chatbot print).
- [`tests/test_understand_router_smoke.py`](../../tests/test_understand_router_smoke.py): observe → `turn_delta` → override/writeback → sidecar probe → buying/browsing → retrieve scores the exact set. Offline tests script `/api/chat`. Live Ollama is opt-in: `AGENT_SMOKE_LIVE=1` (fails if `/api/tags` is down).

## Files

| Path | Role |
| --- | --- |
| `agent/understand/mode.py` | Resolve and pin mode |
| `agent/understand/observation/hybrid.py` | NLU attempts then regex |
| `agent/understand/observation/llm_nlu.py` | Rewrite, layered category chats, attribute chat, parse |
| `agent/understand/observation/rewrite.py` | Parallel color/material alias rewrite plus optional word-class gates |
| `agent/understand/observation/category_merch.py` | Promo / merchandising label detector |
| `agent/understand/observation/category_tree.py` | Committed 3-level category walk (promo children filtered) |
| `agent/understand/observation/runtime.py` | Daemon ping / spawn / model load |
| `agent/understand/observation/coordinator.py` | Store `turn_delta` |
| `agent/understand/observation/patterns.py` | Looking-for / leftover / override regex templates |
| `agent/understand/state/gate.py` | Conversion gate on override writeback |
| `agent/intent_router/` | Override vs accumulate, hard-only pool probes, intention |
| `agent/orchestrator.py` | Keyword, env load, runtime warmup |
