# decide — rank, pick a question, write the protocol response

## Purpose

`decide` takes `SearchHit`s and returns the evaluator dict: `message`, `ask_attribute`, `recommendations`. The objective is one-step expected TechnicalScore (hit early, preferably rank-1), not raw information entropy.

## Submodules

Each subdirectory has its own README. Each `.py` file starts with Purpose / Input / Output.

| Package | Role | Docs |
|---|---|---|
| `ranking/` | Retrieval scores → temperature-0.12 coarse posterior `RankedCandidate`. | [ranking/README.md](ranking/README.md) |
| `clarification/` | Joint search over “which attribute to ask” and “how many products to show”; then sequential slate gating. | [clarification/README.md](clarification/README.md) |
| `response/` | Write back `reply_value_lookup` / `last_slate` and assemble the official response. | [response/README.md](response/README.md) |

## Collaboration

```text
Ranker.apply(hits, state)
    optional semantic head, else belief_from_hits → RankedCandidate[]

Clarifier.apply(state, ranked, top_k)
    ├─ predict_reply partitions → ScoreAwarePlanner.plan → Plan
    └─ apply_sequential_gate → usually keep rank-1 (full Top-K on turn 10 or empty disclosure)

ResponseBuilder.apply(state, retriever, candidate_asins, plan, slate)
    ├─ persist_turn: set_reply_options + record_action
    └─ build_response: message + ask_attribute + recommendations
```

The planner asks catalog “how would this product answer?” via `answer_signature(asin, attribute)`. It does not touch SQLite.

## Core variables

- `RankedCandidate`: `parent_asin`, raw weight, `probability`
- `Plan`: `recommendations`, `ask_attribute`, `expected_value`, `reason`
- `NO_ADDITIONAL`: partition sentinel when the simulator will not disclose more
- `hit_utility(turn, rank) = 0.50 + 0.30/rank + 0.02*(11-turn)`

## Core code

- Posterior: `ranking/belief.py`, `ranking/normalize.py`
- Question choice: `ScoreAwarePlanner.plan` in `clarification/planner.py`
- Distinguishability: `future_value` in `clarification/distinguish.py`
- Slate gate: `apply_sequential_gate` in `clarification/slate.py`
- Protocol assemble: `build_response` in `response/builder.py`
