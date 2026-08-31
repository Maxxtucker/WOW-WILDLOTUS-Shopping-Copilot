# Agent architecture

The `agent` package is the production implementation behind `starter.agent.Agent`. Its highest-level orchestrator owns shared catalog resources, creates isolated conversation sessions, enforces the ten-turn API contract, and sends every normal turn through four stages:

```text
Understand → Intent Router → Retrieve/Rank → Decide
```

The Agent treats every `user_message` as ordinary shopper language. It does not
receive or depend on a target ID, generated intent template, public label, or
scenario state. Its runtime inputs are `session_id`, aggregate `user_profile`,
natural-language messages, turn number, and `top_k`.

Stage-specific documentation:

- [`understand/README.md`](understand/README.md)
- [`intent_router/README.md`](intent_router/README.md)
- [`retrieve/README.md`](retrieve/README.md)
- [`decide/README.md`](decide/README.md)

## Top-level execution

```mermaid
flowchart TD
    NEW["Agent(catalog_path)"] --> IDX["Resolve/build shared SQLite index"]
    IDX --> SIDE["Attach current slot sidecar if available"]
    SIDE --> WARM["Configure NLU; warm NLU and Router"]
    WARM --> READY["Process Agent ready"]
    RESET["reset(session_id, profile)"] --> STATE["Create isolated SessionState"]
    READY --> RESP["respond or respond_traced"]
    STATE --> RESP
    RESP --> VALID["Validate session, turn 1..10, top_k > 0"]
    VALID --> LOCK["Lock recommendation preference"]
    LOCK --> PIPE["TurnPipeline.run_traced"]
    PIPE --> OUT["Official response and optional TurnTrace"]
```

`agent/orchestrator.py` is the process-level supervisor:

- creates one `CatalogRetriever` shared by every session;
- creates the pipeline and bounded planning configuration once;
- keeps `sessions: dict[str, SessionState]`;
- uses an `RLock` around session creation, validation, and preference updates;
- loads `scripts/nlu.env` unless regex mode was explicitly requested;
- starts/checks the local LLM runtime and warms both NLU and Intent Router clients in NLU mode; and
- exposes `respond()` for the evaluator and `respond_traced()` for diagnostics/Chainlit.

The lock protects the session registry and turn-boundary changes. The longer pipeline call receives the isolated state object after validation, so all meaningful dialogue memory remains per session while the expensive catalog index is process-wide.

## Required interface

```python
agent = Agent("data/catalog.jsonl")
agent.reset("session-123", user_profile)
response = agent.respond(
    session_id="session-123",
    user_message="I need waterproof running shoes under $120.",
    turn=1,
    top_k=10,
)
```

The returned dictionary is:

```python
{
    "message": "I narrowed this to 3 high-confidence options. Which color would you prefer?",
    "ask_attribute": "color",
    "recommendations": [
        {"parent_asin": "..."},
        {"parent_asin": "..."},
        {"parent_asin": "..."},
    ],
    "usage": {
        "prompt_tokens": 0,
        "completion_tokens": 0,
    },
}
```

`message` is customer-facing prose. `ask_attribute` is the structured question
field for downstream callers, so they do not need to infer it from prose. Only
valid unique IDs among the first ten recommendations are scored.

## Session lifecycle

```mermaid
stateDiagram-v2
    [*] --> Reset
    Reset --> Active: create SessionState
    Active --> BeginTurn: respond turn 1..10
    BeginTurn --> Observe: apply prior miss and read message
    Observe --> Route: stage turn_delta
    Route --> Retrieve: commit state and exact pools
    Retrieve --> Decide: candidate posterior
    Decide --> Active: persist slate and ask_attribute
    Active --> Converted: evaluator target hit
    Active --> Expired: turn 10 miss
    Converted --> [*]
    Expired --> [*]
```

`reset()` always replaces any prior state with the same session ID. The Agent does not infer turns; the caller supplies them, and only integers `1..10` are accepted.

At each `begin_turn`:

