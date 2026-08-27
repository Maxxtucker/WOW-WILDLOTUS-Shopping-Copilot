# understand/intention — scenario routing

## Purpose

Recognize Buying / Browsing / Override / Boundary and write the conversion gate and intent version. **Does not** extract `what matters is` constraints (that is `attributes/`).

When a turn-1 official template matches, observation ends for this turn so the product phrase inside the template is not parsed as a later reply.

## Files

| File | Role |
|---|---|
| `parsers.py` | Official phrasing and override regexes; returns Match only, no state writes. |
| `detector.py` | Writes `scenario_hint` / `gate_open` / `legacy_hints` / the first constraint from a Match. |

## Collaboration

```text
observation.observe
    turn==1 → apply_turn1_template        # return on match
    … attributes parse what matters is first …
    then    → apply_override_message      # instead/forget inside catalog text already consumed
```

`failsafe` calls `apply_override` when turn≥4 is still `override_pending`. It does not re-run regexes.

## Core variables

- Regexes: `KEY_REQUIREMENT_RE`, `EXPLORING_RE`, `INITIAL_OTHER_RE`, `OVERRIDE_RE`
- State: `scenario_hint`, `gate_open`, `intent_version`, `legacy_hints`, `override_seen`

## Core code

- Templates: `parsers.py`
- Writes: `apply_turn1_template`, `apply_override` in `detector.py`
