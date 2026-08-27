# understand/observation — fixed parse order

## Purpose

The only place inside `understand` allowed to compose extractors. Catalog features may legally contain `instead` / `forget`; apply locked constraints before testing override.

`pipeline` calls `StateDetector.apply` only. It does not call extractors separately.

## Files

| File | Role |
|---|---|
| `classify.py` | `extract_category` / `extract_constraints` / `parse_override` (regex toy; no state writes). |
| `coordinator.py` | `observe`: apply hits in a fixed order every turn. |

## Collaboration

```text
every turn:
    extract_constraints → write active_constraints (and stop if any)
    extract_category    → category; leftover hint closes the conversion gate
    parse_override      → clear legacy, open gate
    colon_fallback      → last-resort constraint parse
```

There is no `if turn == 1` branch and no Buying / Browsing / Boundary label.

## Core variables

No independent state. Reads and writes the passed-in `SessionState`.

## Core code

`observe` in `coordinator.py`. The order is a correctness constraint, not style.
