# understand/state — session memory and turn clock

## Purpose

This package is the memory hub of `understand`. All mutable fields for one session live on `SessionState`. The evaluator has no negative click, so a miss is inferred only when the next `respond` arrives.

## Files

| File | Role |
|---|---|
| `session.py` | `SessionState` dataclass: constraints, scenario, exclusions, conversion gate, reply inverse map. |
| `lifecycle.py` | `StateDetector` / `begin_turn`: pipeline stage 1 entry. |
| `miss_feedback.py` | Gate open and turn>1 → merge last slate into `excluded_asins`. |
| `failsafe.py` | `override_pending` stuck through turn≥4 → force the gate open. |

## Collaboration

```text
pipeline → StateDetector.apply
              begin_turn
                ├─ apply_miss_feedback
                ├─ write turn / latest_message / history
                ├─ observe(...)          # handed to observation/
                └─ apply_override_failsafe
```

`session.py` does not parse sentences. `record_action` lives in `decide/response/writeback.py` so state does not depend on planning results.

## Core variables

See `SessionState`: `category`, `scenario_hint`, `gate_open`, `intent_version`, `active_constraints` / `legacy_hints` / `ranking_constraints`, `disclosed` / `no_preference`, `excluded_asins` / `last_slate` / `last_gate_open`, `reply_value_lookup`.

## Core code

- Memory: `SessionState` in `session.py`
- Turn entry: `begin_turn` in `lifecycle.py`
- Miss: `apply_miss_feedback` in `miss_feedback.py`
- Closed-gate timeout: `apply_override_failsafe` in `failsafe.py`