1. if `turn > 1` and the prior action's conversion gate was open, the previous `last_slate` is unioned into `excluded_asins` as implicit miss feedback; current response writeback already records displayed IDs there, so this union is idempotent;
2. the turn/message fields are advanced and transient Router accounting is cleared;
3. Understand observes the message and writes a `turn_delta` without committing it; and
4. a non-empty disclosure is appended to `current_intent_messages`, the active-intent text used by raw-text safety recall.

## SessionState

`understand/state/session.py` is the complete mutable memory for one conversation.

### Intent and conversion control

| Field | Meaning |
|---|---|
| `category` | current primary category surface |
| `intention` | current `buying`, `browsing`, or `override` retrieval track |
| `intent_version` | increments when an accepted override opens a new intent |
| `gate_open` | whether a recommendation may be treated as conversion/miss evidence |
| `override_seen` | accepted override has reset old-intent leftovers |
| `last_gate_open` | gate state attached to the previous action |

### Constraints and disclosures

| Field | Meaning |
|---|---|
| `typed_constraints` | committed typed `ConstraintSlot` rows |
| `active_constraints` | regex/legacy cited strings |
| `legacy_hints` | provisional category-attached hints kept until override |
| `turn_delta` | current Understand result waiting for Router commit |
| `disclosed` | values already disclosed by the simulated/user conversation |
| `disclosure_empty` | whether this turn added no product/attribute direction |
| `preference_tags` | deduplicated reset-time aggregate profile tags |
| `reply_value_lookup` | normalized mapping used to restore compact follow-up answers |

### Recommendation and question memory

| Field | Meaning |
|---|---|
| `asked`, `last_ask` | previously requested structured attributes |
| `last_slate` | recommendations returned on the immediately prior action |
| `last_ranked` | complete normalized ranking saved for paging |
| `excluded_asins` | missed or otherwise blocked products |
| `shown_asins` | all products displayed under the current intent |

### Messages and route evidence

| Field | Meaning |
|---|---|
| `latest_message` | current original utterance |
| `message_history` | full session message log |
| `current_intent_messages` | non-empty messages since the last accepted override |
| `candidate_count_before_delta` | strict exact-pool size before this turn's delta |
| `candidate_count` | strict exact-pool size after the delta |
| `previous_candidate_count` | prior turn's committed count |
| `exact_strict`, `exact_lenient` | pools computed by Intent Router |

### Planner and accounting

| Field | Meaning |
|---|---|
| `router_prompt_tokens`, `router_completion_tokens` | per-turn Intent Router model usage included in the response |
| `scoring_weights` | immutable HitRate/MRR/Efficiency utility weights |
| `recommendation_preference_position` | UI slider position |
| `recommendation_preference_locked` | prevents changes after the first response begins |

`preference_tags` are copied from `user_profile["preference_tags"]` only at reset, blank values are dropped, and duplicates are removed case-insensitively. No raw purchase history or direct identity data is expected.

Catalog scoring may compute profile similarity for diagnostics, but the
profile contribution to its final weighted score is disabled (`0.0`). The
optional Qwen reranker can still receive those tags as explicitly weak context.

## Normal turn pipeline

The identifiers below are the production progress-node IDs. Solid edges are
the active chain; dotted edges identify bounded retries or compatibility nodes
that can be skipped.

### Understand node chain

