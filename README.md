# Converge — Score-Aware Conversational Product Search

Converge is an offline shopping copilot for TikTok TechJam 2026 Track 4. It
tracks the active shopping intent, predicts how each candidate product would
answer a clarification question, and jointly controls the recommendation slate
and next question to find the hidden product early and at rank one.

The system uses only Python's standard library. It requires no LLM API, API
key, network connection during evaluation, model download, or paid service.

## Public result

Run against the unmodified official evaluator and 200-session public set at
official repository commit `9a35be51780ff1caf89eceaabca34259e946f40f`:

| Metric | Official starter | Converge |
|---|---:|---:|
| Hit Rate@10 | 0.125000 | **1.000000** |
| MRR | 0.068034 | **1.000000** |
| MTTC | 9.810000 | **2.060000** |
| Efficiency | 0.119000 | **0.894000** |
| Recommended TechnicalScore | 0.106710 | **0.978800** |

All four public scenario groups—Buying, Browsing, Intent Override, and
Boundary—reach 100% Hit Rate and 1.0 MRR. This is a development-set result, not
a claim about the private leaderboard. Aggregate output is recorded in
[`docs/converge_public_results.json`](docs/converge_public_results.json).

## Why dynamic slates matter

For a first hit at turn `t` and rank `r`, one session contributes:

```text
U(t, r) = 0.50 + 0.30 / r + 0.02 × (11 - t)
```

Turn 1 / Rank 10 is worth `0.73`, while Turn 2 / Rank 1 is worth `0.98`.
Returning ten uncertain products on every turn can therefore lower the score.
Converge exposes the highest-confidence item while informative evidence is
still arriving, uses a miss as free censoring feedback, and lets the planner
expand coverage when evidence is exhausted; turn 10 is always a full Top-10.

## Architecture

```text
user message
   │
   ▼
intent-version state machine ── handles Buying / Browsing / Override / Boundary
   │
   ▼
structured active constraints ── required / no-preference / superseded / shown
   │
   ├── exact category + response-signature index
   └── field-aware SQLite FTS5 BM25 fallback
   │
   ▼
ranked candidate belief + no-hit exclusions
   │
   ▼
counterfactual reply partitions for each ask_attribute
   │
   ▼
score-aware question + dynamic-slate planner
   │
   ▼
official Agent response: message + ask_attribute + ranked parent_asin values
```

The protocol-aware path precomputes the deterministic intent-card fingerprint
for every one of the 50,000 catalog products. The robust path uses normalized
structured matching and field-weighted BM25 when a message is paraphrased or an
exact value is unavailable. The agent never reads `public_set.jsonl` or any
ground-truth label.

## Repository layout

```text
converge/
  agent.py       official Agent implementation and orchestration
  domain.py      evaluator-compatible card/category helpers
  planner.py     expected-score question and slate planning
  retrieval.py   response signatures, structured scoring, SQLite FTS5
  state.py       session isolation, no-hit feedback, override/boundary state
starter/
  agent.py       thin official entry-point wrapper
scripts/
  download_catalog.py   download and verify the frozen catalog
  check_parity.py       compare all 50k signatures with official helpers
  demo_session.py       print one complete public demonstration session
tests/
  test_converge.py      state, planner, retrieval, parity, and contract tests
evaluator/              unchanged official evaluator
data/public_set.jsonl   unchanged official public development set
```

## Setup

Python 3.10 or later with SQLite FTS5 is required. No `pip install` step is
needed.

```bash
cd converge-shopping-copilot
python3 scripts/download_catalog.py
python3 -m unittest discover -v
python3 scripts/check_parity.py
python3 -m evaluator.local_evaluator
```

The download script verifies the organizer-published SHA-256 digest before
decompressing `data/catalog.jsonl`. The catalog is intentionally gitignored.

### Index cache

By default the agent builds a disposable SQLite cache in the operating system's
temporary directory. This keeps the full-text/signature index off the Python
heap and allows later local runs to reuse it. To select an explicit location:

```bash
mkdir -p .cache
CONVERGE_INDEX_PATH=.cache/converge.sqlite3 \
  python3 -m evaluator.local_evaluator
```

The cache is automatically invalidated when the catalog path, size, timestamp,
or index version changes. Do not commit the generated database.

To force a process-local in-memory index instead, set
`CONVERGE_INDEX_PATH=:memory:`. This avoids disk writes but requires materially
more memory and rebuilds the index on every process start.

## Demo

```bash
python3 scripts/demo_session.py --sample public_0002
```

The default is a four-turn Intent Override example. It prints each simulated
customer message, the structured attribute asked, the recommendation slate,
and the first-hit turn/rank, making it suitable for a backend walkthrough
video.

## Implementation highlights

- Exact compatibility with the official `intent_card`, `coarse_category`, and
  `classify_constraint` behavior, covered by parity tests.
- Candidate-conditioned response signatures for every allowed question.
- One-step expected TechnicalScore planner over question choices and slate
  prefixes, plus a conservative sequential-slate risk guard.
- Correct miss handling: a new call proves the previous slate missed only when
  the Intent Override conversion gate was open.
- Explicit intent versions: an override removes the superseded preference,
  resets old negative evidence, and enables conversion on the same turn.
- Boundary replies are treated as uninformative observations, not as product
  exclusions; `other` remains available after the one-time boundary response.
- Missing-friendly price handling and soft store/brand matching because catalog
  metadata is sparse and `store` is not guaranteed to be a brand.
- Deterministic output, zero reported model tokens, and no network dependency at
  scoring time.

See [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) for the state machine,
planning equation, retrieval design, tests, limitations, and private-set
robustness strategy.

## Cost and feasibility

- External model/API cost: **$0**
- Reported prompt/completion tokens: **0 / 0**
- Runtime dependency: Python standard library only
- Evaluation network requirement: none
- Public 200-session warm-cache runtime observed locally: approximately 7 s;
  a cold run additionally spends about 32 s building a roughly 214 MiB index.
  Hardware, filesystem performance, and cache format change these figures.

## Limitations

- The strongest retrieval path models the released deterministic simulator. A
  different private intent-card generator would rely more heavily on BM25 and
  reduce performance.
- The public set is small and shares one scenario policy, so its score must not
  be treated as an unbiased private-set estimate.
- The current belief transform is deliberately low-capacity rather than a fully
  calibrated probabilistic model.
- A persistent SQLite cache is large; it is a development optimization and is
  not included in the submission.
- No neural semantic reranker is bundled. This keeps the agent offline and
  reproducible, but limits handling of highly subjective paraphrases.

## Team contributions

Before submission, replace this section with each participant's name and
contribution. Suggested categories are retrieval/indexing, dialog state and
planner, evaluation/experiments, and demo/presentation.

## Data attribution

The frozen catalog and sessions are derived from Amazon Reviews 2023 by
McAuley Lab, UCSD. See [`DATA_ATTRIBUTION.md`](DATA_ATTRIBUTION.md). Do not
commit the catalog, private evaluation data, credentials, or generated indexes.
