# Agent pipeline

This document is the code-level runtime map for the production shopping agent.
The implementation under `agent/` is authoritative. The agent treats
`user_message` as ordinary shopper language and does not route on evaluator
templates, public labels, session IDs, or known targets.

The official entry remains `starter.agent.Agent`, a thin re-export of
`agent.orchestrator.Agent`.

## Process and session lifetime

`Agent.__init__()` resolves or builds one shared `CatalogRetriever`, attaches a
current catalog-slot sidecar when available, configures Understand mode, and
constructs one `TurnPipeline`. NLU mode warms the observation and Intent Router
clients. Regex mode skips Ollama startup.

`reset(session_id, user_profile)` replaces that session's `SessionState`.
`respond()` and `respond_traced()` require an existing session, a turn in
`1..10`, and positive `top_k`. The recommendation-preference setting locks when
the first response starts.

Every normal turn follows:

```text
Understand → Intent Router → Retrieve and Rank → Decide and Respond
```

Understand stages evidence only in `turn_delta`. Intent Router is the normal
owner of committed constraint writeback.

## Turn-level shortcut

After Understand, `empty_disclosure_gate` pages the previous ranking when:

```text
turn_delta is None
and disclosure_empty is not False
and at least one last_ranked ASIN is not shown/excluded
```

The `not False` check intentionally includes `None`, which is possible on the
deterministic regex path. The shortcut skips all Router and Retrieve nodes and
all Decide planning nodes, returns up to `min(top_k, 10)` unshown leftovers,
asks a recovery question before turn 10, then still runs `persist_turn` and
`build_response`. If no reusable ASIN remains, the normal pipeline runs.

## Understand: exact node chain

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

One complete NLU attempt includes casefold/alias rewriting, the bounded
three-layer category walk, optional category cap, one attribute extraction,
field grounding, up to three field-local repairs, and disclosure judgment.
Repair calls do not count as extra full attempts. Already-grounded fields stay
unchanged when a failed field is repaired. After three failed complete
attempts, `regex_extract` runs.

`turn_delta` is either the immutable `ObservationExtract` or `None` when the
extract is empty. Understand does not write committed `typed_constraints`,
`active_constraints`, or category state.

## Intent Router: exact node chain

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

The L1 model is accepted only when it returns full replacement and the current
delta contains category evidence. The model prompt judges semantic distance;
the code-level acceptance guard checks delta category presence. A rejected L1
continues to L2.

Only after the L1/L2 calls finish at level `0` does
`strong_override_fallback` inspect anchored explicit start-over language. A
match maps only to L2. L1 clears committed typed state before applying the
delta. L2 drops only attributes named by the delta, then applies it. Both clear
old-intent misses, shown products, questions, prior ranking, and raw intent
messages before probing the replacement intent.

The accumulate branch probes strict/lenient pools before and after
`apply_delta`, computes `after/before` only when both strict counts are
representable and the prior count is nonzero, then asks the route model for
`buying` or `browsing`. Three invalid route replies fall back to `browsing`.
There is no fixed pool-ratio threshold.

Router token counters include every L1, L2, and route-model attempt made on the
turn.

## Strict and lenient pool meaning

For each hard attribute, alternative values are unioned. Different attributes
are intersected. Soft slots never enter either exact pool.

Strict requires a known match for every represented hard group. Lenient uses
`match OR attribute unknown` for each group; a known mismatch still fails.
Hard budget and structured dimensions use numeric filters with missing values
rejected in strict and retained in lenient. Previously excluded ASINs are
subtracted from both pools.

`None` means the exact route cannot represent the active hard evidence.
`set()` means the evidence was represented but no candidate survived.

Retrieve selects lenient only when strict is not `None`, strict has fewer than
150 members, and lenient is non-empty. Otherwise strict remains selected.

## Retrieve and Rank: exact node chain

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

The base path is one of:

- score a non-empty selected exact pool;
- keep exact hits first and hybrid-fill to the library target when fewer than
  150 survive; or
- run hybrid-only recall when no selected exact pool is non-empty.

Buying/Override use a direct exact cap of 150 and a library target of 300.
Browsing uses 500. Hybrid fill disables hard required, budget, and dimension
pruning.

