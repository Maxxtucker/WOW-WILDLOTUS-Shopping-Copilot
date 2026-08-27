# Converge implementation report

## 1. Objective and constraints

Converge implements the official `Agent.reset()` and `Agent.respond()`
interface without modifying the catalog, evaluator, or public labels. The core
runtime uses no network service and no generative model. All output is
deterministic for a fixed catalog and message sequence.

The official technical composite can be decomposed into the terminal utility
of a single session. If the first valid hit occurs at turn `t` and rank `r`:

```text
U(t, r) = 0.50 + 0.30 / r + 0.02 × (11 - t)
```

A miss has utility zero. This decomposition drives both the planner and the
conservative slate policy.

## 2. State model

Each `session_id` owns an isolated `SessionState` with:

- target-derived coarse category text;
- scenario hint and conversion-gate state;
- intent version;
- active constraints and superseded legacy hints;
- normalized values already disclosed by the customer;
- attributes with no additional preference;
- previous slate and whether it was scored under an open gate;
- ASINs excluded by observed misses;
- question and reply history.

### Miss feedback

The evaluator does not send an explicit negative click. Instead, a call to
`respond()` at turn `t + 1` proves that the prior scored slate did not contain
the target. Converge therefore excludes the previous slate at the start of the
new turn, but only if `last_gate_open` was true.

### Intent Override

Before the override message, the conversion gate is closed, so a displayed
target does not end the session and cannot be excluded on the next call. On the
override message, Converge:

1. increments `intent_version`;
2. clears the superseded initial preference;
3. clears stale negative evidence;
4. adds the replacement requirement;
5. enables conversion before ranking the current turn.

Constraints explicitly revealed by the simulator's structured replies are
preserved because they describe the target's effective intent card.

### Boundary

The first non-null Boundary answer is treated as an uninformative observation.
It does not remove products that happen to have a value for the requested
attribute. In particular, a one-time no-preference answer to `other` does not
disable a later `other` question; subsequent requests can reveal constraints.

## 3. Catalog and retrieval

`CatalogRetriever` builds a standard-library SQLite index with two cooperating
routes. By default the database lives in the OS temporary directory rather than
the SQLite in-memory backend, reducing evaluator heap pressure. Raw product and
signature JSON are compressed, and long raw constraint strings are not repeated
inside every signature-index alias row.

### Protocol-aware route

For each product, the index precomputes:

- the exact evaluator-compatible coarse category;
- the first two hard and next two soft constraints;
- the official constraint attribute classification;
- the counterfactual reply for every `ask_attribute`;
- normalized exact mappings from category/constraint to `parent_asin`.

When every observed value has an exact mapping, Converge intersects these sets.
Full normalized response strings are preserved: `Leather sole` must not collapse
to the generic alias `leather` in the exact route.

### Robust fallback

If category or constraint wording cannot be mapped exactly, Converge switches
to:

- SQLite FTS5 BM25 over title, category, features, details, store, and
  description;
- normalized substring/token similarity for structured values;
- soft category, profile-tag, rating, and popularity signals;
- missing-friendly price scoring;
- hard exclusion only for products proven absent by a scored miss.

The starter field weights are retained as a stable lexical baseline:

```text
title 6.0, categories 4.0, features 2.5, details 2.5,
store 1.5, description 1.0
```

## 4. Candidate belief and reply model

Retrieval scores are converted to positive head weights using a conservative
temperature transform. The code intentionally calls this a belief transform,
not a fully calibrated posterior.

For a candidate `d`, question `a`, and values disclosed so far, the response
model returns:

```text
z(d, a) = first two undisclosed card constraints classified as a
```

For `other`, classification is ignored and the next two undisclosed constraints
are returned in card order. Candidates with no value enter a dedicated
`NO_ADDITIONAL` partition.

## 5. Joint question/slate planner

For every viable attribute and every ranked prefix size `k = 0..10`, the
one-step planner estimates:

```text
Q(S, a)
  = Σ[d in S] p(d) U(current_turn, rank(d))
  + Σ[reply partition z] next-turn Top10 utility(z, target not in S)
```

