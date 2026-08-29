# understand/state — session memory and turn clock

## Purpose

This package is the memory hub of `understand`. All mutable fields for one session live on `SessionState`. The evaluator has no negative click, so a miss is inferred only when the next `respond` arrives.

Observe writes `turn_delta`. The intention router commits constraints and `intention`. Fail-safe runs after that writeback.

## Files

| File | Role |
|---|---|
| `session.py` | `SessionState` dataclass: constraints, exclusions, conversion gate, reply inverse map, intention, pool counts. |
| `gate.py` | `open_conversion_gate` after override writeback. |
| `lifecycle.py` | `StateDetector` / `begin_turn`: pipeline stage 1 entry (observe only). |
| `miss_feedback.py` | Gate open and turn>1 → merge last slate into `excluded_asins`. |
| `failsafe.py` | Gate still closed at turn≥4 → open the gate. Does not label override. |

## Collaboration

```text
pipeline → StateDetector.apply
              begin_turn
                ├─ apply_miss_feedback
                ├─ write turn / latest_message / history
                ├─ clear turn_delta / router tokens
                └─ observe(...)          # turn_delta only
           IntentRouter.apply
                └─ apply_override_failsafe after writeback
```

`session.py` does not parse sentences. `record_action` lives in `decide/response/writeback.py` so state does not depend on planning results.

## Core variables

See `SessionState`: `category`, `intention`, `turn_delta`, `gate_open`, `intent_version`, `active_constraints` / `legacy_hints` / `ranking_constraints`, `typed_constraints`, `preference_tags`, `disclosed`, `excluded_asins` / `last_slate` / `last_gate_open`, `reply_value_lookup`, `candidate_count` / `previous_candidate_count` / `candidate_count_before_delta`. `preference_tags` is a reset-time copy of the aggregate profile tags; semantic ranking uses it only as a weak tie-breaker. Retrieve maps **hard** slots to the exact pool and **soft** slots to preferred scoring in `retrieve/from_slots.py`; those pairs are not stored here.

NLU slot shape and grounding rules: [../observation/slots/README.md](../observation/slots/README.md).

## Core code

- Memory: `SessionState` in `session.py`
- Turn entry: `begin_turn` in `lifecycle.py`
- Miss: `apply_miss_feedback` in `miss_feedback.py`
- Conversion gate: `open_conversion_gate` in `gate.py`
- Closed-gate timeout: `apply_override_failsafe` in `failsafe.py`
