# intent_router — Intention Router between observe and retrieve

## Purpose

Observe only stores `turn_delta`. This package decides whether the turn **replaces** prior needs (override) or **accumulates** them, probes the exact candidate pool, labels `buying` / `browsing` / `override`, and hands the pool to retrieve. Override is two levels: L1 discards every committed category and attribute then `apply_delta`; L2 drops only the fields present on this turn's delta then `apply_delta`. Adding alternatives is not override.

Classification is a local Qwen JSON client. There is no regex intention fallback.

## Files

| File | Role |
|---|---|
| `llm.py` | Independent Ollama client. `classify_override` (L1/L2), `classify_route`. |
| `writeback.py` | `apply_delta` / L1 `clear_typed` / L2 `drop_typed`. Upsert slots by `(attribute, value)`. |
| `probe.py` | Pool counts. `None` is not count 0. |
| `exact_pool.py` | Hard signature intersection (group OR, groups AND), then hard budget / LWH / weight numeric filter. |
| `router.py` | `route_intention`: override LLM, then one of the two probe branches. |

## Collaboration

```text
observe → turn_delta
route_intention
    classify_override (L1, then keep only if this turn's category is distant;
                       else L2 replace-vs-add; skip both if no committed intent)
    if L1:
        clear_typed → apply_delta → open gate → probe once → intention=override
    else if L2:
        drop_typed(delta fields) → apply_delta → open gate → probe once → intention=override
    else:
        probe old state → apply_delta → probe new state
        classify_route(counts, ratio, dialogue) → buying|browsing
    failsafe if gate still closed at turn>=4
retrieve.organizer(state, exact)   # scores this set; does not re-intersect
```

Override never uses pool size. Buying vs browsing never runs after override. Hard intersection lives here (`exact_pool.py`), not in retrieve.

## Core variables

- `state.intention`: `buying` | `browsing` | `override`
- `candidate_count` / `previous_candidate_count` / `candidate_count_before_delta`
- Probe uses **hard** slots only; soft slots score later in retrieve
- `router_prompt_tokens` / `router_completion_tokens` (this turn)

[`tests/test_intent_router.py`](../../tests/test_intent_router.py) mocks `classify_override` and `classify_route`. They do not assert regex templates. [`tests/test_understand_router_smoke.py`](../../tests/test_understand_router_smoke.py) stitches observe into this router with a tiny sidecar: scripted HTTP in CI, live Ollama only when `AGENT_SMOKE_LIVE=1`.

## Core code

- Override vs accumulate: `route_intention` in `router.py`
- Hard intersection: `exact_pool_for_state` / `exact_pool_from_groups` in `exact_pool.py`
- Probe wrapper: `probe_exact_pool` in `probe.py`
