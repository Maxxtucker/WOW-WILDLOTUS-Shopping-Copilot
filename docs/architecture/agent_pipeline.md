# Agent Pipeline

This document describes the runtime path of the shopping agent: how the evaluator calls Agent, how data flows inside one turn, what each module does, and the core code that implements it.

The implementation report is `[docs/IMPLEMENTATION.md](../IMPLEMENTATION.md)`. This page is about **structure and call paths**, not public-set scores or submission strategy.

The original contest repo tree is `[docs/architecture/original_repo_code_architecture.md](original_repo_code_architecture.md)`. This page covers only the split inside `agent/`. Each layer and subpackage has a README (purpose, collaboration, core variables, core code). Each `.py` file starts with Purpose / Input / Output.

Understand NLU (mode, Ollama startup, retries, regex fallback): `[understand_nlu.md](understand_nlu.md)`.

---

## 1. In one sentence

This agent is a multi-turn shopping retrieval system. Understand defaults to local NLU (`understand_mode="nlu"`): category and constraints come from the model, with three extract retries then regex fallback. Pass `understand_mode="regex"` for an LLM-free **extract** path (kit tests do this). Intention routing is a separate local JSON client with **no regex fallback**; kit tests mock it. Each turn, `TurnPipeline` observes into `turn_delta`, routes intention, retrieves, ranks, picks `ask_attribute`, writes back and responds. A hit is required within 10 turns.

The official entry is `starter.agent.Agent`. All logic lives in the `agent/` package.

---

## 2. End-to-end call chain

The evaluator does not know about the `agent` package. It imports only `starter.agent.Agent`:

```text
evaluator.local_evaluator
        │  from starter.agent import Agent
        ▼
starter/agent.py          # thin wrap: from agent import Agent
        ▼
agent/orchestrator.py     # thin: reset / respond → TurnPipeline
        ▼
agent/pipeline.py         # one-turn orchestration
        │
        ├── understand/    message → turn_delta
        │     state / attributes / observation
        ├── intent_router/ turn_delta → intention + exact pool
        ├── retrieve/      score router pool → SearchHit
        │     catalog / candidates
        └── decide/        SearchHit → official response
              ranking / clarification / response
```

External protocol for one public-set session:

```text
Agent.reset(session_id, user_profile)

for turn in 1..10:
    Agent.respond(session_id, user_message, turn, top_k=10)
        → { message, ask_attribute, recommendations, usage }

    if the target is among the first 10 valid parent_asin values and the
    conversion gate is open → hit, stop
    else customer_reply(...) or an Intent Override message → next turn
```

The interface contract is `[docs/agent_api_contract.json](../agent_api_contract.json)`. `ask_attribute` is a structured field; the simulator **does not infer the question from natural language**.

---

## 3. One-turn internal pipeline

`Agent.respond()` only validates and calls `TurnPipeline.run()`. Data flow for one turn:

```text
user_message
    │
    ▼
┌───────────────────────────────────────────────────────────────┐
│ 1. StateDetect  (understand/state/lifecycle.py)               │
│    • if last gate was open and we are called again → last     │
│      slate missed                                             │
│    • write turn / latest_message / history                    │
│    • then ObservationCoordinator                              │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────┐
│ 2. Observe  (understand/observation/)                         │
│    hybrid extract (nlu: up to 3 attempts, then regex)         │
│    write turn_delta only                                      │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────┐
│ 3. IntentRouter  (intent_router/)                             │
│    LLM L1? keep only if this turn's category is distant            │
│    else L2 replace-vs-add (skip both if no prior intent)          │
│    L1/L2 → clear or drop-delta-fields, apply_delta, open gate      │
│    else  → probe old → apply_delta → probe new → LLM buying/browsing │
│    fail-safe: gate closed at turn≥4 → open gate only          │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────┐
│ 5. CandidateOrganize  (retrieve/candidates/retrieve.py)       │
│    exact set: score_candidates (soft preferred), cap 150/500  │
│    exact is None: BM25 ∪ signatures                           │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────┐
│ 6. Ranking  (decide/ranking/belief.py + normalize.py)         │
│    score → exp((s - max)/0.12) → normalized RankedCandidate   │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────┐
│ 7. AskAttribute  (decide/clarification/)                      │
│    each legal ask_attribute × slate prefix k∈[0, top_k]       │
│    Q = immediate-hit utility + next-turn partitioned Top-10   │
│    then sequential slate risk gate (usually expose rank-1)    │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────┐
│ 8. WritebackAndReply  (decide/response/)                      │
│    set_reply_options: inverse map for next-turn semicolons    │
│    record_action: record slate / asked attribute              │
│    return message + ask_attribute + recommendations + usage    │
└───────────────────────────────────────────────────────────────┘
```

