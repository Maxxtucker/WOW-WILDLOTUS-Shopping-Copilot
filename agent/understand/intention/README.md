# understand/intention — conversion gate on override

## Purpose

Open the conversion gate and drop superseded leftover hints when the user replaces an earlier preference. **Does not** extract `what matters is` constraints (that is `attributes/` + `observation/classify`).

## Files

| File | Role |
|---|---|
| `parsers.py` | Official looking-for and override regexes; returns Match only, no state writes. |
| `detector.py` | `apply_override`: gate, `intent_version`, clear `legacy_hints` / exclusions. |

## Collaboration

```text
observation.observe
    extract_constraints first
    then parse_override → apply_override
```

`failsafe` calls `apply_override` when the gate is still closed at turn≥4. It does not re-run regexes.

## Core variables

- Regexes: `KEY_REQUIREMENT_RE`, `EXPLORING_RE`, `INITIAL_OTHER_RE`, `OVERRIDE_RE`
- State: `gate_open`, `intent_version`, `legacy_hints`, `override_seen`

## Core code

- Templates: `parsers.py`
- Writes: `apply_override` in `detector.py`