The detailed pre-fusion candidate score is:

```text
1.15 * w_lex * lexical
+ 0.003 * structured
+ rating_prior + popularity_prior
+ w_text * soft_text
```

`structured` contains required, missing-required, preferred, category, budget,
dimension, and exclusion terms. Soft text is the maximum of title coverage,
`0.7 * details coverage`, and `0.5 * description coverage`. Profile similarity
is computed for diagnostics, but its weighted final-score contribution is
disabled. The optional Qwen query can still include profile tags as explicitly
weak context.

When usable `current_intent_messages` exist, the base list is the strict RRF
route and Retrieve also runs relaxed structured and raw-text routes. Weighted
RRF is:

```text
1.40/(60 + strict_rank)
+ 0.90/(60 + relaxed_rank)
+ 1.25/(60 + raw_rank)
```

Without raw evidence, `base_only` bypasses the extra routes.

The optional Qwen cross-encoder reranks the first 50 candidates, blends sigmoid
logits with `1/log2(rank+1)`, applies temperature `0.20`, and retains the
unscored tail behind the head. If that path is unavailable, deterministic
belief uses `T=0.12` for ordinary search scores or
`clip((max-min)/4, 0.0025, 0.02)` for weighted-RRF scores. `normalize` turns
positive weights into the posterior consumed by Decide.

## Decide: exact node chain

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

Production planning is `DynamicSlatePlanner`. `ScoreAwarePlanner.plan()` is not
called; the compatibility object contributes only its
`max_planning_candidates` setting. Dynamic Slate plans over at most 80
candidates, reserves at least 0.20 tail mass, permits `k=0`, and evaluates two
future answer observations.

Immediate value decomposes into:

```text
Hit        = gate * Σ selected_probability * w_H
MRR        = gate * Σ selected_probability * w_M / rank
Efficiency = gate * Σ selected_probability * w_E * (11-turn)/10
```

Default weights are `0.50`, `0.30`, and `0.20`. The pre-chat preference control
may redistribute the first `0.80` between Hit and MRR; Efficiency stays `0.20`.

`eligible_questions` removes already asked attributes and requires at least one
informative answer signature. It does not directly filter an attribute merely
because that attribute is already present in `typed_constraints`.
`viability_filter` is separate and retains questions whose configured
coverage × parser reliability is at least `0.10`.

After Dynamic Slate chooses question and `k`, a deterministic random generator
seeded by `(session_id, intent_version, turn)` keeps the technical plan 80% of
the time. With probability `0.20`, it uniformly selects from the pre-viability
eligible list: concrete, informative, unasked attributes from before static
viability filtering. Exploration changes only `ask_attribute`; the planner's
slate and size remain unchanged.

Before turn 10, a null selected question is replaced by the highest-value
eligible fallback or a recovery question. On turn 10, Dynamic Slate skips
future interaction, returns the full allowed prefix, and sets
`ask_attribute=None`.

`apply_sequential_gate()` currently returns `plan.recommendations` unchanged.
`gate_rank1` remains only as a skipped compatibility/progress node;
`keep_planned` is the production branch.

## Response and writeback

`persist_turn` builds the next-turn reply lookup, stores the slate and
structured question, and immediately adds displayed ASINs to both
`shown_asins` and `excluded_asins`. The next turn's conditional miss union is
therefore idempotent in the current implementation.

`build_response` returns:

```text
message
ask_attribute
recommendations: ordered parent_asin objects
usage.prompt_tokens
usage.completion_tokens
```

Usage contains this turn's Intent Router tokens, including override and route
attempts. Understand NLU token counts are not currently reported.

## Main implementation files

- `agent/orchestrator.py`: process resources, sessions, API validation.
- `agent/pipeline.py`: normal and no-information paging paths.
- `agent/understand/`: turn-local observation and session lifecycle.
- `agent/intent_router/`: override, writeback, exact pools, route label.
- `agent/retrieve/`: base recall, score decomposition, safety fusion.
- `agent/decide/ranking/`: Qwen or deterministic belief normalization.
- `agent/decide/clarification/`: production Dynamic Slate policy.
- `agent/decide/response/`: session action writeback and response shape.

