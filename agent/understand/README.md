# understand — extract this turn, then the intention router commits state

## Purpose

`understand` is the first half of the turn loop: **read this turn's text into `turn_delta`**. Retrieval and planning never parse prose. The **intention router** (not this layer) commits constraints, the conversion gate, and `buying` / `browsing` / `override`.

Every user message is handled the same way: extract category, locked constraints, leftover hints, and optional override spans into `ObservationExtract`. Empty replies leave `turn_delta` empty.

The evaluator has no explicit negative click. This layer also infers that the previous slate missed when the evaluator calls `respond` again.

## Submodules

Each subdirectory has its own README (purpose, collaboration, core variables, core code). Each `.py` file starts with Purpose / Input / Output.

`mode.py` pins process-wide `understand_mode`: nlu (default) or regex. Full note: [`docs/architecture/understand_nlu.md`](../../docs/architecture/understand_nlu.md).

| Package | Role | Docs |
|---|---|---|
| `state/` | Session memory. `SessionState` is the core object; miss feedback, conversion gate, and turn clock live here. Fail-safe runs after the router. | [state/README.md](state/README.md) |
| `attributes/` | Constraint writes and semicolon restore. | [attributes/README.md](attributes/README.md) |
| `observation/` | Hybrid extract into `turn_delta` only. Regex kit path is extract, not intention routing. | [observation/README.md](observation/README.md) |

## Collaboration

```text
StateDetector.begin_turn
    ├─ miss_feedback.apply   if gate open and turn>1 → last slate into excluded_asins
    ├─ write turn / latest_message / history
    ├─ clear turn_delta / router token counters
    └─ observe
          hybrid extract (nlu: up to 3 attempts, then regex)
          colon fallback on regex extracts with no constraints
          write turn_delta only

IntentRouter.apply   (agent/intent_router, after understand)
    classify override (independent LLM; no regex; true only for a product/category switch or explicit reset)
    replace or accumulate, probe exact pool, label intention
    failsafe: gate still closed and turn>=4 → open the gate only
```

`pipeline` calls `StateDetector.apply` then `IntentRouter.apply`. Catalog features containing `instead`/`forget` are not treated as intent resets: the override LLM is instructed to ignore product-copy phrasing, and tests mock that decision.

## Mode

`understand_mode` is process-wide (`mode.py`). Default is `nlu`.

1. `Agent(..., understand_mode=)` / `configure_understand`
2. `AGENT_UNDERSTAND_MODE`
3. `AGENT_NLU_ENABLED` in `{0, false, off}` → `regex`
4. otherwise `nlu`

Nlu startup, three extract retries, span repair vs outer retry, and scripts: [`docs/architecture/understand_nlu.md`](../../docs/architecture/understand_nlu.md).

## Core variables

On `SessionState` (`state/session.py`):

- `category`: primary category phrase (first hard category slot, else first category slot)
- `intention`: `buying` / `browsing` / `override` from the intention router (not evaluator scenario labels)
- `turn_delta`: this turn's extract; observe writes it, the router consumes it
- `gate_open` / `intent_version`: conversion gate (closed until override when the first message had a leftover hint)
- `active_constraints` / `legacy_hints` / `ranking_constraints`: cited-string views for the regex / kit path only (leftover is not an exact-pool prune). NLU retrieve and `nlu_console` `/state` use `typed_constraints`.
- `typed_constraints`: `ConstraintSlot` rows including optional category. Each row has `is_hard`. Design: [observation/slots/README.md](observation/slots/README.md)
- `preference_tags`: reset-time copy of aggregate `user_profile` tags; semantic ranking uses them only as weak tie-breakers
- `disclosed`: values already revealed
- `excluded_asins` / `last_slate` / `last_gate_open`: miss feedback
- `reply_value_lookup`: previous predicted reply → atomic constraints (semicolon restore)
- `candidate_count` / `previous_candidate_count` / `candidate_count_before_delta`: exact-pool sizes for the router

## Core code

- Turn entry: `begin_turn` in `state/lifecycle.py`
- Extract only: `observe` in `observation/coordinator.py`
- Extractors: `observation/classify.py` (regex) and `observation/hybrid.py`
- Regex templates: `observation/patterns.py`
- Conversion gate: `open_conversion_gate` in `state/gate.py`
- Commit: `agent/intent_router`
- Mode: `configure_understand` in `mode.py`
- NLU design: [`docs/architecture/understand_nlu.md`](../../docs/architecture/understand_nlu.md)
- Memory: `SessionState` in `state/session.py`
