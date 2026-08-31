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

See `SessionState`: `category`, `intention`, `turn_delta`, `gate_open`, `intent_version`, `active_constraints` / `legacy_hints` / `ranking_constraints`, `typed_constraints`, `preference_tags`, `disclosed`, `excluded_asins` / `shown_asins` / `last_slate` / `last_gate_open`, `reply_value_lookup`, `disclosure_empty` / `empty_disclosure_reveal`, `current_intent_messages`, `candidate_count` / `previous_candidate_count` / `candidate_count_before_delta`, and `exact_strict` / `exact_lenient`.

`turn_delta` is the only normal Understand write for new shopping evidence. Router later commits it. Retrieve maps **hard** slots to exact/required groups and **soft** slots to preferred and text scoring in `retrieve/from_slots.py`; those derived pairs are not stored here.

The router writes `exact_strict` (all represented hard attributes must match) and `exact_lenient` (each hard attribute may match or be unknown, but a known mismatch still fails). `None` means the exact pool is unrepresentable; an empty set means it was represented and no product survived. Retrieve selects a non-empty lenient pool only when strict is represented and below the 150-candidate floor.

`preference_tags` is a reset-time copy of aggregate profile tags. Catalog scoring computes profile similarity for diagnostics but gives it zero final-score weight. The optional Qwen reranker can still receive these tags as explicitly weak context.

NLU slot shape and grounding rules: [../observation/slots/README.md](../observation/slots/README.md).

## Core code

- Memory: `SessionState` in `session.py`
- Turn entry: `begin_turn` in `lifecycle.py`
- Miss: `apply_miss_feedback` in `miss_feedback.py`
- Conversion gate: `open_conversion_gate` in `gate.py`
- Closed-gate timeout: `apply_override_failsafe` in `failsafe.py`
