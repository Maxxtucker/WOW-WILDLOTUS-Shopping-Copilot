"""Canonical workflow graph and inspector metadata for the demo.

This module is the single source of truth for stage order, graph geometry,
conditional edges, and node descriptions. It contains presentation data only
and does not execute or modify the shopping pipeline.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

STAGE_ORDER = ("understand", "router", "retrieve", "decide")
NODE_FIELDS = frozenset(
    {"stage", "label", "task", "rationale", "implementation"}
)


def _node(
    stage: str,
    label: str,
    task: str,
    rationale: str,
    implementation: str,
) -> dict[str, str]:
    row = {
        "stage": stage,
        "label": label,
        "task": task,
        "rationale": rationale,
        "implementation": implementation,
    }
    if set(row) != NODE_FIELDS or not all(value.strip() for value in row.values()):
        raise ValueError(f"Invalid workflow node metadata for {label!r}")
    return row


_UNDERSTAND_NODES = {
    "prior_miss": _node(
        "understand",
        "Apply prior-turn miss feedback",
        "Treat a continued conversation as evidence that the previously exposed slate did not convert.",
        "Miss feedback prevents the same already-shown products from occupying later recommendation slots, while respecting the conversion gate used by override sessions.",
        "begin_turn calls apply_miss_feedback before resetting the turn. When turn > 1 and last_gate_open is true, every ASIN in last_slate is added to excluded_asins.",
    ),
    "turn_reset": _node(
        "understand",
        "Reset turn-scoped state",
        "Record the new message and clear values that belong only to the preceding turn.",
        "A new observation must start with clean temporary state without erasing the shopper's committed multi-turn intent.",
        "begin_turn writes turn/latest_message, appends message_history, and resets turn_delta, disclosure_empty, candidate_count_before_delta, last_reply_informative, and router token counters.",
    ),
    "understand_mode": _node(
        "understand",
        "Choose NLU or regex extraction",
        "Select the configured observation path for this turn.",
        "The normal NLU path provides grounded structured extraction, while the deterministic regex path keeps the agent operational when explicitly configured or after bounded NLU failure.",
        "current_understand_mode returns nlu or regex. NLU is the default; AGENT_UNDERSTAND_MODE or AGENT_NLU_ENABLED can select the deterministic path.",
    ),
    "nlu_attempt": _node(
        "understand",
        "Run bounded full NLU attempts",
        "Try the complete rewrite, category, attribute, grounding, repair, and disclosure flow up to three times.",
        "A transient model or JSON failure should not immediately discard natural-language understanding, but retries must remain bounded before deterministic fallback.",
        "hybrid_extract allows NLU_ATTEMPTS = 3 full attempts. The first usable ObservationExtract stops the loop; after all three fail, regex_extract runs.",
    ),
    "casefold": _node(
        "understand",
        "Create case-insensitive working text",
        "Casefold the current shopper message before alias matching.",
        "Color and material aliases should behave consistently across capitalization, while the original utterance remains available for category grounding and traceability.",
        "rewrite_for_nlu calls str.casefold once. Alias scans use the folded text; the original message is retained separately and is not overwritten.",
    ),
    "color_map": _node(
        "understand",
        "Map color aliases to catalog colors",
        "Find color phrases and map them to the closed catalog color vocabulary.",
        "Shopper language such as 'navy' may differ from catalog buckets such as 'blue'; normalization improves structured matching without changing unrelated words.",
        "A greedy longest, non-overlapping word-boundary scan reads the committed color alias map. Jewelry metals are protected from inappropriate color rewrites.",
    ),
    "material_map": _node(
        "understand",
        "Map material aliases to catalog materials",
        "Find material phrases and map them to the closed material vocabulary.",
        "Canonical material values let retrieval compare natural phrasing with catalog signatures without relying on exact surface-form equality.",
        "The material map uses the same greedy longest-span scan as color. A span found by both maps is resolved during merge_rewrite.",
    ),
    "color_verify": _node(
        "understand",
        "Verify ambiguous color words",
        "Keep a non-trivial color rewrite only when both the source and canonical value are color terms.",
        "Dictionary aliases can contain ordinary words, so semantic word-class validation protects the shopper's meaning from accidental rewrites.",
        "An optional local Ollama JSON gate validates color pairs. No hit means the node is skipped; unavailable or invalid validation fails open and preserves the mapped hits.",
    ),
    "material_verify": _node(
        "understand",
        "Verify ambiguous material words",
        "Keep a non-trivial material rewrite only when both sides are material, fiber, or fabric terms.",
        "Material aliases need the same precision protection as colors so common language is not converted into a catalog material by accident.",
        "The material word-class gate can run in parallel with color validation. Surviving hits are the only material replacements passed to merge_rewrite.",
    ),
    "merge_rewrite": _node(
        "understand",
        "Build the normalized NLU sentence",
        "Merge verified alias spans and apply them to the folded working sentence.",
        "Attribute extraction benefits from canonical values, but category selection and audit traces still need the shopper's original wording.",
        "merge_alias_hits resolves color/material overlap, then _apply_hits writes replacements in source order. Attribute NLU receives the rewrite; category walking receives the original message.",
    ),
    "category_l1": _node(
        "understand",
        "Select broad catalog roots",
        "Choose zero to three broad catalog branches supported by the current utterance.",
        "Starting broad avoids inventing a narrow audience, sport, gender, or product type that the shopper did not state.",
        "The category LLM sees only allowed L1 IDs and labels. Empty IDs or stop=true ends the walk; Unknown is removed and each layer's fan-out is capped.",
    ),
    "category_l2": _node(
        "understand",
        "Refine within selected L1 branches",
        "Choose supported children of the L1 nodes and no categories outside those branches.",
        "Child-only traversal prevents taxonomy leakage and makes each narrowing decision attributable to the shopper's words.",
        "Children of all selected L1 nodes are concatenated into one allowed list. Audience guards reject nodes that add an unstated age or gender restriction.",
    ),
    "category_l3": _node(
        "understand",
        "Refine within selected L2 branches",
        "Take a final child-only category step when the utterance supports greater specificity.",
        "The best category is the deepest supported node, not automatically the deepest node available in the catalog tree.",
        "The L3 call uses only children of selected L2 nodes and the same scope guard. Empty children, empty IDs, errors, or stop=true terminate the walk.",
    ),
    "category_cap": _node(
        "understand",
        "Cap grounded category ambiguity",
        "Reduce more than five grounded category tags to at most five supported tags.",
        "An over-broad category payload weakens exact-pool meaning and introduces avoidable retrieval noise.",
        "cap_category_payload performs up to three constrained JSON selections. Repeated invalid output falls back to required cited tags plus the highest slot-stat frequency tags in the allowed pool.",
    ),
    "attribute_llm": _node(
        "understand",
        "Extract typed current-turn constraints",
        "Extract non-category slots with source spans, canonical values, alternatives, numeric fields, and hard-versus-soft intent.",
        "Typed requirements let retrieval prune on actual must-haves and rank softer preferences without conflating the two.",
        "The local JSON model receives the rewritten current message and compact locked context. It may emit material, color, size, style, brand, budget, feature, use_case, or other, but not routing or override decisions.",
    ),
    "slot_grounding": _node(
        "understand",
        "Ground extracted fields in the message",
        "Validate extracted category and attribute fields against the shopper's source text and typed schemas.",
        "Grounding blocks invented values and isolates malformed fields so valid fields do not need to be regenerated.",
        "collect_failures span-checks category, provisional_hint, and constraint surfaces; attribute handlers validate canonical values, units, alternatives, and numeric shapes before slots are merged.",
    ),
    "repair_1": _node(
        "understand",
        "Repair failed fields · round 1",
        "Request replacements only for fields that failed the first grounding pass.",
        "Field-local repair preserves already-grounded evidence and reduces the chance that a full regeneration changes valid shopper constraints.",
        "merge_repair_payload keeps valid base fields and patches only the reported failures. MAX_REPAIR_ROUNDS is 3; a clean grounding pass stops immediately.",
    ),
    "repair_2": _node(
        "understand",
        "Repair remaining fields · round 2",
        "Run a second field-local repair only if failures remain after round one.",
        "A bounded second pass improves resilience to malformed JSON or spans without creating an unbounded model loop.",
        "The same failed-field-only schema is used. Valid fields from the original extract and round one remain untouched.",
    ),
    "repair_3": _node(
        "understand",
        "Repair remaining fields · round 3",
        "Run the final field-local repair before the current full NLU attempt finishes.",
        "Three local repair rounds provide a deterministic stopping point while leaving the outer full-attempt limit in control of broader failures.",
        "After round three, parsing uses the grounded fields that survived. A full NLU call that returns no usable extract can still be retried by nlu_attempt, up to three full attempts total.",
    ),
    "disclosure": _node(
        "understand",
        "Validate usable shopping disclosure",
        "Decide whether this utterance actually contributes category or attribute evidence.",
        "Acknowledgements, 'no preference', and empty answers must not create constraints or overwrite committed intent.",
        "A bounded local JSON check sees the original message and grounded extract. empty=true voids the extract; after three invalid replies the check fails open and keeps the delta.",
    ),
    "regex_extract": _node(
        "understand",
        "Run deterministic fallback extraction",
        "Extract category and constraint strings without a model when regex mode is selected or every full NLU attempt fails.",
        "A deterministic path keeps the turn usable offline and prevents model failures from aborting the shopping session.",
        "extract_from_regex runs category and constraint classifiers, creates typed ConstraintSlot rows, and marks the ObservationExtract source as regex.",
    ),
    "colon_restore": _node(
        "understand",
        "Restore a bounded last-question answer",
        "Recover a regex-path constraint from text following a colon when the normal regex extractor found none.",
        "Some direct answers echo the previous question before a colon; the fallback should recover that value without re-parsing successful NLU output.",
        "The node runs only for a non-empty, non-LLM extract with no constraints. colon_fallback requires last_ask, rejects skip markers, and adds grounded hard slots only when bounded checks pass.",
    ),
    "turn_delta": _node(
        "understand",
        "Stage the turn-only observation delta",
        "Store the current turn's extracted category and slots without committing them to active intent.",
        "Separating observation from commitment lets the router decide whether new evidence accumulates, replaces fields, or resets the whole need.",
        "observe sets SessionState.turn_delta to the ObservationExtract, or None when it is empty. Understand does not mutate committed category or constraints.",
    ),
    "active_intent_evidence": _node(
        "understand",
        "Append current-intent raw evidence",
        "Keep the original message as safety-recall evidence only when disclosure is explicitly non-empty.",
        "Raw text protects recall after an extraction miss, but acknowledgements and messages from superseded intents must not pollute later retrieval.",
        "begin_turn appends latest_message to current_intent_messages only when disclosure_empty is False. Override cleanup resets that list to the new intent's latest message.",
    ),
    "empty_disclosure_gate": _node(
        "understand",
        "Choose paging or full pipeline",
        "Page unshown candidates from the previous ranking when this turn adds no evidence, otherwise continue through Router and Retrieve.",
        "A no-preference answer should not pay for redundant routing and retrieval when a real leftover ranking already exists.",
        "pages_empty_disclosure requires turn_delta=None, disclosure_empty not False, and at least one unshown last_ranked ASIN. It skips Router, Retrieve, and joint planning, but still persists and builds the response; no leftovers fall through normally.",
    ),
}


_ROUTER_NODES = {
    "committed_intent": _node(
        "router",
        "Check for committed prior intent",
        "Determine whether session memory already contains a category, typed constraint, active constraint, or legacy hint.",
        "Override classification is meaningful only when there is an existing shopping need to replace.",
        "has_committed_intent checks category, active_constraints, legacy_hints, and typed_constraints. With no committed intent, both override classifiers are skipped and the normal accumulate branch is used.",
    ),
    "override_l1": _node(
        "router",
        "Detect a full intent replacement",
        "Identify an explicit whole-need reset to a distant replacement product category.",
        "A genuine product-family change must remove stale fields, while an attribute change or close-family category refinement must not erase unrelated constraints.",
        "The L1 JSON classifier may select level 1 only when full=true and this turn's delta contains a category. Without a delta category, L1 is rejected and routing continues to L2.",
    ),
    "override_l2": _node(
        "router",
        "Detect a partial field replacement",
        "Identify explicit replacement of only the category or attributes named by this turn.",
        "A request such as 'blue instead of black' should replace color while preserving budget, size, and other committed requirements.",
        "The L2 classifier runs after L1 is not accepted and returns override=true/false. True maps to level 2, which drops only delta attribute names before applying the delta.",
    ),
    "strong_override_fallback": _node(
        "router",
        "Recover explicit start-over language",
        "Catch strong override wording when both model classifiers returned accumulate.",
        "Clear phrases such as 'I changed my mind' should not silently accumulate onto stale intent after a model miss.",
        "When committed intent exists and the classifier level is 0, _STRONG_OVERRIDE_RE checks a small set of explicit start-over phrases. A match maps to L2, not L1, so only fields present in the delta are replaced.",
    ),
    "replace_delta": _node(
        "router",
        "Replace the committed intent",
        "Clear the prior typed need and apply this turn's delta as the new intent.",
        "A confirmed L1 product-family replacement must not retain category or attribute evidence from the superseded request.",
        "apply_override_decision level 1 clears typed, active, legacy, and category state, then calls apply_delta. L1 already requires a replacement category in the delta.",
    ),
    "drop_slots": _node(
        "router",
        "Drop only replaced fields",
        "Remove committed values whose attribute names appear in the L2 turn delta, then apply the new values.",
        "Partial override should preserve every unrelated part of the shopper's active intent.",
        "drop_typed removes matching typed slots and legacy active strings; category is cleared only when category is in the delta. apply_delta then upserts the replacement values.",
    ),
    "override_gate_cleanup": _node(
        "router",
        "Reset override-era memory",
        "Open conversion for the new intent and clear ranking, exposure, question, and raw-text memory tied to the old intent.",
        "Products and questions from a superseded need must not be treated as misses or evidence for the replacement need.",
        "finish_override_gate increments intent_version, sets override_seen and gate_open, clears legacy hints, exclusions, shown ASINs, asked attributes, and last_ranked, then resets current_intent_messages to the latest message.",
    ),
    "probe_override": _node(
        "router",
        "Build replacement exact pools",
        "Measure strict and lenient hard-constraint pools once after override writeback.",
        "The old and new product families are not comparable, so override routing should not compute a before/after narrowing ratio.",
        "probe_exact_pools unions alternatives within each attribute and intersects across attributes. Strict requires matching evidence; lenient keeps match-or-unknown products, and hard budget/dimensions use the same strict versus allow-missing distinction.",
    ),
    "intention_override": _node(
        "router",
        "Route the replacement as override",
        "Set intention=override and bypass Buying/Browsing classification.",
        "Once replacement semantics are explicit, another model call cannot add useful route information.",
        "The override branch stores the replacement pool counts, sets candidate_count_before_delta=None and intention='override', and later uses the same focused retrieval configuration as Buying.",
    ),
    "probe_before": _node(
        "router",
        "Measure the pre-delta exact pool",
        "Build strict hard pools from committed state before accumulating this turn's delta.",
        "Buying/Browsing classification uses the change in feasible catalog size, so the baseline must be captured before writeback.",
        "probe_exact_pools applies OR within each hard attribute and AND across attributes, then hard numeric filters. Soft slots never prune; None means unrepresentable and an empty set means a represented intersection with zero hits.",
    ),
    "apply_delta": _node(
        "router",
        "Accumulate the staged delta",
        "Upsert the turn delta into committed session memory without dropping unrelated values.",
        "Normal follow-ups should refine the shopper's need rather than behave like independent searches.",
        "apply_delta writes grounded typed slots and legacy constraint strings, merges same-attribute alternatives, and synchronizes the primary category. It is the normal branch's committed-state writeback.",
    ),
    "probe_after": _node(
        "router",
        "Measure post-delta strict and lenient pools",
        "Build the exact pools that reflect the newly committed state and will seed Retrieve.",
        "The strict pool supports precision, while the lenient match-or-unknown superset protects recall when catalog attributes are missing but never admits known contradictions.",
        "exact_pools_for_state applies grouped hard signatures plus hard budget and dimensions, subtracts excluded ASINs, and writes both exact_strict and exact_lenient to SessionState.",
    ),
    "pool_ratio": _node(
        "router",
        "Compute candidate-pool narrowing",
        "Calculate after_count / before_count for the normal routing branch.",
        "A strong reduction is evidence of a more focused shopping state, but absent or zero baselines must not be represented as a misleading numeric ratio.",
        "pool_ratio returns None when either count is None or before is zero; otherwise it returns after divided by before and passes that value to route classification.",
    ),
    "route_llm": _node(
        "router",
        "Classify focused Buying or exploratory Browsing",
        "Choose the retrieval track from dialogue context and before/after pool evidence.",
        "The track controls ranking weights and library breadth and must reflect live shopper intent rather than evaluator scenario labels.",
        "classify_route sends category, locked constraints, recent history, message, counts, and ratio to a separate local JSON client. It retries up to three times and defaults to browsing on invalid output.",
    ),
    "buying": _node(
        "router",
        "Select focused Buying retrieval",
        "Use a smaller, structured-heavy retrieval policy for an actionable purchase need.",
        "Once hard requirements converge, precision and exact evidence should dominate broad lexical discovery.",
        "routing_for('buying') uses lexical 0.4, required 6.0, category 4.0, text 0.5, a 150 direct-exact cap, and a minimum downstream library of 300.",
    ),
    "browsing": _node(
        "router",
        "Select exploratory Browsing retrieval",
        "Use a wider, lexical-heavier retrieval policy while the shopper is still exploring.",
        "A broad state needs additional recall so plausible products are not removed before enough preference evidence arrives.",
        "routing_for('browsing') uses lexical 1.6, required 2.5, category 2.0, text 1.0, and a 500-item retrieval library.",
    ),
    "failsafe": _node(
        "router",
        "Apply the turn-four gate failsafe",
        "Open a conversion gate that remains closed at turn four or later.",
        "A missed override signal must not prevent conversion for the rest of the session.",
        "apply_override_failsafe sets gate_open when turn >= 4 and the gate is still closed. It does not change intention, increment intent_version, or mark override_seen.",
    ),
}


_RETRIEVE_NODES = {
    "select_pool": _node(
        "retrieve",
        "Select strict or lenient seed pool",
        "Choose the router-produced ASIN set that will seed direct candidate scoring.",
        "A small strict pool can be brittle when catalog evidence is missing; the match-or-unknown pool preserves recall without accepting known contradictions.",
        "Strict is the default. When strict is represented but has fewer than 150 ASINs and lenient is non-empty, Retrieve selects lenient; None and an empty set retain different meanings.",
    ),
    "slot_groups": _node(
        "retrieve",
        "Build hard and soft scoring groups",
        "Convert committed typed state into required groups, preferred groups, budget, dimensions, exclusions, and soft text.",
        "Only hard requirements may prune; preferences should improve ordering without eliminating plausible products.",
        "Values inside one attribute form an OR group and different attributes combine with AND semantics. Hard numeric slots can filter, while soft values feed ranking features.",
    ),
    "rewrite_query": _node(
        "retrieve",
        "Build the active-intent lexical query",
        "Construct BM25 text from committed category and search values.",
        "Replaying the latest utterance after an override could resurrect negated or superseded language.",
        "rewrite_query joins committed category and slot search terms. latest_message is used only when the structured query would otherwise be empty.",
    ),
    "routing": _node(
        "retrieve",
        "Load route weights and limits",
        "Resolve the Buying, Browsing, or override scoring configuration and candidate bounds.",
        "Focused and exploratory shoppers should score the same evidence with different emphases and breadth.",
        "routing_for returns SearchWeights, direct exact cap, exact-first behavior, and a 1,500 BM25 candidate window. Buying/override cap direct exact at 150; Browsing uses 500; library_limit_for guarantees at least 300.",
    ),
    "lexical_in_pool": _node(
        "retrieve",
        "Restrict BM25 scores to the seed pool",
        "Compute lexical relevance and keep scores only for ASINs admitted by the selected strict or lenient pool.",
        "BM25 should order eligible products without reopening the full catalog after hard-pool selection.",
        "lexical_scores searches the configured candidate window, then the score map is intersected with exact_pool before score_candidates runs.",
    ),
    "score_exact": _node(
        "retrieve",
        "Score selected-pool candidates",
        "Apply the shared catalog scorer to every ASIN in the non-empty selected pool.",
        "Exact eligibility does not determine ordering; products still differ in lexical fit, preferences, category, numeric fit, text, and catalog priors.",
        "score_candidates receives in_exact_pool=True so matched required/category signals do not receive rarity scaling and missing-required penalties are not added to exact-pool candidates.",
    ),
    "hybrid_search": _node(
        "retrieve",
        "Recover or fill candidates permissively",
        "Run broad BM25 plus catalog scoring when the seed pool is absent, empty, or scores below the 150-candidate floor.",
        "Sparse signatures must not collapse the planning library or hide a relevant product that lacks one structured catalog field.",
        "retriever.search runs with hard_required=False. A small selected pool stays first and is filled to 300/500 with its ASINs excluded from fill; a missing/empty pool runs hybrid directly.",
    ),
    "bm25_score": _node(
        "retrieve",
        "Measure BM25 lexical relevance",
        "Read the raw lexical score for each candidate and convert it into the lexical contribution.",
        "Exact words remain a strong relevance signal, especially on the Browsing route, but they must be combined with structured and semantic evidence.",
        "The final lexical contribution is 1.15 × w_lex × BM25. w_lex comes from the current route.",
    ),
    "required_score": _node(
        "retrieve",
        "Score required-constraint coverage",
        "Measure the best signature similarity for each hard attribute group and apply its route weight.",
        "Must-haves need strong influence, while alternatives within one attribute should not be treated as simultaneous requirements.",
        "The scorer takes the maximum similarity inside each OR group, applies required weight and optional IDF rarity, and adds a missing-required penalty only outside the exact pool.",
    ),
    "preferred_score": _node(
        "retrieve",
        "Score soft preferences",
        "Reward candidates matching preferred attribute groups without filtering non-matches.",
        "Preferences should break ties and improve fit without becoming accidental hard constraints.",
        "For each preferred OR group, the best signature similarity is multiplied by the preferred weight and rarity factor. A miss contributes zero and never removes the candidate.",
    ),
    "category_score": _node(
        "retrieve",
        "Score category agreement",
        "Reward candidate signatures that match the active hard category values.",
        "Category fit suppresses unrelated product types while still allowing recovery routes to remain permissive.",
        "The best category signature similarity is multiplied by the route category weight and, outside exact pools, an IDF rarity factor.",
    ),
    "budget_score": _node(
        "retrieve",
        "Score and enforce budget fit",
        "Apply hard price filtering when required and add a budget-fit contribution for in-range prices.",
        "A hard budget is an eligibility condition; a soft or recovery budget should influence rank without manufacturing a price for missing data.",
        "Hard mode drops missing or out-of-range prices. _budget_fit returns 1 only for a present in-range price, and its weighted value joins the structured subtotal.",
    ),
    "dimension_score": _node(
        "retrieve",
        "Score and enforce dimension fit",
        "Compare stated length, width, height, or weight against catalog dimension extras.",
        "Physical-size requirements can be decisive, but absent catalog measurements need different strict and lenient behavior.",
        "Hard mode filters failed measurements; lenient probing may keep missing axes. Equality uses 10% tolerance with absolute floors of 0.25 inch and 0.05 pound.",
    ),
    "exclusion_score": _node(
        "retrieve",
        "Apply negative preference evidence",
        "Penalize or remove candidates matching excluded attribute values.",
        "Products that contradict an explicit rejection should not rank highly or repeatedly return.",
        "The scorer takes the maximum excluded-pair similarity. With hard exclusions, similarity >= 0.9 drops the candidate; otherwise w_excluded × similarity is added to the structured subtotal.",
    ),
    "structured_subtotal": _node(
        "retrieve",
        "Combine structured evidence",
        "Sum required, missing-required, preferred, category, budget, dimension, and exclusion contributions.",
        "Keeping the raw structured subtotal visible makes exact and soft catalog evidence auditable before scale fusion.",
        "The raw component sum is multiplied by 0.003 in the final score; the small scale keeps signature weights comparable with BM25 and catalog priors.",
    ),
    "rating_prior": _node(
        "retrieve",
        "Compute the rating-quality prior",
        "Add a bounded contribution from average product rating.",
        "Rating is useful as a weak quality tie-breaker but should not override the shopper's requirements.",
        "The scorer clamps average_rating / 5 to [0, 1] and multiplies by the route's rating weight.",
    ),
    "popularity_prior": _node(
        "retrieve",
        "Compute the popularity prior",
        "Add a logarithmically normalized contribution from rating count.",
        "Popularity can stabilize ties, but logarithmic scaling prevents very popular items from dominating relevance.",
        "The contribution is w_popularity × log1p(rating_number) / log1p(max_catalog_rating_count).",
    ),
    "catalog_prior": _node(
        "retrieve",
        "Combine catalog quality priors",
        "Sum rating and popularity contributions for each candidate.",
        "A single prior term keeps weak catalog-quality evidence separate from lexical and shopper-specific fit.",
        "prior_score is rating_prior + popularity_prior and enters the final score without an additional multiplier.",
    ),
    "title_text_fit": _node(
        "retrieve",
        "Measure soft-text title coverage",
        "Measure how much of the soft-text query appears in canonicalized product title tokens.",
        "A title match is the strongest of the three unstructured soft-text fields.",
        "Coverage is the intersection of soft query tokens and title tokens divided by the number of soft query tokens, with no field discount.",
    ),
    "details_text_fit": _node(
        "retrieve",
        "Measure soft-text details coverage",
        "Measure soft query token coverage in canonicalized product details.",
        "Structured details often contain useful fit evidence, but are noisier than the title.",
        "Token coverage is multiplied by 0.7 before competing with title and description coverage.",
    ),
    "description_text_fit": _node(
        "retrieve",
        "Measure soft-text description coverage",
        "Measure soft query token coverage in the canonicalized product description.",
        "Descriptions protect recall for nuanced preferences but contain more marketing noise than shorter fields.",
        "Token coverage is multiplied by 0.5 before the best text field is selected.",
    ),
    "soft_text_fit": _node(
        "retrieve",
        "Select the strongest soft-text fit",
        "Take the maximum of title, discounted details, and discounted description coverage.",
        "Using the best field avoids triple-counting repeated copy while preserving the strongest textual evidence.",
        "text_fit = max(title coverage, 0.7 × details coverage, 0.5 × description coverage); its final contribution is w_text × text_fit.",
    ),
    "profile_diagnostic": _node(
        "retrieve",
        "Compute disabled profile diagnostics",
        "Measure aggregate profile-tag fit for inspection without changing candidate scores.",
        "The current request must dominate and the profile feature has not been enabled for production ranking, so the UI must not imply that it affects order.",
        "profile_fits is computed and recorded as profile_fit, but the scoring term is commented out and profile_weighted is exactly 0.0.",
    ),
    "weighted_score": _node(
        "retrieve",
        "Assemble the deterministic retrieval score",
        "Fuse lexical, structured, catalog-prior, and soft-text contributions into the candidate score.",
        "A single code-authoritative formula makes route effects and ranking diagnostics explainable.",
        "final score = 1.15 × w_lex × lexical + 0.003 × structured + prior + w_text × text. Profile fit is computed but disabled.",
    ),
    "cap_hits": _node(
        "retrieve",
        "Assemble the bounded base library",
        "Preserve exact hits first, append any permissive fill, and cap the base route to its intended library size.",
        "Downstream fusion and reranking need enough recall for planning without processing an unbounded catalog slice.",
        "A selected pool with at least 150 scored hits uses the route's direct cap. Under-floor paths retain exact hits then fill to 300 for Buying/override or 500 for Browsing.",
    ),
    "raw_evidence": _node(
        "retrieve",
        "Check active-intent raw-text evidence",
        "Build a safety-recall query from non-empty messages belonging to the current intent version.",
        "Raw language can recover NLU or taxonomy misses, but pre-override and empty-disclosure text must not re-enter retrieval.",
        "current_intent_messages are joined and tokenized. The current tokenizer deduplicates before Counter, so the implemented query is effectively first-seen unique terms despite the retained frequency loop.",
    ),
    "base_only": _node(
        "retrieve",
        "Use the base route without fusion",
        "Pass the assembled base library directly to ranking when no active-intent raw query exists.",
        "Empty relaxed and raw searches add cost and no independent evidence.",
        "When raw_text is empty, relaxed_route, raw_text_route, and weighted_rrf are skipped and base_hits continue unchanged.",
    ),
    "relaxed_route": _node(
        "retrieve",
        "Run relaxed structured safety recall",
        "Search with the committed query and scoring groups while disabling hard required, category, budget, and dimension pruning.",
        "A relevant product may be missing one catalog field even when the structured interpretation is otherwise correct.",
        "The route uses normal intent weights and preferred evidence, categories=(), hard_required=False, hard_budget=False, and hard_dimension=False.",
    ),
    "raw_text_route": _node(
        "retrieve",
        "Run raw-text safety recall",
        "Search the active-intent raw query without structured hard filters.",
        "An independent lexical route protects against extraction and taxonomy errors.",
        "RAW_RECALL_WEIGHTS use lexical 2.2 with weak rating 0.03 and popularity 0.05, no structured groups or profile, and a BM25 window of at least 2,000.",
    ),
    "weighted_rrf": _node(
        "retrieve",
        "Fuse three recall routes with weighted RRF",
        "Combine strict/base, relaxed, and raw-text rankings on rank positions rather than incomparable raw scores.",
        "Rank fusion preserves independent recall signals without pretending their scoring scales are calibrated.",
        "Weighted reciprocal-rank fusion uses k=60 and weights strict/base=1.40, relaxed=0.90, raw text=1.25, removes excluded ASINs, and caps to the 300/500 library limit.",
    ),
    "qwen_rerank": _node(
        "retrieve",
        "Try the optional Qwen semantic head",
        "Use a local cross-encoder to compare the structured shopping request with the strongest retrieved products.",
        "Semantic comparison can recognize paraphrase and nuanced use-case fit after deterministic recall has protected coverage.",
        "QwenSemanticReranker lazily scores up to the first 50 hits in offline-safe mode. Disabled, unavailable, or invalid inference skips to deterministic belief weights.",
    ),
    "semantic_logits": _node(
        "retrieve",
        "Convert semantic logits to fit scores",
        "Turn each cross-encoder output logit into a bounded semantic score.",
        "A stable bounded value is needed before semantic evidence can be blended with deterministic rank position.",
        "CrossEncoder prediction bypasses its default activation, then one numerically stable sigmoid maps each raw logit to [0, 1].",
    ),
    "semantic_blend": _node(
        "retrieve",
        "Blend semantic fit with base rank",
        "Combine semantic score with a reciprocal-log discount of the candidate's deterministic rank.",
        "Semantic evidence should reorder the head without discarding the robust order produced by retrieval.",
        "For rank r, base=1/log2(r+1). combined=(1-w_semantic)×base+w_semantic×semantic, using 0.35 for Buying/override and 0.55 for Browsing.",
    ),
    "semantic_weights": _node(
        "retrieve",
        "Temperature-scale semantic head weights",
        "Convert blended head scores into positive relative ranking weights.",
        "The planner needs relative mass rather than unbounded blended scores.",
        "After sorting the semantic head, each weight is exp((combined - maximum) / 0.20).",
    ),
    "semantic_tail": _node(
        "retrieve",
        "Keep the unscored retrieval tail",
        "Append candidates outside the semantic head behind all semantically scored candidates with decaying weight.",
        "Reranking only 50 products should not erase the rest of the recall library or promote an unscored item above the head.",
        "The tail starts at 0.95 × the smallest semantic-head weight and decays by exp(-offset / 80) in original retrieval order.",
    ),
    "belief_temperature": _node(
        "retrieve",
        "Choose deterministic belief temperature",
        "Select the score scale used when semantic reranking is unavailable.",
        "Structured catalog scores and weighted-RRF scores have very different numeric ranges, so one fixed temperature would distort confidence.",
        "Normal retrieval uses 0.12. Fused RRF hits use clamp((max-min)/4, 0.0025, 0.02), detected from route reasons.",
    ),
    "belief_hits": _node(
        "retrieve",
        "Convert deterministic scores to weights",
        "Transform retrieval score differences into positive relative weights while preserving order.",
        "Dynamic Slate needs a concentration signal, but these hand-built scores are not calibrated purchase probabilities.",
        "belief_from_hits returns exp((score - maximum) / selected_temperature) for every hit.",
    ),
    "normalize": _node(
        "retrieve",
        "Normalize ranking probability mass",
        "Sort positive weights and divide by their total to create RankedCandidate values.",
        "The decision policy requires a consistent ordered distribution for expected utility and tail accounting.",
        "normalize_probabilities converts semantic or deterministic weights into RankedCandidate objects. The resulting probabilities are planning beliefs, not calibrated purchase likelihoods.",
    ),
}


_DECIDE_NODES = {
    "answer_signature": _node(
        "decide",
        "Cache catalog-predicted answers",
        "Memoize candidate-by-attribute reply signatures for counterfactual clarification branches.",
        "Dynamic planning evaluates many repeated answer partitions, so catalog prediction must be consistent and inexpensive.",
        "make_answer_signature wraps retriever.predict_reply using the disclosed set. Candidates with no additional value return the __no_additional__ sentinel.",
    ),
    "eligible_questions": _node(
        "decide",
        "Generate informative unasked questions",
        "List unresolved attributes that produce at least one informative candidate signature.",
        "A question should cost a turn only when the current candidate library can provide useful answer evidence.",
        "eligible_questions scans QUESTION_ATTRIBUTES, skips already asked attributes and exhausted other, and returns [None] on turn 10. With an empty head it offers unasked high-coverage recovery attributes.",
    ),
    "viability_filter": _node(
        "decide",
        "Filter questions by effective coverage",
        "Remove planner questions whose catalog coverage times parser reliability is below 0.10.",
        "A theoretically informative attribute is poor clarification if the catalog rarely exposes it or the live parser cannot reliably consume its answer.",
        "CatalogSignatureTransitionModel uses ATTRIBUTE_COVERAGE × PARSER_RELIABILITY. Before turn 10 it injects the first viable recovery attribute if filtering would leave no question.",
    ),
    "planning_head": _node(
        "decide",
        "Build the planning head and tail mass",
        "Represent at most 80 ranked candidates explicitly and reserve probability for products outside that head.",
        "Two-observation lookahead must remain tractable without pretending a truncated retrieval tail has zero chance of containing the target.",
        "root_state keeps up to 80 candidates, sets tail to max(natural tail, 0.20) when candidates exist, and rescales head probabilities into the remaining mass.",
    ),
    "action_space": _node(
        "decide",
        "Enumerate question and slate-size actions",
        "Build every viable ask_attribute × ranked-prefix-size action for the current turn.",
        "Showing zero, one, or several products changes immediate conversion value and the residual evidence available after a miss.",
        "Before turn 10, k spans 0..min(10, top_k, head size) for every viable question. Turn 10 bypasses lookahead and forces the full available Top-K slate with no question.",
    ),
    "hit_component": _node(
        "decide",
        "Compute expected Hit@10 value",
        "Measure the probability mass exposed by a slate under the session HitRate weight.",
        "The competition rewards finding the target anywhere in the visible Top 10.",
        "For each exposed candidate, the immediate utility includes scoring_weights.hitrate_weight, 0.50 by default; the UI preference slider may redistribute the fixed 0.80 HitRate/MRR budget.",
    ),
    "mrr_component": _node(
        "decide",
        "Compute expected reciprocal-rank value",
        "Reward exposed probability mass more strongly at earlier recommendation ranks.",
        "A target at rank one is more valuable than the same hit near the end of the slate.",
        "For one candidate at rank r, the immediate utility includes scoring_weights.mrr_weight / r, 0.30/r by default.",
    ),
    "efficiency_component": _node(
        "decide",
        "Compute expected turn-efficiency value",
        "Reward conversion earlier in the ten-turn session.",
        "A clarification is worthwhile only when its future ranking gain justifies delaying possible conversion.",
        "The per-hit efficiency term is efficiency_weight × (11-turn)/10. efficiency_weight is fixed at 0.20.",
    ),
    "immediate_value": _node(
        "decide",
        "Sum immediate action utility",
        "Combine HitRate, MRR, and efficiency utility over the ranked prefix shown now.",
        "Dynamic Slate needs the current conversion value before comparing it with possible future observations.",
        "immediate_value = gate_probability × Σ candidate_probability × (hit component + MRR component + efficiency component) across the first k candidates.",
    ),
    "answer_branches": _node(
        "decide",
        "Expand no-hit answer branches",
        "Partition surviving candidate mass by the answer signature predicted for the selected question.",
        "A clarification's value comes from how its answer changes the posterior after products shown this turn fail to convert.",
        "The transition model removes shown mass according to gate_probability, splits each remaining candidate by coverage × parser reliability, compacts typed answers to 12 branches or other to 4, and normalizes each posterior.",
    ),
    "tail_branches": _node(
        "decide",
        "Model planning-tail recovery branches",
        "Represent useful-answer and no-information outcomes for probability mass outside the explicit 80-candidate head.",
        "Ignoring the tail would make wide head slates look falsely certain and undervalue questions that can recover unseen products.",
        "Tail mass splits by the selected attribute's effective coverage. Useful recovery assigns 0.55 × next-turn rank-one utility; no-information recovery assigns zero tail value.",
    ),
    "future_value": _node(
        "decide",
        "Evaluate two future observations",
        "Recursively add probability-weighted best continuation value after each no-hit answer branch.",
        "Questions should be selected for expected downstream ranking improvement, not just immediate partition count.",
        "DynamicSlateConfig uses lookahead_steps=2: it expands observations at t and t+1, then uses the best immediate slate at the next depth as the terminal approximation.",
    ),
    "planner": _node(
        "decide",
        "Choose the best Dynamic Slate action",
        "Select the question and ranked-prefix size with maximum immediate plus future expected utility.",
        "The action must jointly optimize Hit@10, MRR, and MTTC rather than decide questioning and slate size independently.",
        "DynamicSlatePlanner scores all actions with two-observation value. Exact ties prefer an informative question and then the smaller slate.",
    ),
    "epsilon_roll": _node(
        "decide",
        "Choose exploit or attribute exploration",
        "Apply a deterministic epsilon-greedy choice after Dynamic Slate planning.",
        "Occasional exploration prevents one currently favored attribute from monopolizing clarification while keeping runs reproducible.",
        "epsilon is 0.20. A Random seed from session_id, intent_version, and turn produces the roll; exploration is disabled on turn 10, an empty ranking, or an empty concrete pool.",
    ),
    "technical_exploit": _node(
        "decide",
        "Keep the planner's technical choice",
        "Use the Dynamic Slate ask_attribute when the epsilon roll selects exploitation.",
        "Most turns should follow the action with the highest modeled competition utility.",
        "When roll >= 0.20, the raw Dynamic Slate Plan is retained without changing its recommendations, expected value, or reason.",
    ),
    "uniform_explore": _node(
        "decide",
        "Uniformly explore an eligible attribute",
        "Choose one concrete attribute uniformly from the pre-viability eligible question pool.",
        "Exploration should test genuinely informative, unasked attributes without being biased by viability weights already used by the planner.",
        "random.choice runs over non-None questions returned by eligible_questions before viability filtering. The chosen attribute replaces only ask_attribute; the planned slate remains unchanged.",
    ),
    "selected_attribute": _node(
        "decide",
        "Finalize the clarification attribute",
        "Carry forward the exploited or uniformly explored ask_attribute.",
        "The response needs one unambiguous structured attribute while preserving the Dynamic Slate recommendation decision.",
        "AttributeSelection returns mode, roll, exploration pool, and a Plan. Exploration changes only the question; recommendations and expected_value remain the planner's values.",
    ),
    "fallback_question": _node(
        "decide",
        "Guarantee a pre-final question",
        "Choose a concrete clarification before turn 10 if selection still produced no ask_attribute.",
        "The current response policy keeps learning on pre-final turns whenever a recoverable question exists.",
        "_choose_fallback_question evaluates concrete eligible attributes with the same two-step action value, preferring never-asked fields, then recovery_question is the final fallback. The slate is unchanged.",
    ),
    "sequential_gate": _node(
        "decide",
        "Pass through the planned slate",
        "Run the retained sequential-gate interface without altering Dynamic Slate output.",
        "Planning and execution must agree; a hidden post-plan truncation would invalidate expected utility.",
        "apply_sequential_gate currently ignores state and ranked candidates and returns list(plan.recommendations) unchanged. The current gate is intentionally a no-op.",
    ),
    "gate_rank1": _node(
        "decide",
        "Handle a compatibility gate change",
        "Represent the legacy branch that would expose a changed gated slate.",
        "Keeping the conditional branch visible preserves trace compatibility without claiming that current production truncates to Rank 1.",
        "This branch is skipped under the current no-op sequential gate. It runs only if a future compatible implementation returns a slate different from plan.recommendations.",
    ),
    "keep_planned": _node(
        "decide",
        "Keep the Dynamic Slate recommendations",
        "Confirm that the planner's ranked prefix is the slate passed to persistence.",
        "This is the current production branch and makes the absence of post-planner mutation explicit.",
        "When gated is false, the node records the unchanged slate count and head ASINs before response writeback.",
    ),
    "persist_turn": _node(
        "decide",
        "Persist action memory",
        "Store the shown slate, asked attribute, reply lookup, and exposure memory for the next turn.",
        "Next-turn miss feedback, duplicate suppression, and semicolon restoration depend on the exact action shown now.",
        "persist_turn predicts reply options for candidate ASINs, writes last_slate/last_ask/last_gate_open, appends asked attributes, and adds shown ASINs to shown_asins and excluded_asins.",
    ),
    "build_response": _node(
        "decide",
        "Build the official agent response",
        "Serialize message, ask_attribute, ordered parent_asin recommendations, and router token usage.",
        "The demo must finish with the same external contract used by the official evaluator.",
        "ResponseBuilder formats a short English message, emits recommendation objects containing parent_asin, and reports non-negative prompt/completion token counts. A final pre-turn-10 recovery guard supplies a question if needed.",
    ),
}


_POSITIONS = {
    "understand": {
        "prior_miss": {"x": 600, "y": 55},
        "turn_reset": {"x": 600, "y": 145},
        "understand_mode": {"x": 600, "y": 235},
        "nlu_attempt": {"x": 350, "y": 325},
        "casefold": {"x": 350, "y": 415},
        "color_map": {"x": 180, "y": 505},
        "material_map": {"x": 520, "y": 505},
        "color_verify": {"x": 180, "y": 595},
        "material_verify": {"x": 520, "y": 595},
        "merge_rewrite": {"x": 350, "y": 685},
        "category_l1": {"x": 350, "y": 775},
        "category_l2": {"x": 350, "y": 865},
        "category_l3": {"x": 350, "y": 955},
        "category_cap": {"x": 350, "y": 1045},
        "attribute_llm": {"x": 350, "y": 1135},
        "slot_grounding": {"x": 350, "y": 1225},
        "repair_1": {"x": 180, "y": 1315},
        "repair_2": {"x": 350, "y": 1405},
        "repair_3": {"x": 520, "y": 1495},
        "disclosure": {"x": 350, "y": 1585},
        "regex_extract": {"x": 900, "y": 505},
        "colon_restore": {"x": 900, "y": 865},
        "turn_delta": {"x": 600, "y": 1685},
        "active_intent_evidence": {"x": 600, "y": 1785},
        "empty_disclosure_gate": {"x": 600, "y": 1885},
    },
    "router": {
        "committed_intent": {"x": 600, "y": 55},
        "override_l1": {"x": 600, "y": 145},
        "override_l2": {"x": 600, "y": 235},
        "strong_override_fallback": {"x": 600, "y": 325},
        "replace_delta": {"x": 150, "y": 425},
        "drop_slots": {"x": 390, "y": 425},
        "override_gate_cleanup": {"x": 270, "y": 535},
        "probe_override": {"x": 270, "y": 645},
        "intention_override": {"x": 270, "y": 755},
        "probe_before": {"x": 930, "y": 425},
        "apply_delta": {"x": 930, "y": 535},
        "probe_after": {"x": 930, "y": 645},
        "pool_ratio": {"x": 930, "y": 755},
        "route_llm": {"x": 930, "y": 855},
        "buying": {"x": 800, "y": 965},
        "browsing": {"x": 1060, "y": 965},
        "failsafe": {"x": 600, "y": 1150},
    },
    "retrieve": {
        "select_pool": {"x": 880, "y": 55},
        "slot_groups": {"x": 880, "y": 155},
        "rewrite_query": {"x": 880, "y": 255},
        "routing": {"x": 880, "y": 355},
        "lexical_in_pool": {"x": 520, "y": 470},
        "score_exact": {"x": 520, "y": 580},
        "hybrid_search": {"x": 1240, "y": 580},
        "bm25_score": {"x": 160, "y": 780},
        "required_score": {"x": 400, "y": 780},
        "preferred_score": {"x": 640, "y": 780},
        "category_score": {"x": 880, "y": 780},
        "budget_score": {"x": 400, "y": 900},
        "dimension_score": {"x": 640, "y": 900},
        "exclusion_score": {"x": 880, "y": 900},
        "structured_subtotal": {"x": 640, "y": 1030},
        "rating_prior": {"x": 1160, "y": 780},
        "popularity_prior": {"x": 1160, "y": 900},
        "catalog_prior": {"x": 1160, "y": 1030},
        "title_text_fit": {"x": 1440, "y": 780},
        "details_text_fit": {"x": 1440, "y": 900},
        "description_text_fit": {"x": 1440, "y": 1030},
        "soft_text_fit": {"x": 1440, "y": 1150},
        "profile_diagnostic": {"x": 1680, "y": 780},
        "weighted_score": {"x": 880, "y": 1300},
        "cap_hits": {"x": 880, "y": 1420},
        "raw_evidence": {"x": 880, "y": 1540},
        "base_only": {"x": 360, "y": 1680},
        "relaxed_route": {"x": 880, "y": 1680},
        "raw_text_route": {"x": 1400, "y": 1680},
        "weighted_rrf": {"x": 880, "y": 1820},
        "qwen_rerank": {"x": 880, "y": 1940},
        "semantic_logits": {"x": 360, "y": 2080},
        "semantic_blend": {"x": 360, "y": 2200},
        "semantic_weights": {"x": 360, "y": 2320},
        "semantic_tail": {"x": 560, "y": 2440},
        "belief_temperature": {"x": 1400, "y": 2080},
        "belief_hits": {"x": 1400, "y": 2320},
        "normalize": {"x": 880, "y": 2580},
    },
    "decide": {
        "answer_signature": {"x": 900, "y": 55},
        "eligible_questions": {"x": 900, "y": 155},
        "viability_filter": {"x": 900, "y": 265},
        "planning_head": {"x": 900, "y": 375},
        "action_space": {"x": 900, "y": 495},
        "hit_component": {"x": 180, "y": 680},
        "mrr_component": {"x": 500, "y": 680},
        "efficiency_component": {"x": 820, "y": 680},
        "answer_branches": {"x": 1260, "y": 680},
        "tail_branches": {"x": 1580, "y": 680},
        "immediate_value": {"x": 500, "y": 880},
        "future_value": {"x": 1420, "y": 880},
        "planner": {"x": 900, "y": 1060},
        "epsilon_roll": {"x": 900, "y": 1190},
        "technical_exploit": {"x": 500, "y": 1340},
        "uniform_explore": {"x": 1300, "y": 1340},
        "selected_attribute": {"x": 900, "y": 1490},
        "fallback_question": {"x": 900, "y": 1610},
        "sequential_gate": {"x": 900, "y": 1730},
        "gate_rank1": {"x": 500, "y": 1870},
        "keep_planned": {"x": 1300, "y": 1870},
        "persist_turn": {"x": 900, "y": 2010},
        "build_response": {"x": 900, "y": 2130},
    },
}


_EDGES = {
    "understand": (
        ("prior_miss", "turn_reset"),
        ("turn_reset", "understand_mode"),
        ("understand_mode", "nlu_attempt", "nlu"),
        ("understand_mode", "regex_extract", "regex"),
        ("nlu_attempt", "casefold"),
        ("nlu_attempt", "regex_extract", "all three complete attempts fail"),
        ("casefold", "color_map"),
        ("casefold", "material_map"),
        ("color_map", "color_verify"),
        ("material_map", "material_verify"),
        ("color_verify", "merge_rewrite"),
        ("material_verify", "merge_rewrite"),
        ("merge_rewrite", "category_l1"),
        ("category_l1", "category_l2", "continue"),
        ("category_l1", "category_cap", "stop, empty, error, or no children"),
        ("category_l2", "category_l3", "continue"),
        ("category_l2", "category_cap", "stop, empty, error, or no children"),
        ("category_l3", "category_cap"),
        ("category_cap", "attribute_llm"),
        ("attribute_llm", "slot_grounding"),
        ("slot_grounding", "repair_1", "failed fields"),
        ("slot_grounding", "disclosure", "all grounded"),
        ("repair_1", "repair_2", "failures remain"),
        ("repair_1", "disclosure", "grounded or repair call fails"),
        ("repair_2", "repair_3", "failures remain"),
        ("repair_2", "disclosure", "grounded or repair call fails"),
        ("repair_3", "disclosure"),
        ("disclosure", "turn_delta"),
        ("regex_extract", "colon_restore", "non-empty regex extract with no constraints"),
        ("regex_extract", "turn_delta", "colon restore not eligible"),
        ("colon_restore", "turn_delta"),
        ("turn_delta", "active_intent_evidence"),
        ("active_intent_evidence", "empty_disclosure_gate"),
    ),
    "router": (
        ("committed_intent", "override_l1", "prior intent exists"),
        ("committed_intent", "probe_before", "no committed intent"),
        ("override_l1", "replace_delta", "level 1"),
        ("override_l1", "override_l2", "not accepted"),
        ("override_l2", "drop_slots", "level 2"),
        ("override_l2", "strong_override_fallback", "LLM level 0"),
        ("strong_override_fallback", "drop_slots", "match maps only to level 2"),
        ("strong_override_fallback", "probe_before", "no match"),
        ("replace_delta", "override_gate_cleanup"),
        ("drop_slots", "override_gate_cleanup"),
        ("override_gate_cleanup", "probe_override"),
        ("probe_override", "intention_override"),
        ("intention_override", "failsafe"),
        ("probe_before", "apply_delta"),
        ("apply_delta", "probe_after"),
        ("probe_after", "pool_ratio"),
        ("pool_ratio", "route_llm"),
        ("route_llm", "buying", "buying"),
        ("route_llm", "browsing", "browsing or failed attempts"),
        ("buying", "failsafe"),
        ("browsing", "failsafe"),
    ),
    "retrieve": (
        ("select_pool", "slot_groups"),
        ("slot_groups", "rewrite_query"),
        ("rewrite_query", "routing"),
        ("routing", "lexical_in_pool", "selected pool non-empty"),
        ("routing", "hybrid_search", "selected pool missing or empty"),
        ("lexical_in_pool", "score_exact"),
        ("score_exact", "hybrid_search", "fewer than 150 scored hits"),
        ("score_exact", "bm25_score"),
        ("score_exact", "required_score"),
        ("score_exact", "rating_prior"),
        ("score_exact", "title_text_fit"),
        ("score_exact", "profile_diagnostic"),
        ("hybrid_search", "bm25_score"),
        ("hybrid_search", "required_score"),
        ("hybrid_search", "rating_prior"),
        ("hybrid_search", "title_text_fit"),
        ("hybrid_search", "profile_diagnostic"),
        ("required_score", "preferred_score"),
        ("preferred_score", "category_score"),
        ("required_score", "budget_score"),
        ("preferred_score", "dimension_score"),
        ("category_score", "exclusion_score"),
        ("budget_score", "structured_subtotal"),
        ("dimension_score", "structured_subtotal"),
        ("exclusion_score", "structured_subtotal"),
        ("rating_prior", "popularity_prior"),
        ("popularity_prior", "catalog_prior"),
        ("title_text_fit", "details_text_fit"),
        ("details_text_fit", "description_text_fit"),
        ("description_text_fit", "soft_text_fit"),
        ("bm25_score", "weighted_score"),
        ("structured_subtotal", "weighted_score"),
        ("catalog_prior", "weighted_score"),
        ("soft_text_fit", "weighted_score"),
        ("profile_diagnostic", "weighted_score"),
        ("weighted_score", "cap_hits"),
        ("cap_hits", "raw_evidence"),
        ("raw_evidence", "base_only", "no raw evidence"),
        ("raw_evidence", "relaxed_route", "raw evidence present"),
        ("raw_evidence", "raw_text_route", "raw evidence present"),
        ("cap_hits", "weighted_rrf", "base route"),
        ("relaxed_route", "weighted_rrf"),
        ("raw_text_route", "weighted_rrf"),
        ("base_only", "qwen_rerank"),
        ("weighted_rrf", "qwen_rerank"),
        ("qwen_rerank", "semantic_logits", "valid semantic head"),
        ("qwen_rerank", "belief_temperature", "unavailable or invalid"),
        ("semantic_logits", "semantic_blend"),
        ("semantic_blend", "semantic_weights"),
        ("semantic_weights", "semantic_tail"),
        ("semantic_tail", "normalize"),
        ("belief_temperature", "belief_hits"),
        ("belief_hits", "normalize"),
    ),
    "decide": (
        ("answer_signature", "eligible_questions"),
        ("eligible_questions", "viability_filter"),
        ("viability_filter", "planning_head"),
        ("planning_head", "action_space"),
        ("action_space", "hit_component"),
        ("action_space", "mrr_component"),
        ("action_space", "efficiency_component"),
        ("hit_component", "immediate_value"),
        ("mrr_component", "immediate_value"),
        ("efficiency_component", "immediate_value"),
        ("action_space", "answer_branches"),
        ("action_space", "tail_branches"),
        ("answer_branches", "future_value"),
        ("tail_branches", "future_value"),
        ("immediate_value", "planner"),
        ("future_value", "planner"),
        ("planner", "epsilon_roll"),
        ("eligible_questions", "epsilon_roll", "pre-viability exploration pool"),
        ("epsilon_roll", "technical_exploit", "roll >= 0.20"),
        ("epsilon_roll", "uniform_explore", "roll < 0.20"),
        ("technical_exploit", "selected_attribute"),
        ("uniform_explore", "selected_attribute"),
        ("selected_attribute", "fallback_question"),
        ("fallback_question", "sequential_gate"),
        ("sequential_gate", "gate_rank1", "compatibility change"),
        ("sequential_gate", "keep_planned", "current no-op"),
        ("gate_rank1", "persist_turn"),
        ("keep_planned", "persist_turn"),
        ("persist_turn", "build_response"),
    ),
}


_STAGE_COPY = {
    "understand": (
        "Prepare a turn-only observation: apply miss feedback, select NLU or "
        "regex, ground and repair current-message evidence, then stage a delta "
        "without committing active intent."
    ),
    "router": (
        "Own committed-state writeback: choose full replacement, partial "
        "replacement, or accumulation; build strict and match-or-unknown pools; "
        "then select override, Buying, or Browsing routing."
    ),
    "retrieve": (
        "Select the strict or lenient seed, score deterministic catalog "
        "evidence, protect recall with hybrid and three-route fusion, then use "
        "semantic or deterministic ranking weights."
    ),
    "decide": (
        "Jointly plan clarification and slate size from Hit@10, MRR, and "
        "efficiency with two-observation lookahead, apply epsilon attribute "
        "selection, persist memory, and build the official response."
    ),
}

_TITLES = {
    "understand": "Understand · prepare a grounded turn-only delta",
    "router": "Intent Router · replace or accumulate, then choose a route",
    "retrieve": "Retrieve + Rank · score, recover recall, and normalize belief",
    "decide": "Decide · optimize the question and recommendation slate",
}

_VIEW_BOXES = {
    "understand": "0 0 1200 1990",
    "router": "0 0 1200 1255",
    "retrieve": "0 0 1840 2700",
    "decide": "0 0 1720 2220",
}

_NODES_BY_STAGE = {
    "understand": _UNDERSTAND_NODES,
    "router": _ROUTER_NODES,
    "retrieve": _RETRIEVE_NODES,
    "decide": _DECIDE_NODES,
}

WORKFLOW_SCHEMA: dict[str, dict[str, Any]] = {
    stage: {
        "stage": stage,
        "title": _TITLES[stage],
        "summary": _STAGE_COPY[stage],
        "viewBox": _VIEW_BOXES[stage],
        "positions": _POSITIONS[stage],
        "edges": _EDGES[stage],
        "nodes": _NODES_BY_STAGE[stage],
    }
    for stage in STAGE_ORDER
}


def _validate_schema() -> None:
    seen: set[str] = set()
    for stage in STAGE_ORDER:
        graph = WORKFLOW_SCHEMA[stage]
        nodes = graph["nodes"]
        positions = graph["positions"]
        if graph["stage"] != stage or set(nodes) != set(positions):
            raise ValueError(f"Workflow graph mismatch in stage {stage!r}")
        for node_id, metadata in nodes.items():
            if node_id in seen:
                raise ValueError(f"Duplicate workflow node id {node_id!r}")
            seen.add(node_id)
            if set(metadata) != NODE_FIELDS:
                raise ValueError(f"Unexpected metadata fields for {node_id!r}")
            if metadata["stage"] != stage or not all(metadata.values()):
                raise ValueError(f"Invalid metadata for {node_id!r}")
        for edge in graph["edges"]:
            if len(edge) not in {2, 3}:
                raise ValueError(f"Invalid {stage} edge arity: {edge!r}")
            source, target = edge[0], edge[1]
            if source not in nodes or target not in nodes:
                raise ValueError(
                    f"Invalid {stage} edge endpoint: {source!r} -> {target!r}"
                )
            if len(edge) == 3 and not str(edge[2]).strip():
                raise ValueError(f"Empty {stage} edge label: {source!r} -> {target!r}")


_validate_schema()

NODE_METADATA: dict[str, dict[str, str]] = {
    node_id: dict(metadata)
    for stage in STAGE_ORDER
    for node_id, metadata in WORKFLOW_SCHEMA[stage]["nodes"].items()
}

STAGE_BLURBS: dict[str, str] = {
    stage: str(WORKFLOW_SCHEMA[stage]["summary"]) for stage in STAGE_ORDER
}


def workflow_graph_props() -> dict[str, dict[str, Any]]:
    """Return JSON-safe graph props without duplicating canonical metadata."""

    return {
        stage: deepcopy(
            {
                "stage": graph["stage"],
                "title": graph["title"],
                "viewBox": graph["viewBox"],
                "positions": graph["positions"],
                "edges": [list(edge[:2]) for edge in graph["edges"]],
            }
        )
        for stage, graph in WORKFLOW_SCHEMA.items()
    }


def mermaid_flowchart(stage: str) -> str:
    """Return the canonical mermaid flowchart for one production stage."""

    if stage not in WORKFLOW_SCHEMA:
        raise KeyError(f"Unknown workflow stage {stage!r}")
    graph = WORKFLOW_SCHEMA[stage]
    lines = ["flowchart TD"]
    for node_id, metadata in graph["nodes"].items():
        label = str(metadata["label"]).replace('"', "#quot;")
        lines.append(f'    {node_id}["{label}"]')
    for edge in graph["edges"]:
        source, target = edge[0], edge[1]
        if len(edge) == 3:
            label = str(edge[2]).replace('"', "#quot;")
            lines.append(f'    {source} -- "{label}" --> {target}')
        else:
            lines.append(f"    {source} --> {target}")
    return "\n".join(lines) + "\n"


def mermaid_marker(stage: str) -> str:
    """HTML comment used to pin generated mermaid into English READMEs."""

    return f"<!-- workflow-schema:{stage} -->"


def extract_marked_mermaid(markdown: str, stage: str) -> str:
    """Return the mermaid source pinned by ``workflow-schema:<stage>``."""

    marker = mermaid_marker(stage)
    start = markdown.find(marker)
    if start < 0:
        raise ValueError(f"Missing {marker} in markdown")
    fence = markdown.find("```mermaid", start)
    if fence < 0:
        raise ValueError(f"Missing mermaid fence after {marker}")
    body_start = markdown.find("\n", fence)
    body_end = markdown.find("```", body_start + 1)
    if body_start < 0 or body_end < 0:
        raise ValueError(f"Unclosed mermaid fence after {marker}")
    return markdown[body_start + 1 : body_end].strip() + "\n"


__all__ = [
    "NODE_FIELDS",
    "NODE_METADATA",
    "STAGE_BLURBS",
    "STAGE_ORDER",
    "WORKFLOW_SCHEMA",
    "extract_marked_mermaid",
    "mermaid_flowchart",
    "mermaid_marker",
    "workflow_graph_props",
]