Orchestration code:

```41:53:agent/pipeline.py
    def run(...) -> dict:
        response, _trace = self.run_traced(...)
        return response

    def run_traced(...) -> tuple[dict, TurnTrace]:
        self.state_detector.apply(state, user_message, turn)
        exact = self.intent_router.apply(state, self.retriever)
        hits = self.organizer.apply(state, exact)
        ranked = self.ranker.apply(hits, state)
        plan, slate = self.clarifier.apply(state, ranked, top_k)
        return self.responder.apply(
            state, self.retriever, [hit.parent_asin for hit in hits], plan, slate
        ), TurnTrace(...)
```

Observe stores `turn_delta`. The intention router classifies override with a separate local model (no regex). L1 is kept only when this turn names a category that is far from the committed one (sandal vs backpack); attribute-only turns and close-family category swaps cannot be L1. L2 replaces only the fields present on this turn's delta, and only when the utterance clearly overturns a preference. Adding alternatives is not override. Catalog features may legally contain `instead` / `forget`; that is handled by the L2 prompt and by tests that mock accumulate. Both override levels open the conversion gate. The override LLMs are skipped when no committed prior intent exists.

---

## 4. Module map

| Module | Path | Responsibility |
| --- | --- | --- |
| Official entry | `starter/agent.py` | Evaluator import; re-exports `agent.Agent` |
| Orchestrator | `agent/orchestrator.py` | Session dict, index path, hand `respond` to pipeline |
| One-turn loop | `agent/pipeline.py` | Observe, route, retrieve, rank, plan, respond. `run_traced` also returns `TurnTrace` |
| Stage summaries | `agent/trace.py` | Compact per-stage dicts for the console chatbot |
| Stage contracts | `agent/stages.py` | Swappable Protocols, including `ResponseStage` |
| Dialogue memory | `agent/understand/state/` | `SessionState` dataclass; miss / fail-safe / begin_turn |
| Intention router | `agent/intent_router/` | Override LLM, delta commit, exact-pool probes, buying/browsing |
| Conversion gate | `agent/understand/state/gate.py` | Open gate and clear leftover / exclusions |
| Attributes | `agent/understand/attributes/` | Constraint writes, semicolon restore |
| Observation | `agent/understand/observation/` | Hybrid extract into `turn_delta`. Typed slots: [`slots/README.md`](../../agent/understand/observation/slots/README.md). NLU vs regex: [`understand_nlu.md`](understand_nlu.md) |
| Understand mode | `agent/understand/mode.py` | `nlu` (default) or `regex`; Agent keyword / env |
| Hard filter | `agent/intent_router/exact_pool.py` | Exact signature intersection (router probe) |
| Candidate fuse | `agent/retrieve/candidates/` | Score router pool; BM25 only if exact is None |
| Ranking | `agent/decide/ranking/` | Temperature softmax and `RankedCandidate` |
| Clarification | `agent/decide/clarification/` | Utility planning, question choice, slate gate |
| Response | `agent/decide/response/` | Message templates and session writeback |
| Catalog index | `agent/retrieve/catalog/` | SQLite FTS5 + response signature |
| Understand layer | [`agent/understand/README.md`](../../agent/understand/README.md) | message → SessionState |
| Retrieve layer | [`agent/retrieve/README.md`](../../agent/retrieve/README.md) | Router pool → SearchHit |
| Decide layer | [`agent/decide/README.md`](../../agent/decide/README.md) | SearchHit → official response |
| Domain protocol | `agent/domain.py` | Evaluator-aligned `intent_card` / `classify_constraint` |
| Evaluator (read-only) | `evaluator/local_evaluator.py` | Simulated customer and scoring; Agent **must not** read `public_set.jsonl` labels |

