# retrieve/filtering — exact signature intersection

## Purpose

Pipeline stage 4. Buying main path: `category ∩ each constraint's response signature`. If any signal has no exact hit in the index → return `None` so candidates use BM25. **Never empty-intersect**: an empty set can kill the target.

## Files

| File | Role |
|---|---|
| `exact_pool.py` | `ProductFilter.apply` / `exact_pool` / `exact_pool_for_state`. |

## Collaboration

```text
pipeline
    exact = ProductFilter.apply(state)
    hits  = CandidateOrganizer.apply(state, exact)
```

Regex path: `classify_constraint` from `agent.domain` plus `response_only=True` so only simulator-disclose strings are used. NLU path: slot `attribute` + search values, with search aliases. Several canonicals on one slot are a **union** (OR); groups AND with each other.

## Core variables

- `exact: set[str] | None`: a set is scored; `None` means lexical fallback is required
- Input: `state.category`, `from_slots.exact_pool_groups(state)`

## Core code

`exact_pool_for_state` in `exact_pool.py`: `signature_candidates` per signal; missing any → `return None`; otherwise `set.intersection`.
