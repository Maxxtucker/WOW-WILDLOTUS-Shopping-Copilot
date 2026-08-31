# understand/attributes — constraints and semicolon restore

## Purpose

Turn ordinary shopper evidence into cited constraint strings and restore compact
follow-up values that contain semicolons. Observation finds the strings and
stages them in `turn_delta`; Router writeback calls this package when it commits
an accumulation or replacement decision.

## Files

| File | Role |
|---|---|
| `parsers.py` | Regex for `what matters is`. |
| `lookup.py` | Previous predicted-reply surface form → atomic constraints (do not blindly split on semicolons). |
| `capture.py` | `add_constraint` into `active_constraints` / `disclosed`. |

## Collaboration

```text
observe
    extract_constraints
        ├─ key requirement / what matters is
        └─ resolve_matters_pieces (lookup)
    → turn_delta
Intent Router
    apply_delta
        └─ add_constraint → active_constraints / disclosed
```

`reply_value_lookup` is written by the previous turn's `decide/response/writeback.set_reply_options`. This package only reads it.

## Core variables

- Regex: `MATTERS_RE`
- State: `active_constraints`, `disclosed`, `last_reply_informative`

## Core code

- Phrasing: `parsers.py`
- Semicolon restore: `build_reply_lookup` / `resolve_matters_pieces` in `lookup.py`
- Writes: `add_constraint` in `capture.py`