Package export:

```1:10:agent/__init__.py
"""Purpose: export Agent.

Input: evaluator constructs Agent(catalog_path) via starter.agent.
Output: Agent class with reset / respond.
Role: `from agent import Agent`. Implementation is orchestrator.py.
"""

from .orchestrator import Agent
```

```1:9:starter/agent.py
"""Competition entry point.

The official evaluator imports ``starter.agent.Agent``.  The implementation is
kept in the ``agent`` package so its components can be tested independently.
"""

from agent import Agent

__all__ = ["Agent"]
```

Tests and scripts import nested packages directly:

```python
from agent.understand.state import SessionState
from agent.decide.clarification import ScoreAwarePlanner, hit_utility
from agent.decide.ranking import normalize_probabilities
from agent.retrieve.catalog import CatalogRetriever, build_response_signature, _coerce_constraints
```

---

## 5. Module details

### 5.1 `agent.Agent` — thin entry

**File:** `agent/orchestrator.py`

**Owns:**

- Resolve the index path (`retrieve/catalog/index_path.py`).
- Construct the shared `CatalogRetriever`, `ScoreAwarePlanner`, and `TurnPipeline`.
- Isolate `SessionState` by `session_id`.
- Pin `understand_mode`, and when it is `nlu` load `scripts/nlu.env`, start Ollama, and construct the observation and intention-router chat clients. Details: [`understand_nlu.md`](understand_nlu.md).
- Validate `reset` / `turn` / `top_k`, then hand one turn to the pipeline.

```46:67:agent/orchestrator.py
    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        *,
        understand_mode: str | None = None,
    ) -> None:
        persistent_index = resolve_index_path(catalog_path)
        self.retriever = CatalogRetriever(catalog_path, index_path=persistent_index)
        self.planner = ScoreAwarePlanner(max_planning_candidates=500)
        self.pipeline = TurnPipeline(self.retriever, self.planner)
        self.sessions: dict[str, SessionState] = {}
        self._lock = RLock()
        if understand_mode != MODE_REGEX:
            load_nlu_env()
        self.understand_mode = configure_understand(
            resolve_understand_mode(understand_mode)
        )
        if self.understand_mode == MODE_NLU:
            ensure_llm_runtime()
            warmup_nlu()
            warmup_intent_router()
```

The index defaults to the OS temp directory (`AGENT_CACHE_DIR` / `tempfile`) and is invalidated by catalog fingerprint. `AGENT_INDEX_PATH=:memory:` forces an in-process rebuild.

---

### 5.2 Observe: turn_delta only

**Memory:** `SessionState` in `agent/understand/state/session.py`. Public `begin_turn` / `observe` / `record_action` still exist; internals delegate to submodules.

Key fields:

| Field | Meaning |
| --- | --- |
| `category` | Coarse category phrase (committed by the router) |
| `intention` | `buying` / `browsing` / `override` from the intention router |
| `turn_delta` | This turn's extract; observe writes it |
| `gate_open` | Conversion gate. When closed, showing the target **does not** end the session and cannot count as a miss |
| `active_constraints` | Current locked constraints |
| `typed_constraints` | Slot rows including optional category. Each row has `is_hard`. Hard slots prune; soft slots only score |
| `preference_tags` | Reset-time copy of aggregate `user_profile` tags. Soft long-term preferences; retrieve uses them only as a weak surface cosine tie-break, never as BM25 or exact-pool terms |
| `legacy_hints` | Pre-override leftover preference; dropped after override |
| `disclosed` | Values the simulator already revealed; not treated as new evidence in planning |
| `excluded_asins` | ASINs proven missed after the gate opened |
| `reply_value_lookup` | Surface form of last predicted reply → atomic constraints, so semicolons are not split wrongly |
| `candidate_count` | Exact-pool size after this turn's commit (`None` if the exact path is unavailable) |

**Turn start:**

```27:37:agent/understand/state/lifecycle.py
def begin_turn(state: SessionState, message: str, turn: int) -> None:
    apply_miss_feedback(state, turn)
    state.turn = turn
    state.latest_message = str(message)
    state.message_history.append(state.latest_message)
    state.last_reply_informative = False
    state.turn_delta = None
    state.candidate_count_before_delta = None
    state.router_prompt_tokens = 0
    state.router_completion_tokens = 0
    observe(state, message)
```

