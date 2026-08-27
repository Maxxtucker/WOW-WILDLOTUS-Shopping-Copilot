# decide/ranking — retrieval scores → coarse posterior

## Purpose

Pipeline stage 6. Turn `SearchHit.score` into `RankedCandidate.probability` for the planner. Temperature 0.12 only spreads the popularity prior; it does not claim calibrated probabilities.

## Files

| File | Role |
|---|---|
| `belief.py` | `exp((s - max)/0.12)` unnormalized weights. |
| `normalize.py` | Normalize positive weights, sort by score, define `RankedCandidate`. |
| `__init__.py` | `Ranker.apply`: chain the two steps. |

## Collaboration

```text
Ranker.apply(hits)
    belief_from_hits → normalize_probabilities → RankedCandidate[]
Clarifier reads probability and parent_asin order only
```

## Core variables

- `BELIEF_TEMPERATURE = 0.12`
- `RankedCandidate`: `parent_asin`, raw `score` (weight), `probability`

## Core code

- `belief_from_hits` in `belief.py`
- `normalize_probabilities` in `normalize.py`
- `Ranker.apply` (this package's `__init__.py`)
