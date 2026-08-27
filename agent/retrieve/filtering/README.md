# retrieve/filtering — exact signature intersection

## Purpose

Pipeline stage 4. Buying main path: `category ∩ each constraint's response signature`. If any signal has no exact hit in the index → return `None` so candidates use BM25. **Never empty-intersect**: an empty set can kill the target.

## Files

| File | Role |
|---|---|
| `exact_pool.py` | `ProductFilter.apply` / `exact_pool`. |

## Collaboration

```text
pipeline
    exact = ProductFilter.apply(state)
    hits  = CandidateOrganizer.apply(state, exact)
```

`classify_constraint` comes from `agent.domain`. The exact path uses `response_only=True` so only strings the simulator can actually disclose are used.

## Core variables

- `exact: set[str] | None`: a set is scored; `None` means lexical fallback is required
- Input: `state.category`, `state.ranking_constraints`

## Core code

`exact_pool` in `exact_pool.py`: `signature_candidates` per signal; missing any → `return None`; otherwise `set.intersection`.