The evaluator **has no explicit negative click**. Another `respond(turn+1)` proves the previous open-gate slate missed. Displays while the gate was closed (before Override) are not negatives. If the gate is still closed at `turn >= 4`, fail-safe opens it **without** labeling `intention=override`.

**NLU vs regex.** Default `understand_mode` is `nlu`: `hybrid_extract` calls the local model (including on protocol-looking phrasing), retries a failed extract three times, then uses regex. `understand_mode="regex"` skips the model. `observe` only stores the extract. Full note: [`understand_nlu.md`](understand_nlu.md).

Regex templates (kit tests and NLU fallback) still live in `understand/observation/classify.py` and fill `turn_delta`:

| Shape | Extract |
| --- | --- |
| `I'm looking for X. A key requirement is: Y.` | hard category X, hard locked constraint Y |
| `I'm looking for X, but I'm still exploring.` | hard category X only |
| `I'm looking for X. {rest}` | hard category X; leftover rest is a soft slot |
| `For that, what matters is: A; B.` | locked constraints (semicolon restore via `reply_value_lookup`) |
| Override phrasing | new-need text as a hard constraint slot (router LLM still decides) |
| Empty replies (simulator judgment / no additional) | empty extract |

`ranking_constraints` still concatenates leftover hints for display and regex query fallback. Exact-pool probes and required scoring use **hard** typed slots only; leftover is a soft slot and does not prune.

### 5.2b Intention router

**Package:** `agent/intent_router/`. Independent Ollama JSON client (same host/model/timeout as observation, separate conversation state).

1. If there is no committed prior intent (category / typed_constraints / active_constraints / leftover), skip both override LLMs and accumulate.
2. Otherwise call L1 (`{"full": true|false}`). Keep L1 only when this turn names a category that is far from the committed one. Attribute-only turns and close-family category swaps discard L1 and call L2 (`{"override": true|false}`). L2 is also called when L1 is false. No catalog.
3. L1 clears all typed constraints then `apply_delta`. L2 drops only delta field names then `apply_delta`. Both open the conversion gate, probe the exact pool once, set `intention=override`, skip buying/browsing.
4. If not: probe the **old** state, `apply_delta`, probe again, then call the route LLM with counts and ratio → `buying` | `browsing`. Pass the after-delta exact set to retrieve.
5. Fail-safe after writeback. Three failed router extracts: not-override and `browsing`. No regex routing.

Tests patch `agent.intent_router.router.classify_override` and `classify_route`.

---

### 5.3 `agent.retrieve.catalog.CatalogRetriever` — index and recall

**Implementation:** `agent/retrieve/catalog/` (`types` / `signatures` / `index` / `scoring` / `search` / `retriever`).

The public API deliberately does not depend on session state or the planner, so it can be tested alone.

**Two indexes in one SQLite database (`INDEX_VERSION = agent-retrieval-v3`):**

| Table | Role |
| --- | --- |
| `products` | ASIN, price, rating, compressed raw JSON and signature JSON |
| `product_fts` | FTS5: title / categories / features / details / store / description |
| `signature_values` | Exact inverted index `(attribute, kind, value_norm, parent_asin)` |
| `index_meta` | Version + catalog fingerprint; decides rebuild |

`kind` is one of:

- `response`: values the simulator **will actually disclose** (intent-card constraints).
- `search`: extra aliases (category path, store/brand, material/color/price extracted from text). The planner uses response; BM25 fallback uses search.

**Each product's `ResponseSignature`:** precomputed at startup for the 50k catalog, mirroring official `intent_card`. `expected_reply(attribute, disclosed)` predicts the simulator's next sentence. If there is no value, the planner puts the product in the `NO_ADDITIONAL` partition.

**`search()` fusion:**

