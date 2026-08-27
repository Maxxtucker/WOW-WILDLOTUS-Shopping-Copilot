# understand/observation — fixed parse order

## Purpose

The only place inside `understand` allowed to compose intention and attributes. Catalog features may legally contain `instead` / `forget`; consume `what matters is` before testing override.

`pipeline` **must not** call `IntentionDetector` and `AttributeCapture` separately.

## Files

| File | Role |
|---|---|
| `coordinator.py` | `ObservationCoordinator.apply` / `observe`: the fixed three-step order. |

## Collaboration

```text
turn 1: apply_turn1_template → stop on match
        else capture_turn1_generic_fallback
then:   capture_reply_attributes (including what matters is)
then:   apply_override_message
```

## Core variables

No independent state. Reads and writes the passed-in `SessionState`.

## Core code

`observe` in `coordinator.py`. The order is a correctness constraint, not style.
