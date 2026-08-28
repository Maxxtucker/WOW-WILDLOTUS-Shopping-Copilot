# understand/attributes — constraints and semicolon restore

## Purpose

Turn shopping evidence in simulator/user messages into structured constraints for retrieve. This is semantic capture, not prose understanding. Observation classify finds the strings; this package writes them and restores semicolon-containing values.

## Files

| File | Role |
|---|---|
| `parsers.py` | Regex for `what matters is`. |
| `lookup.py` | Previous predicted-reply surface form → atomic constraints (do not blindly split on semicolons). |
| `capture.py` | `add_constraint` into `active_constraints` / `disclosed`. |

## Collaboration

```text
observe → extract_constraints
            ├─ key requirement / what matters is
            └─ resolve_matters_pieces (lookup)
```

`reply_value_lookup` is written by the previous turn's `decide/response/writeback.set_reply_options`. This package only reads it.

## Core variables

- Regex: `MATTERS_RE`
- State: `active_constraints`, `disclosed`, `last_reply_informative`

## Core code

- Phrasing: `parsers.py`
- Semicolon restore: `build_reply_lookup` / `resolve_matters_pieces` in `lookup.py`
- Writes: `add_constraint` in `capture.py`