<!-- workflow-schema:understand -->
```mermaid
flowchart TD
    prior_miss["Apply prior-turn miss feedback"]
    turn_reset["Reset turn-scoped state"]
    understand_mode["Choose NLU or regex extraction"]
    nlu_attempt["Run bounded full NLU attempts"]
    casefold["Create case-insensitive working text"]
    color_map["Map color aliases to catalog colors"]
    material_map["Map material aliases to catalog materials"]
    color_verify["Verify ambiguous color words"]
    material_verify["Verify ambiguous material words"]
    merge_rewrite["Build the normalized NLU sentence"]
    category_l1["Select broad catalog roots"]
    category_l2["Refine within selected L1 branches"]
    category_l3["Refine within selected L2 branches"]
    category_cap["Cap grounded category ambiguity"]
    attribute_llm["Extract typed current-turn constraints"]
    slot_grounding["Ground extracted fields in the message"]
    repair_1["Repair failed fields · round 1"]
    repair_2["Repair remaining fields · round 2"]
    repair_3["Repair remaining fields · round 3"]
    disclosure["Validate usable shopping disclosure"]
    regex_extract["Run deterministic fallback extraction"]
    colon_restore["Restore a bounded last-question answer"]
    turn_delta["Stage the turn-only observation delta"]
    active_intent_evidence["Append current-intent raw evidence"]
    empty_disclosure_gate["Choose paging or full pipeline"]
    prior_miss --> turn_reset
    turn_reset --> understand_mode
    understand_mode -- "nlu" --> nlu_attempt
    understand_mode -- "regex" --> regex_extract
    nlu_attempt --> casefold
    nlu_attempt -- "all three complete attempts fail" --> regex_extract
    casefold --> color_map
    casefold --> material_map
    color_map --> color_verify
    material_map --> material_verify
    color_verify --> merge_rewrite
    material_verify --> merge_rewrite
    merge_rewrite --> category_l1
    category_l1 -- "continue" --> category_l2
    category_l1 -- "stop, empty, error, or no children" --> category_cap
    category_l2 -- "continue" --> category_l3
    category_l2 -- "stop, empty, error, or no children" --> category_cap
    category_l3 --> category_cap
    category_cap --> attribute_llm
    attribute_llm --> slot_grounding
    slot_grounding -- "failed fields" --> repair_1
    slot_grounding -- "all grounded" --> disclosure
    repair_1 -- "failures remain" --> repair_2
    repair_1 -- "grounded or repair call fails" --> disclosure
    repair_2 -- "failures remain" --> repair_3
    repair_2 -- "grounded or repair call fails" --> disclosure
    repair_3 --> disclosure
    disclosure --> turn_delta
    regex_extract -- "non-empty regex extract with no constraints" --> colon_restore
    regex_extract -- "colon restore not eligible" --> turn_delta
    colon_restore --> turn_delta
    turn_delta --> active_intent_evidence
    active_intent_evidence --> empty_disclosure_gate
```
<!-- /workflow-schema -->

### Router node chain

<!-- workflow-schema:router -->
```mermaid
flowchart TD
    committed_intent["Check for committed prior intent"]
    override_l1["Detect a full intent replacement"]
    override_l2["Detect a partial field replacement"]
    strong_override_fallback["Recover explicit start-over language"]
    replace_delta["Replace the committed intent"]
    drop_slots["Drop only replaced fields"]
    override_gate_cleanup["Reset override-era memory"]
    probe_override["Build replacement exact pools"]
    intention_override["Route the replacement as override"]
    probe_before["Measure the pre-delta exact pool"]
    apply_delta["Accumulate the staged delta"]
    probe_after["Measure post-delta strict and lenient pools"]
    pool_ratio["Compute candidate-pool narrowing"]
    route_llm["Classify focused Buying or exploratory Browsing"]
    buying["Select focused Buying retrieval"]
    browsing["Select exploratory Browsing retrieval"]
    failsafe["Apply the turn-four gate failsafe"]
    committed_intent -- "prior intent exists" --> override_l1
    committed_intent -- "no committed intent" --> probe_before
    override_l1 -- "level 1" --> replace_delta
    override_l1 -- "not accepted" --> override_l2
    override_l2 -- "level 2" --> drop_slots
    override_l2 -- "LLM level 0" --> strong_override_fallback
    strong_override_fallback -- "match maps only to level 2" --> drop_slots
    strong_override_fallback -- "no match" --> probe_before
    replace_delta --> override_gate_cleanup
    drop_slots --> override_gate_cleanup
    override_gate_cleanup --> probe_override
    probe_override --> intention_override
    intention_override --> failsafe
    probe_before --> apply_delta
    apply_delta --> probe_after
    probe_after --> pool_ratio
    pool_ratio --> route_llm
    route_llm -- "buying" --> buying
    route_llm -- "browsing or failed attempts" --> browsing
    buying --> failsafe
    browsing --> failsafe
```
<!-- /workflow-schema -->

### Retrieve and rank node chain