```text
query terms
    ├─ FTS5 BM25 (field weights: title 6, categories 4, features 2.5,
    │              details 2.5, store 1.5, description 1.0)
    └─ signature_candidates exact hits
         ↓
    candidate union (intersect required only when hard_required and the
    index has an exact hit)
         ↓
    score_candidates: Path A hard required unweighted; Path B hard hit/miss × rarity;
    both paths soft preferred × rarity; BM25 + soft-only text_fit + profile cosine + prior
         ↓
    sort by score, required_coverage, lexical, asin; truncate to limit
```

The exact path (`intent_router/exact_pool.py`) intersects `signature_candidates`. Retrieve then `score_candidates` on that set. Typed NLU uses slot attribute + search value with catalog aliases; the regex path keeps `response_only=True`. When the router returns `None`, retrieve uses `search(..., hard_required=False)`.

`retrieve/catalog/protocol_copy.py` keeps an independent copy of `intent_card` / `classify_constraint` so index build does not import `domain` in a cycle.

---

### 5.4 Router pool / Candidates / Ranking

**Exact filter** (router) requires category and every retrieve-facing **hard** constraint to hit in `signature_values`. Groups come from `retrieve/from_slots.py`. Any miss drops the intersection so the pool is not pruned empty. On the regex path, `response_only=True` keeps exact matching on strings the simulator can actually disclose (for example `"Leather sole"` must not collapse to `"leather"`). Typed slots look up `canonical` / amount with search aliases instead. Retrieve does not re-run this intersection.

**Belief transform:** temperature-`0.12` shifted softmax (`decide/ranking/belief.py`). Structured scores inside an exact-signature bucket are often identical; this temperature only spreads popularity/quality priors for ranking and does not claim calibrated probabilities.

---

### 5.5 `agent.decide.clarification.ScoreAwarePlanner` — joint planning

**Implementation:** `decide/clarification/planner.py`, `distinguish.py`, `questions.py`, `slate.py`.

One-step finite-horizon search over “how many products to show now” and “which attribute to ask next”. The objective is expected TechnicalScore utility, not raw entropy.

```1:12:agent/decide/clarification/utility.py
"""Purpose: contribution of one hit to official TechnicalScore.

Input: turn in [1, 10], rank >= 1.
Output: 0.50 + 0.30/rank + 0.02*(11-turn).
Role: planner utility unit; misses do not go through here (utility 0).
"""


def hit_utility(turn: int, rank: int) -> float:
    """Exact per-session contribution to the official technical composite."""

    return 0.50 + 0.30 / rank + 0.02 * (11 - turn)
```

Turn 1 / Rank 10 = `0.73`; Turn 2 / Rank 1 = `0.98`. Dumping an uncertain Top-10 too early loses score.

**Action space:**

- Question: `None` (ask nothing) or an still-informative attribute in `QUESTION_ATTRIBUTES`.
- Slate size: `k = 0 .. min(top_k, |candidates|)`.
- Turn 10 forces `ask_attribute=None` and slate = posterior Top-K.

Question filters: do not re-ask attributes already in `state.asked` or in `typed_constraints`; skip attributes with no non-`NO_ADDITIONAL` partition. `other` may repeat because each ask can reveal the next pair of constraints.

**Objective:**

```text
Q(S, a) = Σ_{d ∈ S} p(d) · U(t, rank(d))
         + Σ_{reply partition z}  Top10_utility(residual of z not in S, t+1)
```

Residuals are grouped by `answer_signature(asin, a)`. Only the first 500 candidates are expanded.

**Closed-gate special case:** while the Override conversion gate is closed, showing the target cannot score. The planner always exposes one placeholder product but uses the full candidate pool to pick the most informative question.

**Sequential slate gate** (`decide/clarification/slate.py`): gate open, not turn 10, and an informative question remains (or remaining candidates can still be probed one per turn) → expose only rank-1. Turn 10 is always a full Top-K.

Tie-break: at equal expected utility, prefer asking a question, then prefer a smaller slate. Natural-language questions are filled by `explain_question()`; the simulator **only reads `ask_attribute`**.

---

### 5.6 `agent.domain` — protocol mirror

**File:** `agent/domain.py`

- `intent_card(product)` — aligned with `evaluator.local_evaluator.intent_card`
- `coarse_category(values)` — category phrase in the initial message
- `classify_constraint(value)` — constraint → `budget/material/color/size/style/use_case/feature`
- `canonical(value)` — normalization for constraint equality
- `QUESTION_ATTRIBUTES` — planner question order (no `category`/`brand`)