Questions with no predicted coverage, repeated typed questions, and attributes
already marked no-preference are removed. `other` may repeat because each call
can reveal the next pair of constraints.

For ablation experiments, the planner also supports a `static` policy. It asks
the first eligible attribute in a configured complete priority sequence rather
than comparing expected utilities. The production default remains `dynamic`;
the static option exists to quantify whether a fixed ordering generalizes on
fresh synthetic draws.

The planner only expands the top 500 candidates. Retrieval keeps a wider path
for recall. On turn 10, future value is zero, so the response is the full
posterior Top-10 and `ask_attribute=None`.

### Sequential-slate risk guard

The public reward places much more value on rank one than on a low-ranked hit.
While an informative answer is pending, Converge exposes only the highest-
confidence product from a proposed multi-item slate. A continued session then
proves that item was wrong and promotes the next hypothesis. When evidence is
exhausted, singleton probing continues only if the remaining turns plus final
Top-10 can still cover the complete candidate set; otherwise the planner's
wider slate is preserved. The final turn always expands to ten.

This guard is why the public result obtains MRR 1.0 rather than terminating on
an uncertain rank-2-to-rank-10 item.

## 6. Scenario behavior

| Scenario | Initial state | Main policy |
|---|---|---|
| Buying | category + first hard constraint, gate open | rank immediately; request the strongest remaining evidence |
| Browsing | category only, gate open | one high-confidence item plus active clarification |
| Boundary | indistinguishable from Browsing initially | treat the first no-preference answer as uninformative, then continue |
| Intent Override | category + legacy hint, gate closed | gather evidence without negative-censoring; reset legacy intent and rank when gate opens |

## 7. Reproducibility and tests

Run:

```bash
python3 -m unittest discover -v
python3 -m evaluator.local_evaluator
```

The added tests cover:

- official intent-card parity;
- exact response-string lookup;
- open-gate and closed-gate miss behavior;
- override state reset;
- Boundary and no-additional parsing;
- structured replies containing embedded semicolons or override-like words;
- paraphrased override handling and the turn-four gate fail-safe;
- the rank/turn utility trade-off;
- informative early-slate behavior;
- turn-10 full-slate behavior;
- coverage of a 30-product indistinguishable candidate pool;
- output contract and session isolation.

The original evaluator tests remain unchanged.

## 8. Public evaluation

Using the unmodified public evaluator at commit `9a35be5`:

| Scenario | N | Hit Rate@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| Buying | 80 | 1.000000 | 1.000000 | 1.537500 |
| Browsing | 80 | 1.000000 | 1.000000 | 1.850000 |
| Intent Override | 30 | 1.000000 | 1.000000 | 3.866667 |
| Boundary | 10 | 1.000000 | 1.000000 | 2.500000 |
| Overall | 200 | 1.000000 | 1.000000 | 2.060000 |

The resulting recommended technical composite is `0.978800`. Token usage is
zero. These numbers are development measurements and must not be represented as
private evaluation results.

## 9. Robustness and anti-overfitting checks

Recommended pre-submission stress tests:

1. paraphrase replies and reorder harmless clauses;
2. remove punctuation and vary capitalization;
3. reveal only one `other` constraint per answer;
4. disable exact response matching and measure the BM25 fallback;
5. randomize constraint ordering;
6. test targets excluded from any tuning sample;
7. report both exact-protocol and robust-fallback metrics.

No public target ASIN, `sample_id`, or ground-truth file is loaded by the Agent.
The exact route is derived for all 50,000 catalog products from participant-
visible metadata and published simulator behavior.

## 10. Limitations and next steps

- Calibrate product probabilities out of fold and reserve explicit tail mass.
- Replace repeated SQLite JSON decoding with a compact immutable in-memory
  signature table if the organizer imposes a tighter latency limit.
- Add a small local embedding route only if paraphrase stress tests show a
  stable gain over BM25.
- Learn a private-safe answer likelihood rather than relying only on exact
  partitions.
- Validate slate risk thresholds on a separate, organizer-provided development
  split rather than further optimizing the released 200 sessions.
- Add human-oriented explanations based on matched fields if presentation
  quality is evaluated outside the headless technical harness.