<!-- workflow-schema:retrieve -->
```mermaid
flowchart TD
    select_pool["Select strict or lenient seed pool"]
    slot_groups["Build hard and soft scoring groups"]
    rewrite_query["Build the active-intent lexical query"]
    routing["Load route weights and limits"]
    lexical_in_pool["Restrict BM25 scores to the seed pool"]
    score_exact["Score selected-pool candidates"]
    hybrid_search["Recover or fill candidates permissively"]
    bm25_score["Measure BM25 lexical relevance"]
    required_score["Score required-constraint coverage"]
    preferred_score["Score soft preferences"]
    category_score["Score category agreement"]
    budget_score["Score and enforce budget fit"]
    dimension_score["Score and enforce dimension fit"]
    exclusion_score["Apply negative preference evidence"]
    structured_subtotal["Combine structured evidence"]
    rating_prior["Compute the rating-quality prior"]
    popularity_prior["Compute the popularity prior"]
    catalog_prior["Combine catalog quality priors"]
    title_text_fit["Measure soft-text title coverage"]
    details_text_fit["Measure soft-text details coverage"]
    description_text_fit["Measure soft-text description coverage"]
    soft_text_fit["Select the strongest soft-text fit"]
    profile_diagnostic["Compute disabled profile diagnostics"]
    weighted_score["Assemble the deterministic retrieval score"]
    cap_hits["Assemble the bounded base library"]
    raw_evidence["Check active-intent raw-text evidence"]
    base_only["Use the base route without fusion"]
    relaxed_route["Run relaxed structured safety recall"]
    raw_text_route["Run raw-text safety recall"]
    weighted_rrf["Fuse three recall routes with weighted RRF"]
    qwen_rerank["Try the optional Qwen semantic head"]
    semantic_logits["Convert semantic logits to fit scores"]
    semantic_blend["Blend semantic fit with base rank"]
    semantic_weights["Temperature-scale semantic head weights"]
    semantic_tail["Keep the unscored retrieval tail"]
    belief_temperature["Choose deterministic belief temperature"]
    belief_hits["Convert deterministic scores to weights"]
    normalize["Normalize ranking probability mass"]
    select_pool --> slot_groups
    slot_groups --> rewrite_query
    rewrite_query --> routing
    routing -- "selected pool non-empty" --> lexical_in_pool
    routing -- "selected pool missing or empty" --> hybrid_search
    lexical_in_pool --> score_exact
    score_exact -- "fewer than 150 scored hits" --> hybrid_search
    score_exact --> bm25_score
    score_exact --> required_score
    score_exact --> rating_prior
    score_exact --> title_text_fit
    score_exact --> profile_diagnostic
    hybrid_search --> bm25_score
    hybrid_search --> required_score
    hybrid_search --> rating_prior
    hybrid_search --> title_text_fit
    hybrid_search --> profile_diagnostic
    required_score --> preferred_score
    preferred_score --> category_score
    required_score --> budget_score
    preferred_score --> dimension_score
    category_score --> exclusion_score
    budget_score --> structured_subtotal
    dimension_score --> structured_subtotal
    exclusion_score --> structured_subtotal
    rating_prior --> popularity_prior
    popularity_prior --> catalog_prior
    title_text_fit --> details_text_fit
    details_text_fit --> description_text_fit
    description_text_fit --> soft_text_fit
    bm25_score --> weighted_score
    structured_subtotal --> weighted_score
    catalog_prior --> weighted_score
    soft_text_fit --> weighted_score
    profile_diagnostic --> weighted_score
    weighted_score --> cap_hits
    cap_hits --> raw_evidence
    raw_evidence -- "no raw evidence" --> base_only
    raw_evidence -- "raw evidence present" --> relaxed_route
    raw_evidence -- "raw evidence present" --> raw_text_route
    cap_hits -- "base route" --> weighted_rrf
    relaxed_route --> weighted_rrf
    raw_text_route --> weighted_rrf
    base_only --> qwen_rerank
    weighted_rrf --> qwen_rerank
    qwen_rerank -- "valid semantic head" --> semantic_logits
    qwen_rerank -- "unavailable or invalid" --> belief_temperature
    semantic_logits --> semantic_blend
    semantic_blend --> semantic_weights
    semantic_weights --> semantic_tail
    semantic_tail --> normalize
    belief_temperature --> belief_hits
    belief_hits --> normalize
```
<!-- /workflow-schema -->