`retrieve/catalog/protocol_copy.py` has independent copies of the same functions. `scripts/check_parity.py` and `tests/test_agent.py` keep both sides aligned with the official evaluator.

---

### 5.7 Evaluator side (outside Agent)

**File:** `evaluator/local_evaluator.py` (official code, do not change)

| Function | Behavior |
| --- | --- |
| `initial_message` | Buying gets a hard constraint; Override gets the old preference; others Exploring |
| `customer_reply` | Boundary: first answer is no preference; otherwise disclose up to 2 undisclosed constraints for `ask_attribute`; else `no additional preference` |
| `evaluate` | `reset` → at most 10 `respond` calls; hits before Override conversion do not count; only the first 10 unique legal ASINs |

Agent **must not** read `ground_truth` from `data/public_set.jsonl`.

---

## 6. How the evaluator scenarios look on this path

The public set still has four simulator scripts. The agent does not route on those labels. The intention router labels `buying` / `browsing` / `override` from language, dialogue, and pool sizes.

| Simulator script | First message (evaluator) | What the agent stores |
| --- | --- | --- |
| Buying | category + first hard constraint | same; gate open |
| Browsing | category only | same; gate open |
| Intent Override | category + leftover old preference | leftover in `legacy_hints`, gate closed until override |
| Boundary | same first line as Browsing | first asked attribute is an empty reply; agent writes nothing |

If the gate is still closed on turn 4, `apply_override_failsafe` opens it so a paraphrase cannot stall conversion. It does not set `intention=override`.

---

## 7. Runtime object lifetime

```text
Process start
    Agent.__init__
        CatalogRetriever opens or rebuilds SQLite (~50k products)
        ScoreAwarePlanner(max_planning_candidates=500)
        TurnPipeline(...)
        sessions = {}

Each session
    reset(session_id, user_profile)
        sessions[session_id] = SessionState(...)

    respond × N
        TurnPipeline.run reads/writes that SessionState
        shared Retriever / Planner are read-only

Process end
    persistent index may remain in temp; rebuilds when catalog fingerprint changes
```

`Agent` protects the `sessions` dict with `RLock`. `CatalogRetriever` has a connection-level lock because the SQLite connection uses `check_same_thread=False`.

Environment variables:

| Variable | Role |
| --- | --- |
| `AGENT_INDEX_PATH` | Explicit SQLite path; `:memory:` disables disk |
| `AGENT_CACHE_DIR` | Default cache root (else OS temp) |

---

## 8. Core types

```text
SearchHit            one recall row: asin, score, lexical/structured/prior, coverage
ResponseSignature    product protocol fingerprint + retrieval aliases
RankedCandidate      asin, raw weight, normalized probability
Plan                 recommendations, ask_attribute, expected_value, reason
SessionState         all mutable dialogue memory for one session
```

Data flows one way: **message → State → Hits → Belief → Plan → truncated slate → response → write back State**. `catalog` does not read `SessionState` (index API only); the router probe and `candidates` read session constraints and exclusions. The planner does not touch SQLite; it asks “how would this ASIN answer?” through the `answer_signature` callback.

---

## 9. Suggested reading order

1. `starter/agent.py` — entry
2. `agent/README.md` plus `understand/` `retrieve/` `decide/` and each subpackage README — tree and collaboration
3. [`understand_nlu.md`](understand_nlu.md) — nlu vs regex observe path
4. `agent/orchestrator.py` + `agent/pipeline.py` — thin orchestration and one-turn loop
5. `agent/understand/observation/hybrid.py` + `coordinator.py` — extract into turn_delta
6. `agent/intent_router/` — override vs accumulate, pool probes
7. `agent/understand/state/session.py` + `lifecycle.py` — session memory
8. `agent/retrieve/catalog/retriever.py` — recall facade
9. `agent/decide/clarification/planner.py` + `distinguish.py` — question choice
10. `evaluator/local_evaluator.py` `evaluate` / `customer_reply` — external loop
11. `tests/test_agent.py` + `tests/test_intent_router.py` — state machine, mocked router, signature alignment
