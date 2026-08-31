# decide/response — writeback and official dict

## Purpose

Pipeline stage 8 writes this turn's slate and question into `SessionState`, then assembles the required `respond` shape. `usage` includes all prompt and completion tokens accumulated by the Intent Router on the current turn. Understand-model tokens are not currently counted.

## Files

| File | Role |
|---|---|
| `writeback.py` | `set_reply_options`, `record_action`, `persist_turn`. |
| `builder.py` | `build_response` / `build_message`; `ResponseBuilder.apply`. |

## Collaboration

```text
ResponseBuilder.apply(state, retriever, candidate_asins, plan, slate)
    if turn < 10 and ask_attribute is None:
        inject recovery_question
    persist_turn
        set_reply_options  → reply_value_lookup (next-turn semicolon restore)
        record_action      → last_slate / last_gate_open / last_ask / asked
                           → shown_asins and excluded_asins
    build_response
        message + ask_attribute + recommendations
        usage = router_prompt_tokens + router_completion_tokens by field
```

Next turn's `miss_feedback` reads `last_slate` and `last_gate_open` written here.

## Core variables

- Writeback: `last_slate`, `last_gate_open`, `last_ask`, `asked`, `shown_asins`, `excluded_asins`, `reply_value_lookup`
- External: `message`, `ask_attribute`, `recommendations`, `usage`
- Usage source: per-turn `router_prompt_tokens` and `router_completion_tokens`

`persist_turn()` predicts reply options from the complete retrieved candidate-ASIN list, not only the displayed slate. A null question clears that lookup. `record_action()` immediately adds every displayed ASIN to both shown and excluded sets; the next-turn conditional miss union is therefore idempotent in the current implementation.

Turn 10 may return `ask_attribute=None`. Before turn 10, both `Clarifier` and `ResponseBuilder` guard against a null question by selecting a recovery attribute.

## Core code

- Writeback: `writeback.py`
- Assemble: `build_response` in `builder.py`
