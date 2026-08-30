"""README-aligned node metadata layered over the legacy demo catalog.

The base catalog is kept for backwards compatibility. Importing this module
updates the same dictionaries in place, so Chainlit callers that imported
``demo.node_catalog`` earlier see the refined copy as well.
"""

from __future__ import annotations

from typing import Any

from demo.node_catalog import NODE_CATALOG, STAGE_BLURBS


def _node(
    stage: str,
    label: str,
    purpose: str,
    why: str,
    how: str,
    *,
    contract: str = "",
) -> dict[str, Any]:
    return {
        "stage": stage,
        "label": label,
        "purpose": purpose,
        "why": why,
        "how_it_works": how,
        "function": contract or purpose,
        "implementation": how,
    }


NODE_CATALOG.update(
    {
        # Understand: clarify the actual contract boundaries and repair semantics.
        "casefold": _node(
            "understand",
            "Normalize text",
            "Create the case-insensitive working text used by alias matching.",
            "Color and material normalization should not depend on capitalization, while the original utterance must remain available for category grounding and traceability.",
            "rewrite_for_nlu casefolds the utterance once. Alias scans read that folded text; the original message is preserved separately and is never overwritten.",
            contract="Raw user utterance → folded working text. No session constraint is committed here.",
        ),
        "merge_rewrite": _node(
            "understand",
            "Build normalized query",
            "Apply only verified color/material alias replacements to the NLU working sentence.",
            "The attribute model benefits from closed-vocabulary values, but category grounding and debugging still need the shopper's exact wording.",
            "Verified span replacements are merged in source order. Attribute extraction sees the rewritten sentence; the category walk still uses the original utterance.",
            contract="Verified alias spans → rewritten attribute-NLU text; original text remains unchanged.",
        ),
        "category_l1": _node(
            "understand",
            "Category · L1 roots",
            "Select only broad catalog roots that can contain the product explicitly supported by this turn.",
            "A broad-but-correct category is safer than an unjustified narrow branch. Audience, gender, age, sport, or product-type restrictions must not be invented.",
            "The category LLM receives only allowed L1 ids/labels and may return 0–3 ids. Empty ids or stop=true terminates the walk instead of forcing a match.",
        ),
        "category_l2": _node(
            "understand",
            "Category · L2 children",
            "Refine only inside the L1 branches selected by the previous layer.",
            "Constrained child-only traversal prevents category leakage and makes each narrowing decision auditable.",
            "Children of selected L1 nodes become the entire allowed list. category_scope rejects branches that add an unstated audience restriction.",
        ),
        "category_l3": _node(
            "understand",
            "Category · L3 children",
            "Take one final child-only refinement when the message supports it.",
            "The system should stop at the deepest supported category, not the deepest category available in the tree.",
            "The same allowed-child selection and audience guard runs at L3. No category is committed to SessionState in this node; Understand only stages the extract.",
        ),
        "category_cap": _node(
            "understand",
            "Cap category ambiguity",
            "Reduce an over-broad grounded category payload to at most five supported category tags.",
            "A large category payload weakens retrieval precision and makes the later exact pool less meaningful.",
            "When more than five grounded tags survive, a bounded JSON selection keeps five supported tags; repeated invalid output falls back deterministically.",
        ),
        "attribute_llm": _node(
            "understand",
            "Extract typed constraints",
            "Extract this turn's non-category requirements as typed, span-grounded slots with hardness and canonical values.",
            "Hard requirements and soft preferences must remain distinct so Retrieve can prune only on true must-haves while still ranking preferences.",
            "The local JSON model emits material/color/size/style/brand/budget/feature/use_case/other slots. Attribute handlers validate spans, canonical values, units, alternatives, and hardness.",
            contract="Rewritten current-turn text + locked context → grounded ObservationExtract fields. No override or Buying/Browsing decision occurs here.",
        ),
        "repair_1": _node(
            "understand",
            "Grounding repair · 1",
            "Repair only attribute fields that failed span or schema grounding after the initial extract.",
            "A malformed field should not force a full re-extraction or overwrite fields that were already valid.",
            "collect_failures identifies failed fields; the model receives only those failures and merge_repair_payload patches them back into the working payload.",
        ),
        "repair_2": _node(
            "understand",
            "Grounding repair · 2",
            "Run the second bounded field-local repair only if grounding failures remain.",
            "Bounded, local repair improves robustness while keeping model cost and state changes controlled.",
            "The same failed-field-only repair contract runs again. Valid fields from previous rounds remain untouched.",
        ),
        "repair_3": _node(
            "understand",
            "Grounding repair · 3",
            "Run the final field-local repair round before the full NLU attempt is considered unsuccessful.",
            "The pipeline needs a deterministic stopping point instead of an unbounded repair loop.",
            "After MAX_REPAIR_ROUNDS, remaining invalid output can cause the outer hybrid extractor to retry the complete NLU attempt or eventually fall back to regex.",
        ),
        "disclosure": _node(
            "understand",
            "Validate disclosure",
            "Decide whether this utterance actually disclosed usable category/attribute evidence.",
            "Acknowledgements, 'no preference', and empty answers must not create fake constraints or accidentally mutate the active intent.",
            "A small local JSON check sees the original message plus grounded extract. empty=true clears the staged extract; invalid classifier output is bounded and fail-open.",
        ),
        "turn_delta": _node(
            "understand",
            "Stage turn delta",
            "Store the current turn's grounded observation as a temporary delta and stop the Understand stage.",
            "Multi-turn correctness depends on separating observation from commitment. The router must decide replace-vs-accumulate before live constraints change.",
            "observe writes source/category/slots/empty into SessionState.turn_delta. Existing committed constraints are not changed by Understand.",
            contract="ObservationExtract → SessionState.turn_delta only. Intent Router owns all committed-state writeback.",
        ),

        # Intent Router: make strict/lenient semantics and write ownership explicit.
        "override_l1": _node(
            "router",
            "L1 full override?",
            "Detect a true whole-intent reset before any new turn delta is committed.",
            "A product-family switch must clear stale category and attribute constraints, while a normal refinement must preserve them.",
            "When prior committed intent exists, the local override classifier returns full=true/false. full=true selects the replace branch; otherwise routing continues to L2.",
        ),
        "override_l2": _node(
            "router",
            "L2 field override?",
            "Detect partial replacement of fields named by this turn while preserving unrelated committed constraints.",
            "'Blue instead of black' should replace color, not erase budget, use case, or product type.",
            "The L2 JSON classifier runs only after L1 is false. On true, drop_typed removes the attributes represented in turn_delta before the new delta is applied.",
        ),
        "probe_before": _node(
            "router",
            "Probe exact pool · before",
            "Measure the strict hard-constraint pool on the committed pre-delta state.",
            "Buying/Browsing routing uses how much this turn changes the feasible set, so the before measurement must be taken before accumulation.",
            "exact_pool_for_state applies OR within an attribute, AND across hard groups, then hard budget/dimension filters. None means an exact set cannot be represented; zero means a represented intersection is empty.",
        ),
        "probe_after": _node(
            "router",
            "Probe exact pool · after",
            "Build the strict and lenient hard-constraint pools after the turn delta is committed.",
            "Retrieve needs both a precise pool and a match-or-unknown recovery superset, while routing needs the after count for the narrowing ratio.",
            "The strict pool requires hard evidence; the lenient pool tolerates missing catalog evidence but never contradicting evidence. Soft slots never prune either pool.",
        ),
        "route_llm": _node(
            "router",
            "Classify Buying / Browsing",
            "Choose focused Buying versus exploratory Browsing from dialogue evidence plus the before/after pool change.",
            "The route controls retrieval breadth and scoring weights; it is not an evaluator label and should reflect the live session state.",
            "A local JSON call receives pool_before, pool_after, their ratio, and dialogue context. Explicit override skips this classifier and uses intention=override.",
        ),
        "buying": _node(
            "router",
            "Buying route",
            "Select tighter, structured-heavy retrieval for a focused purchase state.",
            "When hard requirements have converged, precision matters more than broad exploration.",
            "routing_for('buying') uses the focused score weights and a 150 direct-exact cap; under-floor recovery still builds a 300-item planning library.",
        ),
        "browsing": _node(
            "router",
            "Browsing route",
            "Select wider, lexical-heavier retrieval while the shopper is still exploring.",
            "Browsing should preserve recall so the hidden target is not eliminated before enough preference evidence exists.",
            "routing_for('browsing') increases lexical emphasis and uses a 500-item retrieval library.",
        ),

        # Retrieve: exact/lenient, base recall, safety recall, fusion, and ranking.
        "select_pool": _node(
            "retrieve",
            "Select strict / lenient pool",
            "Choose which router-produced exact set should seed candidate scoring.",
            "A small strict set can be too brittle when the catalog omits evidence. The lenient match-or-unknown set protects recall without accepting known contradictions.",
            "Use strict by default. If strict is represented but below the 150-candidate floor and a non-empty lenient pool exists, score the lenient pool instead. None and an empty set remain distinct in the inspector.",
        ),
        "slot_groups": _node(
            "retrieve",
            "Build scoring groups",
            "Convert committed typed state into hard required groups, soft preferred groups, and optional numeric filters.",
            "Only hard evidence may prune candidates. Soft preferences should improve order without eliminating plausible products.",
            "required_and_budget, preferred_groups, session_dimension, and soft_text_terms translate SessionState into the retriever's structured scoring inputs. Alternatives are OR inside one attribute; attributes combine with AND semantics.",
        ),
        "rewrite_query": _node(
            "retrieve",
            "Build lexical query",
            "Construct BM25 text from the committed active intent instead of blindly replaying the latest utterance.",
            "Reusing superseded or negated text after an override can resurrect stale intent and damage recall precision.",
            "rewrite_query joins committed category/search values; the latest message is only a fallback when structured search text is empty.",
        ),
        "routing": _node(
            "retrieve",
            "Load route weights / limits",
            "Load the Buying/Browsing/override scoring weights and candidate limits selected by Intent Router.",
            "The same candidate evidence should be scored differently for a focused buyer versus an exploratory browser.",
            "routing_for returns structured weights, direct exact cap, candidate_limit, and exact-first behavior; library_limit_for returns the downstream 300/500 library target.",
        ),
        "lexical_in_pool": _node(
            "retrieve",
            "BM25 inside selected pool",
            "Compute lexical relevance only for ASINs already admitted by the selected strict/lenient exact pool.",
            "BM25 should order eligible products without reopening the entire catalog after hard-pool selection.",
            "lexical_scores runs on the catalog candidate window, then the score map is intersected with the selected ASIN set before structured scoring.",
        ),
        "score_exact": _node(
            "retrieve",
            "Score selected pool",
            "Apply structured retrieval scoring to every selected exact/lenient candidate.",
            "Eligibility alone does not determine rank; category fit, required coverage, preferences, budget/dimensions, text, rating/popularity, and profile evidence still matter.",
            "score_candidates fuses the route-specific signals. Missing hard evidence is penalized; soft preferences never remove a candidate.",
        ),
        "hybrid_search": _node(
            "retrieve",
            "Hybrid base recall / fill",
            "Recover a full candidate library when the selected pool is missing, empty, or below the 150 floor.",
            "Exact intersections are vulnerable to sparse or incomplete catalog evidence. A permissive hybrid fill protects target recall before final ranking.",
            "If exact scoring yields fewer than 150 hits, keep those hits first and fill to the 300/500 library limit with hard_required=False. With no non-empty selected pool, run hybrid recall directly.",
        ),
        "cap_hits": _node(
            "retrieve",
            "Assemble base library",
            "Finalize the strict/exact-plus-fill base route before safety recall fusion.",
            "Downstream reranking should receive a bounded library, but the graph must distinguish this base route from the later three-route safety fusion.",
            "A large exact pool is capped by the route's direct exact limit; under-floor paths preserve exact hits then append hybrid fill. The resulting list becomes the weighted-RRF 'strict/base' route.",
        ),
        "raw_evidence": _node(
            "retrieve",
            "Check active-intent raw evidence",
            "Build raw lexical evidence from non-empty messages belonging to the current intent version.",
            "Structured extraction can miss useful wording. Raw current-intent text provides a recall safety net without reviving messages from before an override.",
            "current_intent_messages is cleared on intent reset. The helper tokenizes the concatenated active-intent messages; the current tokenizer deduplicates before Counter, so the runtime query is effectively first-seen unique terms despite the frequency-weighting loop.",
        ),
        "base_only": _node(
            "retrieve",
            "Use base route only",
            "Bypass safety fusion when there is no non-empty active-intent raw text.",
            "Running empty relaxed/raw searches would add cost without evidence and make the displayed graph misleading.",
            "The already-built base library passes directly to semantic/deterministic ranking; relaxed, raw-text, and weighted-RRF nodes are marked skipped.",
        ),
        "relaxed_route": _node(
            "retrieve",
            "Safety recall · relaxed",
            "Run a second structured search with category, budget, dimension, and required pruning relaxed.",
            "This route recovers products that semantically fit but are missing one piece of catalog metadata required by the strict path.",
            "The committed query and groups still contribute to score, but hard_required/hard_budget/hard_dimension are false and categories are not used as a hard restriction.",
        ),
        "raw_text_route": _node(
            "retrieve",
            "Safety recall · raw text",
            "Run a lexical-heavy search over the active-intent raw-text query with no structured hard filters.",
            "A pure lexical route protects against NLU or taxonomy misses and gives the fusion step independent evidence.",
            "The route uses RAW_RECALL_WEIGHTS (lexical 2.2 plus weak rating/popularity), no structured groups, and at least a 2,000-candidate BM25 window.",
        ),
        "weighted_rrf": _node(
            "retrieve",
            "Fuse routes · weighted RRF",
            "Fuse strict/base, relaxed, and raw-text rankings into one safety-recall library.",
            "Rank fusion combines independent recall signals without requiring their raw scores to share a calibrated scale.",
            "Weighted reciprocal-rank fusion uses k=60 and route weights strict/base=1.40, relaxed=0.90, raw=1.25, then removes already excluded ASINs and caps to the 300/500 library limit.",
        ),
        "qwen_rerank": _node(
            "retrieve",
            "Semantic head rerank",
            "Optionally rerank the strongest retrieval head using a local semantic cross-encoder.",
            "Keyword and structured scores can still miss paraphrases or nuanced shopping fit. Semantic comparison is most useful after recall has already been protected.",
            "QwenSemanticReranker evaluates up to the top 50 candidates and fuses semantic evidence with different Buying/Browsing strength. If unavailable or disabled, the node skips safely.",
        ),
        "belief_hits": _node(
            "retrieve",
            "Deterministic score belief",
            "Convert retrieval scores into positive relative weights when semantic reranking is unavailable.",
            "The planner needs a comparable concentration signal even when the optional local reranker cannot run.",
            "belief_from_hits applies an exponential temperature transform around the maximum score. The outputs are ranking weights, not calibrated purchase probabilities.",
        ),
        "normalize": _node(
            "retrieve",
            "Normalize ranking mass",
            "Normalize positive semantic/belief weights into the RankedCandidate distribution consumed by Decide.",
            "Dynamic slate planning needs ordered candidates plus relative probability mass, including the amount later reserved for the tail outside its planning head.",
            "normalize_probabilities sorts candidates and divides each positive weight by total weight. These values are planning beliefs, not externally calibrated probabilities.",
        ),

        # Decide: current dynamic-slate implementation, not the legacy gate story.
        "answer_signature": _node(
            "decide",
            "Cache predicted answers",
            "Build a memoized mapping from candidate × question attribute to the answer that catalog evidence predicts the shopper could give.",
            "The planner evaluates counterfactual clarification branches many times; recomputing catalog reply signatures inside every branch would be expensive and opaque.",
            "make_answer_signature wraps retriever.predict_reply with the current disclosed set and uses NO_ADDITIONAL when a product has no new value for that attribute.",
        ),
        "eligible_questions": _node(
            "decide",
            "Generate eligible questions",
            "List unresolved attributes that can still partition the ranked candidates, plus the option to ask nothing.",
            "A clarification should cost a turn only when it can change what the system knows or how candidates separate.",
            "eligible_questions skips hard typed attributes and most already-asked dimensions, respects the final-turn rule, and uses answer signatures to retain questions that distinguish the planning candidates.",
        ),
        "viability_filter": _node(
            "decide",
            "Filter question viability",
            "Remove questions whose expected useful-answer probability is too low for dynamic planning.",
            "Catalog coverage and parser reliability differ sharply by attribute; asking a theoretically discriminative but practically unanswerable question wastes MTTC.",
            "CatalogSignatureTransitionModel multiplies ATTRIBUTE_COVERAGE by PARSER_RELIABILITY and requires at least 0.10 effective coverage. Before turn 10 it injects a viable recovery attribute if the filtered set would otherwise be empty.",
        ),
        "planning_head": _node(
            "decide",
            "Build planning head + tail",
            "Compress the full ranking into at most 80 explicit planning candidates while reserving probability mass for products outside that head.",
            "Planning every candidate over two future observations is expensive, but pretending the truncated tail does not exist would overstate confidence in the head.",
            "root_state keeps up to 80 candidates, reserves at least 20% tail mass when candidates exist, rescales the head into the remaining probability budget, and carries gate probability into expected utility.",
        ),
        "action_space": _node(
            "decide",
            "Enumerate question × slate size",
            "Construct the joint action space over viable question choices and ranked-prefix size k.",
            "The optimal response is not just 'ask or recommend': showing 0, 1, or several products changes immediate hit utility and the information available on the next turn.",
            "Before turn 10, k ranges from 0 through min(10, top_k, head size) for every viable question and the planner looks ahead two observations. Turn 10 bypasses lookahead and forces the full available Top-K slate with no question.",
        ),
        "planner": _node(
            "decide",
            "Dynamic slate planner",
            "Choose the question and slate prefix that maximize expected competition-style utility now plus two future observations.",
            "The competition jointly rewards Hit@10, reciprocal rank, and reaching the target quickly, so clarification value must be weighed against the cost of delaying exposure.",
            "DynamicSlatePlanner scores immediate expected hit utility, expands no-hit/answer branches from catalog signatures and tail recovery, then chooses the best action. Exact ties prefer an informative question and then a smaller slate.",
        ),
        "fallback_question": _node(
            "decide",
            "Pre-final question guard",
            "Guarantee a concrete clarification before turn 10 when the dynamic planner selected no question.",
            "The current response contract expects the agent to keep learning before the final turn when a useful question is still recoverable.",
            "If raw planner ask_attribute is None before turn 10, the guard evaluates concrete eligible attributes with the same two-step action value, preferring never-asked fields; recovery_question is the final fallback. The planned slate and expected value are left unchanged.",
        ),
        "sequential_gate": _node(
            "decide",
            "Compatibility slate gate",
            "Pass the dynamic planner's slate through the retained sequential-gate interface.",
            "Older experiments used this hook to truncate to Rank-1, so keeping the node preserves trace compatibility while the current production policy is intentionally simpler.",
            "apply_sequential_gate currently returns plan.recommendations unchanged. The inspector reports whether that invariant held instead of claiming a Rank-1 promotion occurred.",
        ),
        "gate_rank1": _node(
            "decide",
            "Legacy gate-change branch",
            "Represent the compatibility branch that would run only if the sequential gate changed the planned slate.",
            "Keeping this branch visible makes historical trace semantics explicit without pretending it is part of the current normal policy.",
            "With the current no-op apply_sequential_gate implementation this node is skipped. It would become active automatically if the compatibility gate were re-enabled later.",
        ),
        "keep_planned": _node(
            "decide",
            "Keep dynamic slate",
            "Confirm that the slate selected by the dynamic planner is the slate passed to response writeback.",
            "This is the current normal path and prevents the UI from suggesting a hidden post-planner truncation.",
            "When the compatibility gate leaves the slate unchanged, this node records the final count and head ASINs before persistence.",
        ),
        "persist_turn": _node(
            "decide",
            "Persist action memory",
            "Write the shown slate, asked attribute, predicted reply lookup, and exposure memory needed by the next turn.",
            "Next-turn miss feedback and duplicate suppression depend on exactly what was shown and asked this turn.",
            "persist_turn predicts reply options for candidate ASINs, stores last_slate/last_ask, appends asked attributes, and immediately adds shown ASINs to both shown_asins and excluded_asins.",
        ),
        "build_response": _node(
            "decide",
            "Build official response",
            "Serialize the chosen slate and clarification into the evaluator's required respond() shape.",
            "The demo must end on the same external contract used by evaluation rather than a presentation-only payload.",
            "ResponseBuilder returns message, ask_attribute, recommendation objects containing parent_asin, and router token usage. Before turn 10 it also has a final recovery guard if ask_attribute is still None.",
            contract="Plan + final slate + session usage → {message, ask_attribute, recommendations, usage}.",
        ),
    }
)

STAGE_BLURBS.clear()
STAGE_BLURBS.update(
    {
        "understand": (
            "Observe this turn only: preserve the raw utterance, normalize safe aliases, "
            "walk the category tree, extract and ground typed slots, repair failed fields, "
            "validate disclosure, then stage turn_delta. No committed intent changes here."
        ),
        "router": (
            "Own committed-state writeback: detect L1/L2 overrides, replace or accumulate "
            "the staged delta, build strict + lenient hard pools, compare before/after pool "
            "size, and choose Buying, Browsing, or explicit override routing."
        ),
        "retrieve": (
            "Select strict/lenient seed pool, score exact candidates or hybrid-fill the "
            "library, optionally add relaxed + raw active-intent safety recall and weighted "
            "RRF, then semantic-rerank or deterministic-belief and normalize ranking mass."
        ),
        "decide": (
            "Predict clarification answers, filter viable questions, build an 80-item "
            "planning head with explicit tail mass, search question × slate-size actions "
            "with two-observation lookahead, guard pre-final questions, persist action "
            "memory, and return the official response contract."
        ),
    }
)

__all__ = ["NODE_CATALOG", "STAGE_BLURBS"]
