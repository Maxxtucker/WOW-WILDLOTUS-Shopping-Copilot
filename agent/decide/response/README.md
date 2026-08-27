# decide/response — writeback and official dict

## Purpose

Pipeline stage 8. Write this turn's slate / question into `SessionState`, then assemble the evaluator `respond` shape. `usage` is always 0 (no LLM).

## Files

| File | Role |
|---|---|
| `writeback.py` | `set_reply_options`, `record_action`, `persist_turn`. |
| `builder.py` | `build_response` / `build_message`; `ResponseBuilder.apply`. |

## Collaboration

```text
ResponseBuilder.apply
    persist_turn
        set_reply_options  → reply_value_lookup (next-turn semicolon restore)
        record_action      → last_slate / last_ask / asked
    build_response → {message, ask_attribute, recommendations, usage: 0}
```

Next turn's `miss_feedback` reads `last_slate` and `last_gate_open` written here.

## Core variables

- Writeback: `last_slate`, `last_gate_open`, `last_ask`, `asked`, `shown_asins`, `reply_value_lookup`
- External: `message`, `ask_attribute`, `recommendations`, `usage`

## Core code

- Writeback: `writeback.py`
- Assemble: `build_response` in `builder.py`
