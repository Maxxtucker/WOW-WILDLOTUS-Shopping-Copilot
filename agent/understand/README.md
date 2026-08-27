# understand — turn user/simulator text into structured session state

## Purpose

`understand` is the first half of the turn loop: **read this turn's natural language, write `SessionState`**. Retrieval and planning never parse prose; they consume the fields produced here.

The evaluator has no explicit negative click. This layer also infers that the previous slate missed when the evaluator calls `respond` again.

## Submodules

Each subdirectory has its own README (purpose, collaboration, core variables, core code). Each `.py` file starts with Purpose / Input / Output.

| Package | Role | Docs |
|---|---|---|
| `state/` | Session memory. `SessionState` is the core object; miss feedback, turn clock, and override fail-safe live here. | [state/README.md](state/README.md) |
| `intention/` | Scenario routing: Buying / Browsing / Override-pending / Boundary. | [intention/README.md](intention/README.md) |
| `attributes/` | Extract constraints, no-preference, and semicolon restore. | [attributes/README.md](attributes/README.md) |
| `observation/` | **Fixed parse order.** Intention and attributes must not run independently; consume `what matters is` before override. | [observation/README.md](observation/README.md) |

## Collaboration

```text
StateDetector.begin_turn
    ├─ miss_feedback.apply   if gate open and turn>1 → last slate into excluded_asins
    ├─ write turn / latest_message / history
    ├─ ObservationCoordinator.observe
    │     ├─ turn 1: intention templates (buying / exploring / override_pending)
    │     ├─ attributes: no-pref / matters / colon fallback
    │     └─ intention: override phrasing
    └─ failsafe               override_pending and turn>=4 → force the gate open
```

`pipeline` calls only `StateDetector.apply`. `IntentionDetector` and `AttributeCapture` are invoked in order by the coordinator so catalog features containing `instead`/`forget` are not treated as intent resets.

## Core variables

On `SessionState` (`state/session.py`):

- `category`: coarse category phrase from turn 1
- `scenario_hint` / `gate_open` / `intent_version`: scenario and conversion gate
- `active_constraints` / `legacy_hints` / `ranking_constraints`: retrieval constraint views
- `disclosed` / `no_preference`: revealed values and attributes not to ask again
- `excluded_asins` / `last_slate` / `last_gate_open`: miss feedback
- `reply_value_lookup`: previous predicted reply → atomic constraints (semicolon restore)

## Core code

- Turn entry: `begin_turn` in `state/lifecycle.py`
- Parse order: `observe` in `observation/coordinator.py`
- Memory: `SessionState` in `state/session.py`