### Decide node chain

<!-- workflow-schema:decide -->
```mermaid
flowchart TD
    answer_signature["Cache catalog-predicted answers"]
    eligible_questions["Generate informative unasked questions"]
    viability_filter["Filter questions by effective coverage"]
    planning_head["Build the planning head and tail mass"]
    action_space["Enumerate question and slate-size actions"]
    hit_component["Compute expected Hit@10 value"]
    mrr_component["Compute expected reciprocal-rank value"]
    efficiency_component["Compute expected turn-efficiency value"]
    immediate_value["Sum immediate action utility"]
    answer_branches["Expand no-hit answer branches"]
    tail_branches["Model planning-tail recovery branches"]
    future_value["Evaluate two future observations"]
    planner["Choose the best Dynamic Slate action"]
    epsilon_roll["Choose exploit or attribute exploration"]
    technical_exploit["Keep the planner's technical choice"]
    uniform_explore["Uniformly explore an eligible attribute"]
    selected_attribute["Finalize the clarification attribute"]
    fallback_question["Guarantee a pre-final question"]
    sequential_gate["Pass through the planned slate"]
    gate_rank1["Handle a compatibility gate change"]
    keep_planned["Keep the Dynamic Slate recommendations"]
    persist_turn["Persist action memory"]
    build_response["Build the official agent response"]
    answer_signature --> eligible_questions
    eligible_questions --> viability_filter
    viability_filter --> planning_head
    planning_head --> action_space
    action_space --> hit_component
    action_space --> mrr_component
    action_space --> efficiency_component
    hit_component --> immediate_value
    mrr_component --> immediate_value
    efficiency_component --> immediate_value
    action_space --> answer_branches
    action_space --> tail_branches
    answer_branches --> future_value
    tail_branches --> future_value
    immediate_value --> planner
    future_value --> planner
    planner --> epsilon_roll
    eligible_questions -- "pre-viability exploration pool" --> epsilon_roll
    epsilon_roll -- "roll >= 0.20" --> technical_exploit
    epsilon_roll -- "roll < 0.20" --> uniform_explore
    technical_exploit --> selected_attribute
    uniform_explore --> selected_attribute
    selected_attribute --> fallback_question
    fallback_question --> sequential_gate
    sequential_gate -- "compatibility change" --> gate_rank1
    sequential_gate -- "current no-op" --> keep_planned
    gate_rank1 --> persist_turn
    keep_planned --> persist_turn
    persist_turn --> build_response
```
<!-- /workflow-schema -->

The main path is implemented in `TurnPipeline.run_traced()`:

1. `StateDetector.apply()` runs Understand.
2. `IntentRouter.apply()` commits or replaces state and returns the strict exact pool.
3. `CandidateOrganizer.apply()` performs exact-first/hybrid retrieval and weighted route fusion.
4. `Ranker.apply()` converts search scores into a normalized candidate posterior, optionally using a local Qwen cross-encoder for the head.
5. `Clarifier.apply()` jointly chooses a recommendation prefix and `ask_attribute`.
6. `ResponseBuilder.apply()` persists the action and emits the official response shape.

`Clarifier` uses `DynamicSlatePlanner`, not `ScoreAwarePlanner.plan()`.
The compatibility `ScoreAwarePlanner` instance supplies only the outer
candidate-cap setting. Dynamic Slate decomposes immediate value into Hit,
MRR, and Efficiency terms, expands two answer observations, and then applies a
seeded epsilon policy (`0.20`) to the pre-viability informative/unasked
attribute list while leaving the planned slate unchanged. Question eligibility
does not directly suppress an attribute just because that attribute already
exists in `typed_constraints`.

Every stage emits structured progress events. `respond()` does not register a listener, so official evaluation has no UI dependency. `respond_traced()` returns the same response plus a read-only `TurnTrace` used by the demo and tests.

## Empty-disclosure shortcut

The shortcut is taken when all of the following are true after Understand:

