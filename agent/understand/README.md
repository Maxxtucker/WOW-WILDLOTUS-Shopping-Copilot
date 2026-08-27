# understand — turn user/simulator text into structured session state

## Purpose

`understand` is the first half of the turn loop: **read this turn's text, write `SessionState`**. Retrieval and planning never parse prose; they consume the fields produced here.

Every user message is handled the same way: extract category, locked constraints, and override. Empty replies write nothing.

The evaluator has no explicit negative click. This layer also infers that the previous slate missed when the evaluator calls `respond` again.

## Submodules

Each subdirectory has its own README (purpose, collaboration, core variables, core code). Each `.py` file starts with Purpose / Input / Output.

| Package | Role | Docs |
|---|---|---|
| `state/` | Session memory. `SessionState` is the core object; miss feedback, turn clock, and override fail-safe live here. | [state/README.md](state/README.md) |
| `intention/` | Conversion-gate writeback when override fires. | [intention/README.md](intention/README.md) |
| `attributes/` | Constraint writes and semicolon restore. | [attributes/README.md](attributes/README.md) |
| `observation/` | **Fixed parse order.** Category / constraints / override extractors; constraints before override. | [observation/README.md](observation/README.md) |

## Collaboration

```text
StateDetector.begin_turn
    ├─ miss_feedback.apply   if gate open and turn>1 → last slate into excluded_asins
    ├─ write turn / latest_message / history
    ├─ observe
    │     ├─ extract_constraints (key requirement / what matters is)
    │     ├─ extract_category (looking-for / exploring / leftover hint)
    │     └─ parse_override
    └─ failsafe               gate still closed and turn>=4 → force the gate open
```

`pipeline` calls only `StateDetector.apply`. Catalog features containing `instead`/`forget` are not treated as intent resets because constraints are applied before override.

## Core variables

On `SessionState` (`state/session.py`):

- `category`: coarse category phrase
- `gate_open` / `intent_version`: conversion gate (closed until override when the first message had a leftover hint)
- `active_constraints` / `legacy_hints` / `ranking_constraints`: retrieval constraint views
- `disclosed`: values already revealed
- `excluded_asins` / `last_slate` / `last_gate_open`: miss feedback
- `reply_value_lookup`: previous predicted reply → atomic constraints (semicolon restore)

## Core code

- Turn entry: `begin_turn` in `state/lifecycle.py`
- Parse order: `observe` in `observation/coordinator.py`
- Extractors: `observation/classify.py`
- Memory: `SessionState` in `state/session.py`
