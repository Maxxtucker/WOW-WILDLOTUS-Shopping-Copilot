# decide/clarification — question selection and slate

## Purpose

Pipeline stage 7. Joint search over “which `ask_attribute` to ask” and “how many products to show”. The objective is one-step expected TechnicalScore, not entropy. Then sequential slate risk gating (usually keep rank-1).

The simulator reads only structured `ask_attribute`. It does not infer the question from `message`.

## Files

| File | Role |
|---|---|
| `types.py` | `Plan`, sentinel `NO_ADDITIONAL`. |
| `utility.py` | `hit_utility(turn, rank) = 0.50 + 0.30/rank + 0.02*(11-turn)`. |
| `questions.py` | Still-informative attributes; `explain_question` templates. |
| `replies.py` | Cache `predict_reply` for planner counterfactuals. |
| `distinguish.py` | Partition by predicted reply; estimate next-turn Top-10 utility. |
| `planner.py` | `ScoreAwarePlanner.plan`: one-step search over question × slate prefix. |
| `slate.py` | Sequential gate after planning. |
| `stage.py` | `Clarifier`: stage entry for plan + gate. |

## Collaboration

```text
Clarifier.apply
    make_answer_signature(retriever, disclosed)
    ScoreAwarePlanner.plan(state, ranked, top_k, answer_signature)
        eligible_questions × k∈[0, top_k]
            immediate-hit utility + future_value(partitions)
    apply_sequential_gate → usually rank-1; turn 10 is full slate and no question
```

The planner asks catalog how an ASIN would answer via a callback. It does not touch SQLite.

## Core variables

- `Plan`: `recommendations`, `ask_attribute`, `expected_value`, `reason`
- `NO_ADDITIONAL`: simulator will not disclose more on that attribute
- `max_planning_candidates = 500`

## Core code

- Entry: `Clarifier.apply` in `stage.py`
- Search: `ScoreAwarePlanner.plan` in `planner.py`
- Distinguishability: `future_value` in `distinguish.py`
- Gate: `apply_sequential_gate` in `slate.py`