- `turn_delta is None`;
- `disclosure_empty is not False` (`True` or `None`); and
- `last_ranked` still contains an ASIN not in `excluded_asins ∪ shown_asins`;

the pipeline skips Intent Router and Retrieve. It returns the next unshown prefix from `last_ranked`, capped by `min(top_k, 10)`, and asks a recovery question before turn 10. This treats “no additional preference” as a request to continue through existing evidence instead of repeating expensive retrieval.

If no leftover product exists, the shortcut is not taken and the normal route/retrieval path runs.

## Conversion gate and implicit negative feedback

The conversion gate controls modeled conversion utility and records whether the next turn should apply the explicit miss-feedback step:

- `record_action()` stores both `last_slate` and `last_gate_open`.
- At the next turn, only a slate shown with `last_gate_open=True` is unioned by `apply_miss_feedback()`; current response writeback already adds every shown slate to `excluded_asins`, so the conditional union does not change membership.
- An accepted override calls `open_conversion_gate()`, increments `intent_version`, sets `override_seen`, clears old misses/shown products/questions/legacy hints, and resets active-intent raw text.
- If a provisional path leaves the gate closed, the Router fail-safe opens it at turn 4. This fail-safe does not claim an override and does not increment `intent_version`.

## Runtime recommendation preference

Before the first `respond()`, `set_recommendation_preference(session_id, position)` maps a slider in `[0,100]` to planner weights:

- total HitRate + MRR budget is fixed at `0.80`;
- Efficiency is fixed at `0.20`;
- position `0` produces `HitRate=0.72`, `MRR=0.08`;
- position `100` produces `HitRate=0.08`, `MRR=0.72`;
- position `34.375` is the official-like default `0.50/0.30/0.20`;
- interior positions linearly change the HitRate share from 90% to 10% of the `0.80` recommendation budget.

The per-hit planner utility at turn `t` and rank `r` is:

\[
U(t,r)=w_H+\frac{w_M}{r}+0.20\cdot\frac{11-t}{10}.
\]

The setting is locked after the first response begins and affects planning only. The official evaluator still computes the fixed `0.50/0.30/0.20` TechnicalScore.

## Package map

```text
agent/
  orchestrator.py             process Agent and official API
  pipeline.py                 normal and empty-disclosure turn paths
  domain.py                   shared allowed attributes and text helpers
  progress.py                 optional progress-event protocol
  trace.py                    read-only stage traces
  understand/                 message observation and SessionState
  intent_router/              state commit and route selection
  retrieve/
    catalog/                  SQLite FTS/signature facade and scoring
    candidates/               exact-first organization and route fusion
  decide/
    ranking/                  semantic/fallback belief normalization
    clarification/            question and slate planner
    response/                 response construction and turn writeback
```

## Operating modes and failure behavior

### Understand mode

- `understand_mode="nlu"` or default: local Ollama extraction, three full attempts, then deterministic regex fallback.
- `understand_mode="regex"`: no Ollama initialization; use deterministic regex extraction and the bounded colon restore.

### Semantic reranker

- `AGENT_RERANKER_MODE=auto`: use the local model when available; otherwise use deterministic belief ranking.
- `off`: always use deterministic belief ranking.
- `required`: model load/inference failure raises a runtime error.

### Catalog assets

- A persistent FTS/signature index is fingerprinted by catalog path, size, and mtime and rebuilt automatically when stale.
- The separately preprocessed slot sidecar must already exist and be current. Missing/stale sidecars degrade safely; they are never rebuilt during a turn.

## Invariants

- Understand stages evidence but does not commit it.
- Intent Router is the only normal owner of typed-constraint writeback.
- Values within one typed attribute are OR alternatives; different attributes are AND requirements for exact filtering.
- Soft constraints never remove products from the strict exact pool.
- Old-intent raw messages are cleared on override and are never replayed into the new raw-text route.
- ASINs recorded in `excluded_asins`—including every displayed slate under current writeback—are removed before fusion and ranking.
- Decide returns only a prefix of the current ranking; it does not invent or reorder IDs independently.
- Turn 10 asks no further question and exposes the full allowed final prefix.
