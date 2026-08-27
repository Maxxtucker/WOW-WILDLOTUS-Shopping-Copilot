# understand/attributes — constraints and no-preference

## Purpose

Turn shopping evidence in simulator/user messages into structured constraints for retrieve (hard/soft filters) and clarification (which attributes not to ask). This is semantic capture, not prose understanding.

## Files

| File | Role |
|---|---|
| `parsers.py` | Regexes for `what matters is` / no preference / no additional. |
| `lookup.py` | Previous predicted-reply surface form → atomic constraints (do not blindly split on semicolons). |
| `capture.py` | Write Match results into `active_constraints` / `disclosed` / `no_preference`. |

## Collaboration

```text
observe → capture_reply_attributes
            ├─ no additional / no preference
            ├─ what matters is → resolve_matters_pieces (lookup)
            └─ colon fallback (turn 1 when no template matched)
```

`reply_value_lookup` is written by the previous turn's `decide/response/writeback.set_reply_options`. This package only reads it.

## Core variables

- Regexes: `MATTERS_RE`, `NO_PREFERENCE_RE`, `NO_ADDITIONAL_RE`
- State: `active_constraints`, `disclosed`, `no_preference`, `boundary_seen`, `last_reply_informative`

## Core code

- Phrasing: `parsers.py`
- Semicolon restore: `build_reply_lookup` / `resolve_matters_pieces` in `lookup.py`
- Writes: `capture_reply_attributes`, `add_constraint` in `capture.py`
