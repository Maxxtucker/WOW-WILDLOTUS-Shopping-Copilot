"""Purpose: English inspector copy for every circuit node.

Input: module READMEs and the functions behind each progress node.
Output: id → function / implementation / stage / label.
Role: demo UI only. Does not change pipeline behavior.
"""

from __future__ import annotations

from typing import Any

NODE_CATALOG: dict[str, dict[str, Any]] = {
    "casefold": {
        "stage": "understand",
        "label": "Normalize text",
        "purpose": (
            "Standardize the shopper’s message before any color, material, or "
            "attribute matching."
        ),
        "why": (
            "The same request should behave identically whether the shopper writes "
            "'BLACK SHOES', 'Black Shoes', or 'black shoes'. This prevents "
            "capitalization from changing downstream matching."
        ),
        "this_turn": (
            "Input: 'I want shoes'\nNormalized: 'i want shoes'\n\nResult: the message is ready "
            "for downstream alias lookup and category checks."
        ),
        "how_it_works": (
            "This node lowercases the raw sentence once and passes the same folded text to the "
            "color and material maps. Implementation: Python str.casefold()."
        ),
        "function": (
            "Normalize the shopper message to lowercase before any alias lookup. "
            "This is the single shared start of rewrite."
        ),
        "implementation": (
            "rewrite_for_nlu calls message.casefold() and emits the folded string. "
            "Color and material maps are case-insensitive, so every later n-gram "
            "runs on this text. An empty fold skips the rest of rewrite."
        ),
    },
    "color_map": {
        "stage": "understand",
        "label": "Normalize color",
        "purpose": (
            "Convert different ways of describing a color into the catalog’s standard color vocabulary."
        ),
        "why": (
            "A shopper may say 'navy' while the catalog stores 'blue'. Without normalization, the "
            "right product could be missed."
        ),
        "this_turn": (
            "Input: 'i want shoes'\nDetected colors: none\n\nAction: continue without changing the message."
        ),
        "how_it_works": (
            "Scans short phrases against the color alias table and keeps the longest valid match. "
            "Technical: longest-match 1–4 token n-gram scan."
        ),
        "function": (
            "Find color phrases in the folded sentence and map them onto the "
            "closed catalog color set (for example navy → blue)."
        ),
        "implementation": (
            "A longest-match scan over 1–4 token n-grams reads the committed "
            "color alias JSON in parallel with the material map. Jewelry metals "
            "(gold, silver, platinum) are not rewritten to yellow or white. "
            "Hits still need the optional LLM word-class gate."
        ),
    },
    "material_map": {
        "stage": "understand",
        "label": "Normalize material",
        "purpose": (
            "Map different material descriptions into a consistent catalog material."
        ),
        "why": (
            "Product text and shopper language often use different forms, such as 'cordovan leather' "
            "and 'cordovan'."
        ),
        "this_turn": (
            "Input: 'i want shoes'\nDetected materials: none\n\nAction: continue without changing the message."
        ),
        "how_it_works": (
            "Uses the same longest-match strategy as color, but against the material alias table. "
            "Technical: longest-match 1–5 token n-gram scan."
        ),
        "function": (
            "Find material phrases in the same folded sentence and map them "
            "onto the closed material set."
        ),
        "implementation": (
            "Same longest-match design as color, with 1–5 token n-grams and "
            "the material alias table. A span that hits both maps becomes a "
            "combined “color material” rewrite token at merge."
        ),
    },
    "color_verify": {
        "stage": "understand",
        "label": "Validate ambiguous color",
        "purpose": (
            "Check ambiguous alias matches before changing the shopper’s meaning."
        ),
        "why": (
            "A dictionary match alone can be wrong; a common adjective should not be turned into a "
            "color by accident."
        ),
        "this_turn": (
            "Status: skipped\nReason: no ambiguous color alias required semantic validation.\n\nResult: "
            "no model call was needed."
        ),
        "how_it_works": (
            "When a color rewrite is ambiguous, a lightweight model checks whether both sides truly "
            "describe colors."
        ),
        "function": (
            "Keep a color hit only when both the source phrase and the "
            "replacement are color words."
        ),
        "implementation": (
            "An optional Ollama word-class gate on each color pair. This drops "
            "accidental aliases such as easy → brown. Regex mode and a missing "
            "NLU client skip the gate and keep the map hits unchanged."
        ),
    },
    "material_verify": {
        "stage": "understand",
        "label": "Validate ambiguous material",
        "purpose": (
            "Verify uncertain material mappings before they are applied."
        ),
        "why": (
            "A normal word or phrase should not be treated as a material unless the model confirms it."
        ),
        "this_turn": (
            "Status: skipped\nReason: no material alias required semantic validation.\n\nResult: no model "
            "call was needed."
        ),
        "how_it_works": (
            "Runs the same precision gate on material aliases, but only when a candidate match is uncertain."
        ),
        "function": (
            "Keep a material hit only when both sides of the pair are material words."
        ),
        "implementation": (
            "The material-side twin of the color gate, run in parallel. Surviving "
            "hits are the only replacements merge_rewrite will apply."
        ),
    },
    "merge_rewrite": {
        "stage": "understand",
        "label": "Build normalized query",
        "purpose": (
            "Create a clean, NLU-friendly version of the shopper’s request while preserving the original message."
        ),
        "why": (
            "Downstream NLU sees standardized terms, while the original phrasing remains available for context "
            "and debugging."
        ),
        "this_turn": (
            "Original: 'I want shoes'\nNormalized: 'I want shoes'\n\nChanges: none. No rewrite was necessary."
        ),
        "how_it_works": (
            "Applies only validated color and material replacements in span order; the original text is kept untouched."
        ),
        "function": (
            "Apply kept color and material replacements and produce the sentence "
            "used by attribute NLU."
        ),
        "implementation": (
            "Replacements are written back onto the folded string in span order. "
            "The original message is stored on the session unchanged. Category "
            "walk still reads that original sentence; only attribute extract "
            "uses the rewrite."
        ),
    },
    "category_l1": {
        "stage": "understand",
        "label": "Find broad product family",
        "purpose": (
            "Identify the broad catalog branch that can contain the product the shopper is asking for."
        ),
        "why": (
            "Category routing keeps obviously unrelated product types out of retrieval. If the shopper asks for shoes, "
            "gloves or jewelry should not compete with them."
        ),
        "this_turn": (
            "Input: 'I want shoes'\nTask: find the broad product family\n\nStatus: category model did not return a valid result\nResult: no L1 category was selected."
        ),
        "how_it_works": (
            "Starts at the top of the catalog category tree and asks the category model to select only broad branches supported by the shopper's wording."
        ),
        "function": (
            "Choose Amazon L1 roots that the original message actually supports."
        ),
        "implementation": (
            "category_tree loads the fold-pruned three-level tree (promo "
            "merchandising children omitted) and asks the category LLM over L1 "
            "roots. An empty id list stops the walk; no extra LLM round starts."
        ),
    },
    "category_l2": {
        "stage": "understand",
        "label": "Narrow to product type",
        "purpose": (
            "Refine the broad product family into a more specific type."
        ),
        "why": (
            "Narrower categories reduce the number of irrelevant products before retrieval and improve ranking precision."
        ),
        "this_turn": (
            "Status: skipped\nReason: category L1 did not produce a valid parent category.\nResult: no L2 model call was needed."
        ),
        "how_it_works": (
            "Looks only at children of the selected L1 category and chooses the most relevant supported subcategory."
        ),
        "function": "Walk selected L1 children into L2 labels.",
        "implementation": (
            "Selected L1 nodes concatenate their children; the LLM picks among "
            "those children only. category_scope drops L2+ branches that add "
            "kids, gender, or age the shopper did not state."
        ),
    },
    "category_l3": {
        "stage": "understand",
        "label": "Resolve final catalog category",
        "purpose": (
            "Refine the product type to the most specific category supported by the shopper's request."
        ),
        "why": (
            "The final category becomes a strong retrieval constraint, helping prevent category leakage into unrelated products."
        ),
        "this_turn": (
            "Status: skipped\nReason: no valid L2 category was available to refine.\nResult: no L3 model call was made."
        ),
        "how_it_works": (
            "Traverses one more level down the catalog tree, but only within the selected L2 branch."
        ),
        "function": "Walk selected L2 children into L3 labels.",
        "implementation": (
            "Same child-concat walk as L2. A layer with no children ends the "
            "tree. Session category is not committed here; turn_delta only stores "
            "the extract."
        ),
    },
    "category_cap": {
        "stage": "understand",
        "label": "Limit category ambiguity",
        "purpose": (
            "When category detection is still too broad, keep only the five most plausible catalog categories."
        ),
        "why": (
            "A vague request can activate many related categories. Capping them prevents retrieval from becoming too broad and noisy."
        ),
        "this_turn": (
            "Candidate categories: 0\nStatus: skipped\nReason: there were no category candidates to reduce."
        ),
        "how_it_works": (
            "Scores the remaining valid category candidates and retains at most five that best cover the shopper's stated product type."
        ),
        "function": (
            "When this turn still has more than five category tags, keep the "
            "five closest tags that can contain the shopper's item."
        ),
        "implementation": (
            "Safety net after identity emit. The model must return five tags "
            "that fold_category-match the allowed list and cover cited product "
            "types. Invalid JSON retries up to three times. After three misses, "
            "keep cited tags plus the highest slot_stats.df counts in that pool."
        ),
    },
    "attribute_llm": {
        "stage": "understand",
        "label": "Extract shopping constraints",
        "purpose": (
            "Turn the shopper's request into structured requirements that retrieval and ranking can use."
        ),
        "why": (
            "Structured constraints let the agent distinguish hard requirements from softer preferences instead of treating the entire request as one keyword string."
        ),
        "this_turn": (
            "Input: 'I want shoes'\nStatus: attribute extraction failed\nStructured constraints: none."
        ),
        "how_it_works": (
            "A local model extracts typed constraints such as category, color, material, size, budget, and preference strength. Attribute-specific handlers then validate and normalize each value."
        ),
        "function": (
            "Extract typed slots — attribute, value, hardness, and cite spans — "
            "from the rewritten sentence."
        ),
        "implementation": (
            "Ollama returns JSON constraints. Each attribute has its own handler "
            "(color, material, size, budget, …) for cite-vs-classify and alias "
            "policy. Regex mode skips this model and uses classify.py instead."
        ),
    },
    "repair_1": {
        "stage": "understand",
        "label": "Retry structured extraction · Attempt 1",
        "purpose": (
            "Retry constraint extraction when the model does not return a valid structured result."
        ),
        "why": (
            "A malformed model response should not break the shopping session. This gives the agent a controlled chance to recover automatically."
        ),
        "this_turn": (
            "Status: skipped\nReason: the initial attribute extraction was already valid.\nResult: no retry was needed."
        ),
        "how_it_works": (
            "Repeats the same structured extraction request using the same output schema. A valid result ends the retry chain immediately."
        ),
        "function": "First retry when the attribute JSON is missing or unusable.",
        "implementation": (
            "hybrid_extract allows three NLU attempts with the same schema. "
            "This is attempt 2. A valid payload ends the loop; otherwise repair 2 runs."
        ),
    },
    "repair_2": {
        "stage": "understand",
        "label": "Retry structured extraction · Attempt 2",
        "purpose": (
            "Make a second recovery attempt if the previous structured extraction is still invalid."
        ),
        "why": (
            "A bounded retry sequence improves robustness without allowing repeated model calls to continue indefinitely."
        ),
        "this_turn": (
            "Status: skipped\nReason: Attempt 1 was not needed, so no second retry was required.\nResult: no additional model call was made."
        ),
        "how_it_works": (
            "Uses the same constraint schema as the first extraction attempt. If the result is valid, recovery stops; otherwise the agent proceeds to the final retry."
        ),
        "function": "Second retry of the attribute JSON extract.",
        "implementation": (
            "Same client and schema as attribute_llm. Still no override keys — "
            "intention routing does not live in understand."
        ),
    },
    "repair_3": {
        "stage": "understand",
        "label": "Final recovery attempt · Attempt 3",
        "purpose": (
            "Make the final model-based recovery attempt before switching to the deterministic extractor."
        ),
        "why": (
            "The agent gets several chances to recover from malformed model output, but always has a deterministic path forward instead of failing the whole turn."
        ),
        "this_turn": (
            "Status: skipped\nReason: earlier recovery attempts were not needed because extraction was already usable.\nResult: final retry and fallback were not needed."
        ),
        "how_it_works": (
            "This is the last bounded model retry. If it still fails, the pipeline hands extraction to the deterministic rule-based classifier."
        ),
        "function": "Last model attempt before regex fallback.",
        "implementation": (
            "If this call is None or invalid, hybrid_extract falls back to "
            "classify.py. Colon-fallback can still parse a last-resort constraint."
        ),
    },
    "disclosure": {
        "stage": "understand",
        "label": "Validate the turn",
        "purpose": (
            "Confirm that this turn contains usable shopping information before updating the shopper's active preferences."
        ),
        "why": (
            "Not every shopper message changes the search. Greetings, acknowledgements, or empty turns should not create fake constraints or overwrite useful state."
        ),
        "this_turn": (
            "Status: skipped\nReason: this turn already contained a valid shopping constraint.\nResult: the turn remains eligible for state update."
        ),
        "how_it_works": (
            "After category and attribute extraction, the node checks whether the turn contains any usable shopping signal. If neither is present, the turn is marked empty instead of modifying the session."
        ),
        "function": (
            "After category+attribute, void the delta when the utterance "
            "disclosed neither."
        ),
        "implementation": (
            "A local JSON call sees the original sentence plus this turn's "
            "category and attribute rows. {\"empty\": true} clears the extract "
            "so turn_delta is None. Invalid JSON retries up to three times; "
            "three misses keep the delta (fail-open). Regex mode skips this node."
        ),
    },
    "turn_delta": {
        "stage": "understand",
        "label": "Stage this turn's understanding",
        "purpose": (
            "Package everything understood from the current message into one temporary turn update."
        ),
        "why": (
            "The agent does not immediately overwrite the shopper's existing preferences. It first stages the new information so the Intent Router can decide whether to add, replace, or ignore it. This prevents a follow-up such as 'more breathable' from erasing earlier requirements such as 'running shoes under $150.'"
        ),
        "this_turn": (
            "Extraction path: Rule-based (regex)\nDetected constraint\nType: Use case\nSource phrase: \"running shoes for jogging\"\nStatus: valid shopping turn\nNext: ready for Intent Router."
        ),
        "how_it_works": (
            "Stores the current turn's extracted category and constraints separately from the committed session state. The next stage decides whether each piece of information should be added, replaced, or ignored."
        ),
        "function": (
            "Write this turn’s extract onto SessionState.turn_delta and stop. "
            "Nothing is committed to the live constraint set here."
        ),
        "implementation": (
            "observe in coordinator.py stores source, category, slots, and empty. "
            "The intention router’s replace/accumulate writeback is what later "
            "upserts slots. There is no turn==1 special case and no evaluator "
            "Buying/Browsing label."
        ),
    },
    "override_l1": {
        "stage": "router",
        "label": "Override L1",
        "purpose": (
            "Decide whether the shopper has changed their mind and wants a full reset of the current intent."
        ),
        "why": (
            "When a shopper clearly switches goals, the agent should not keep old constraints alive. A new intent should replace the previous shopping state instead of accumulating stale requirements."
        ),
        "this_turn": (
            "Status: skipped\nReason: there was no prior intent to reset.\nResult: the router kept the current state instead of clearing it."
        ),
        "how_it_works": (
            "Checks whether the turn is a full reset by asking whether every committed category and attribute should be discarded."
        ),
        "function": (
            "Decide whether this utterance discards every committed category "
            "and every committed attribute."
        ),
        "implementation": (
            "A local JSON call returns {\"full\": true|false}. Skipped when no "
            "committed prior intent exists. True clears all typed constraints "
            "then apply_delta and opens the conversion gate."
        ),
    },
    "override_l2": {
        "stage": "router",
        "label": "Override L2",
        "purpose": (
            "Decide whether only some committed preferences should be replaced rather than added."
        ),
        "why": (
            "A shopper may keep the same broad intent but narrow or change a few details, such as switching from black to blue while keeping running shoes."
        ),
        "this_turn": (
            "Status: skipped\nReason: the turn did not require a partial replacement.\nResult: the router kept the existing preferences and accumulated the new details."
        ),
        "how_it_works": (
            "Checks whether the turn should replace only the attributes that changed, while leaving unrelated preferences intact."
        ),
        "function": (
            "If not a full reset, decide whether some committed preferences "
            "are being replaced rather than added."
        ),
        "implementation": (
            "A second JSON call returns {\"override\": true|false}. True drops "
            "only the attribute names present on this turn’s delta, then "
            "apply_delta, and opens the conversion gate. Adding alternatives "
            "is false and accumulates."
        ),
    },
    "replace_delta": {
        "stage": "router",
        "label": "Replace",
        "purpose": (
            "Clear all prior needs when the shopper clearly changes roles or product family."
        ),
        "why": (
            "If the shopper says 'actually I need a handbag instead', the router must not carry old shoe constraints forward."
        ),
        "this_turn": (
            "Status: skipped\nReason: this turn did not trigger a full reset.\nResult: old intent was not cleared."
        ),
        "how_it_works": (
            "Clears all typed constraints and then applies the current turn's delta to the replacement state."
        ),
        "function": "Clear all typed constraints, then apply this turn’s delta (L1).",
        "implementation": (
            "clear_typed then apply_delta. Opens the conversion gate and clears "
            "last_ranked. Skipped on L2 and accumulate."
        ),
    },
    "drop_slots": {
        "stage": "router",
        "label": "Drop slots",
        "purpose": (
            "Replace only the preferences that changed, while keeping the rest of the shopper's intent intact."
        ),
        "why": (
            "This keeps the shopper's older requirements alive when the new message is only a refinement, such as changing black to blue without dropping running shoes or budget."
        ),
        "this_turn": (
            "Status: skipped\nReason: no partial replacement was triggered.\nResult: no fields were removed before accumulation."
        ),
        "how_it_works": (
            "Drops only the specific attribute names in the current turn's delta, then applies the updated values."
        ),
        "function": "Drop committed fields that appear in this turn’s delta (L2).",
        "implementation": (
            "drop_typed uses delta attribute names, then apply_delta writes the "
            "new values. Opens the conversion gate. Skipped on L1 and accumulate."
        ),
    },
    "probe_override": {
        "stage": "router",
        "label": "Probe once",
        "purpose": (
            "Measure the replacement state once when the shopper fully changed intent, without comparing it to the older state."
        ),
        "why": (
            "A full reset is not comparable to the old pool because the product family itself changed. The router should measure only the new search space."
        ),
        "this_turn": (
            "Status: skipped\nReason: this turn did not trigger a full override.\nResult: the router did not create a one-off replacement probe."
        ),
        "how_it_works": (
            "Builds the hard exact ASIN pool once, on the replaced state."
        ),
        "function": (
            "Build the hard exact ASIN pool once, on the replaced state."
        ),
        "implementation": (
            "exact_pool_for_state intersects hard signatures (OR inside an "
            "attribute, AND across groups), then applies hard budget / LWH / "
            "weight filters. Soft slots never enter this set. Override does not "
            "probe a before-count."
        ),
    },
    "intention_override": {
        "stage": "router",
        "label": "Override label",
        "purpose": (
            "Skip the buying-versus-browsing classification when an explicit intent reset already decided the path."
        ),
        "why": (
            "Once the shopper clearly changed their mind, the router should not spend a second model call guessing whether the next step is a focused purchase or exploratory browse."
        ),
        "this_turn": (
            "Status: skipped\nReason: this turn did not require override routing.\nResult: the router kept the normal decision path."
        ),
        "how_it_works": (
            "Uses the reset path directly, without asking the LLM to reclassify the turn as buying or browsing."
        ),
        "function": "Set intention=override and skip buying versus browsing.",
        "implementation": (
            "route_llm is skipped. Retrieve still scores this exact set with "
            "buying-like weights and a 150-hit cap. Failsafe may still open "
            "the conversion gate at turn 4."
        ),
    },
    "probe_before": {
        "stage": "router",
        "label": "Probe before",
        "purpose": (
            "Measure the candidate pool before the newest preferences are added."
        ),
        "why": (
            "The router needs to know whether this turn narrowed the search substantially or simply added a small refinement. This helps distinguish a focused purchase from open browsing."
        ),
        "this_turn": (
            "Status: skipped\nReason: the turn was a full reset and did not have a comparable previous state.\nResult: no before-probe was needed."
        ),
        "how_it_works": (
            "Captures the exact-pool size before the current turn's delta is applied, so the after-state can be compared."
        ),
        "function": (
            "Exact pool on the committed state before this turn’s delta is applied."
        ),
        "implementation": (
            "The before count is stored as candidate_count_before_delta. Together "
            "with the after count it forms the ratio classify_route sees. "
            "Skipped on override."
        ),
    },
    "apply_delta": {
        "stage": "router",
        "label": "Accumulate",
        "purpose": (
            "Add new preferences without overwriting the earlier shopping state."
        ),
        "why": (
            "A follow-up like 'more breathable' should not erase prior requirements such as 'running shoes under $150.' This preserves the shopper's ongoing intent across turns."
        ),
        "this_turn": (
            "Status: ran\nResult: the new preferences were added to the current shopping state without dropping older requirements."
        ),
        "how_it_works": (
            "Upserts the new slots onto the committed session state while preserving earlier constraints unless an override explicitly replaces them."
        ),
        "function": "Upsert this turn’s slots onto the committed session state.",
        "implementation": (
            "apply_delta writes hard and soft typed slots. Same-key updates keep "
            "the later hardness. This is the only writeback on the non-override path."
        ),
    },
    "probe_after": {
        "stage": "router",
        "label": "Probe after",
        "purpose": (
            "Measure the candidate pool after the new preferences are added so the router can judge how much the search narrowed."
        ),
        "why": (
            "A big drop from before to after suggests the shopper is focusing the search, while a small or noisy change suggests a broader exploratory browse."
        ),
        "this_turn": (
            "Status: ran\nResult: candidate pool was measured after the current turn's preferences were applied."
        ),
        "how_it_works": (
            "Captures the exact-pool size after merge, and compares it with the before measurement to decide whether the search is becoming more focused."
        ),
        "function": "Exact pool after accumulate — the set retrieve will score if nonempty.",
        "implementation": (
            "None is not zero: a missing pool and an empty intersection both "
            "send retrieve down hybrid recovery. The after count becomes "
            "candidate_count."
        ),
    },
    "route_llm": {
        "stage": "router",
        "label": "Route LLM",
        "purpose": (
            "Decide whether the search should be focused and purchase-like or wide and exploratory."
        ),
        "why": (
            "The same shopper request can mean a narrow buy decision or a broad browse, depending on how much the search space narrowed and how explicit the constraints are."
        ),
        "this_turn": (
            "Status: ran\nResult: the router selected the appropriate search mode using the before/after candidate comparison."
        ),
        "how_it_works": (
            "Uses the before/after pool ratio and the current dialogue to classify the turn as buying or browsing."
        ),
        "function": "Label the turn buying or browsing from dialogue plus pool ratio.",
        "implementation": (
            "classify_route is a second Qwen JSON call. It receives pool_before, "
            "pool_after, and their ratio. There is no regex intention fallback. "
            "The call is skipped after override."
        ),
    },
    "buying": {
        "stage": "router",
        "label": "Buying",
        "purpose": (
            "Use tighter retrieval when the shopper has already narrowed the product with specific constraints."
        ),
        "why": (
            "A focused purchase path should prioritize a smaller, high-confidence candidate pool rather than broad exploration."
        ),
        "this_turn": (
            "Status: ran\nResult: the router chose a focused search with a tighter retrieval cap."
        ),
        "how_it_works": (
            "Switches the search to a narrower, higher-confidence mode that keeps the candidate pool small and more decisive."
        ),
        "function": (
            "Outcome node: intention=buying, tighter structured weights, 150-hit cap."
        ),
        "implementation": (
            "routing_for('buying') sets lexical 0.4 / required 6.0 / category 4.0 "
            "and BUYING_LIMIT=150. Mutually exclusive with browsing."
        ),
    },
    "browsing": {
        "stage": "router",
        "label": "Browsing",
        "purpose": (
            "Keep retrieval wider while the shopper is still exploring or refining the category."
        ),
        "why": (
            "A broad exploration mode is better when the shopper has not yet converged on a final requirement set or when the current request is still open-ended."
        ),
        "this_turn": (
            "Status: ran\nResult: the router chose a broader search so the candidate pool stayed wider."
        ),
        "how_it_works": (
            "Uses a wider retrieval cap and lighter weighting so the agent is still exploratory rather than overly decisive."
        ),
        "function": (
            "Outcome node: intention=browsing, lexical-heavier weights, 500-hit cap."
        ),
        "implementation": (
            "routing_for('browsing') sets lexical 1.6 / required 2.5 and "
            "BROWSING_LIMIT=500 so soft exploration stays wider."
        ),
    },
    "failsafe": {
        "stage": "router",
        "label": "Failsafe",
        "purpose": (
            "Prevent the router from getting stuck in the wrong intent mode when the session is still unresolved."
        ),
        "why": (
            "A robust agent should not remain locked into a stale route forever. This safety check keeps the session moving forward when the intent is still ambiguous."
        ),
        "this_turn": (
            "Status: ran\nResult: the router completed its safety check before retrieval."
        ),
        "how_it_works": (
            "Opens the conversion gate when the session is still in a stale or unresolved state, preventing the router from getting stuck."
        ),
        "function": (
            "Open the conversion gate at turn 4 if a missed override left it closed."
        ),
        "implementation": (
            "apply_override_failsafe sets gate_open when turn >= 4 and the gate "
            "is still closed. It does not rewrite intention, bump intent_version, "
            "or set override_seen. Both router branches end here."
        ),
    },
    "slot_groups": {
        "stage": "retrieve",
        "label": "Separate requirements from preferences",
        "purpose": (
            "Split the shopper’s saved constraints into must-have requirements, softer preferences, and budget limits."
        ),
        "why": (
            "Hard requirements can restrict which products are eligible, while preferences should improve ranking without accidentally removing good alternatives."
        ),
        "this_turn": (
            "Search mode: Browsing\nMust-have requirements: use case — 'to buy running shoes for jogging'\nPreferences: none\nBudget: none"
        ),
        "how_it_works": (
            "Hard constraints form required groups; soft constraints become ranking preferences. Hard filters may remove candidates, while soft preferences only affect score."
        ),
        "function": (
            "Turn committed typed slots into required groups, preferred groups, "
            "and an optional budget interval."
        ),
        "implementation": (
            "from_slots.required_and_budget reads hard slots (OR inside an "
            "attribute, AND across). Soft slots become preferred_groups and never "
            "prune. Hard budget drops missing-price items; soft budget only "
            "withholds a bonus. Category is handled separately."
        ),
    },
    "rewrite_query": {
        "stage": "retrieve",
        "label": "Build the retrieval query",
        "purpose": (
            "Convert the committed shopping intent into the text query used for lexical retrieval."
        ),
        "why": (
            "Retrieval should search from the shopper’s current session state, not blindly reuse the latest message and accidentally reintroduce preferences that were removed or replaced."
        ),
        "this_turn": (
            "Resolved category: not available\nSearch terms: 'to buy running shoes for jogging'\nFinal query: 'to buy running shoes for jogging'"
        ),
        "how_it_works": (
            "Combines the current category and committed search values. The raw shopper message is used only when no structured search terms are available."
        ),
        "function": (
            "Build the BM25 query from the current category plus committed "
            "search values."
        ),
        "implementation": (
            "rewrite_query joins category and slot search terms. The raw message "
            "is fallback only when that string is empty — replaying it after "
            "slots exist would restore negated or superseded words."
        ),
    },
    "routing": {
        "stage": "retrieve",
        "label": "Choose retrieval breadth",
        "purpose": (
            "Choose how many candidates to retrieve and how strongly to favor exact constraints based on the Intent Router’s buying/browsing decision."
        ),
        "why": (
            "Focused buyers need tighter retrieval, while browsing users need a wider candidate pool so the correct product is not removed too early."
        ),
        "this_turn": (
            "Intent: Browsing\nRetrieval strategy: wide exploration\nFinal hit limit: 500\nCandidate search limit: 1,500\nExact matches preferred first: yes"
        ),
        "how_it_works": (
            "Browsing keeps a wider pool; buying uses a smaller, more constraint-focused pool."
        ),
        "function": "Pick score weights and hit caps from the router-labeled intention.",
        "implementation": (
            "routing_for(intention) returns TrackRouting. Buying and override "
            "share the 150 cap; browsing uses 500. Hard intersection already "
            "happened in the router; this node only chooses how to score."
        ),
    },
    "lexical_in_pool": {
        "stage": "retrieve",
        "label": "Rank within the exact-match pool",
        "purpose": (
            "Apply BM25 relevance only to products that already satisfy the exact hard-constraint pool."
        ),
        "why": (
            "Once must-have requirements are satisfied, lexical relevance helps order those valid products without reopening unrelated catalog items."
        ),
        "this_turn": (
            "Status: skipped\nReason: no usable exact candidate pool was available.\nResult: continue to hybrid recovery."
        ),
        "how_it_works": (
            "BM25 scores the catalog and then keeps only products already present in the exact candidate pool."
        ),
        "function": (
            "BM25 scores restricted to ASINs already in the router exact set."
        ),
        "implementation": (
            "lexical_scores(query, candidate_limit) then keep only keys in exact. "
            "Taken only when that set is nonempty. This is a tie-break inside "
            "the pool, not a new recall."
        ),
    },
    "score_exact": {
        "stage": "retrieve",
        "label": "Score exact-match candidates",
        "purpose": (
            "Rank products that satisfy the hard requirements using category fit, lexical relevance, required-constraint coverage, budget, and preferences."
        ),
        "why": (
            "Exact matching determines eligibility, but products still need to be ordered by how well they satisfy the full shopping request."
        ),
        "this_turn": (
            "Status: skipped\nReason: there was no exact-match pool to score.\nNext: hybrid candidate recovery."
        ),
        "how_it_works": (
            "Combines structured requirement coverage with lexical and preference signals. Missing hard requirements receive strong penalties; soft preferences affect ranking only."
        ),
        "function": "Structured-score every exact-pool ASIN with the routing weights.",
        "implementation": (
            "score_candidates fuses lexical, required coverage, category, budget, "
            "dimensions, soft text, and weak profile tags. Missing required "
            "slots are penalized; preferred slots never drop a candidate."
        ),
    },
    "hybrid_search": {
        "stage": "retrieve",
        "label": "Recover broader candidates",
        "purpose": (
            "Recover relevant products using broader lexical and catalog-signature retrieval when exact filtering cannot provide enough candidates."
        ),
        "why": (
            "Hard intersections can sometimes be too strict or incomplete. Hybrid recovery prevents the agent from returning an empty or tiny recommendation slate."
        ),
        "this_turn": (
            "Reason for recovery: no usable exact pool\nQuery: 'to buy running shoes for jogging'\nRequested limit: 500\nRecovered candidates: 500"
        ),
        "how_it_works": (
            "Searches more permissively, combines lexical and catalog-signature matches, preserves strong exact hits when available, and fills the remaining candidate slots."
        ),
        "function": (
            "Recover candidates with BM25 ∪ catalog signatures when the exact "
            "pool is empty, missing, or smaller than 150."
        ),
        "implementation": (
            "retriever.search(..., hard_required=False) so an over-pruned "
            "intersection does not yield an empty slate. A small exact pool "
            "keeps hard hits first and fills to 300 (browsing 500); a pool "
            "of 150+ skips this node. Excluded ASINs from earlier slates "
            "are dropped."
        ),
    },
    "cap_hits": {
        "stage": "retrieve",
        "label": "Merge and cap candidates",
        "purpose": (
            "Merge the exact and hybrid recall paths into one candidate list and keep only the number required by the current retrieval strategy."
        ),
        "why": (
            "Retrieval needs enough recall to protect the hidden target, but downstream ranking should not waste time processing an unnecessarily large catalog slice."
        ),
        "this_turn": (
            "Recall path: hybrid recovery\nCandidates before cap: 500\nRouting limit: 500\nCandidates passed forward: 500"
        ),
        "how_it_works": (
            "Keeps exact candidates first when they exist, fills remaining slots from hybrid retrieval, and truncates the merged list to the routing limit."
        ),
        "function": "Truncate the scored list to the routing limit. Merge of both recall paths.",
        "implementation": (
            "hits[:routing.limit] when exact already has 150+; otherwise "
            "exact hits plus hybrid fill to 300/500, hard segment first. "
            "Official respond still uses planner/gate, not this full library."
        ),
    },
    "qwen_rerank": {
        "stage": "retrieve",
        "label": "Semantic rerank",
        "purpose": (
            "Reorder the strongest retrieved candidates by semantic shopping fit, beyond simple keyword overlap."
        ),
        "why": (
            "Lexical search may rank 'running' and 'jogging' differently even when they express similar needs. Semantic reranking helps correct those ordering mistakes after candidate recall."
        ),
        "this_turn": (
            "Status: skipped\nReason: local semantic reranker was unavailable or disabled.\nFallback: continue with deterministic ranking."
        ),
        "how_it_works": (
            "When enabled, the local semantic model reranks the top retrieved products using the structured shopping request and product information."
        ),
        "function": (
            "Optional local cross-encoder that reorders the retrieved head by "
            "semantic shopping fit."
        ),
        "implementation": (
            "QwenSemanticReranker scores the first 50 hits with a structured "
            "query/product pair. Buying fuses at 0.35, browsing at 0.55. Missing "
            "weights or AGENT_RERANKER_LOCAL_FILES_ONLY skips safely to belief."
        ),
    },
    "belief_hits": {
        "stage": "retrieve",
        "label": "Convert scores to ranking confidence",
        "purpose": (
            "Turn raw retrieval scores into positive relative weights for downstream ranking and decision-making."
        ),
        "why": (
            "BM25 and structured scores are not naturally comparable as probabilities. A common ranking scale lets the next stage judge how concentrated or uncertain the candidate list is."
        ),
        "this_turn": (
            "Input candidates: 500\nMethod: deterministic score conversion\nOutput weights: 500\nNote: these are ranking confidence weights, not purchase probabilities."
        ),
        "how_it_works": (
            "Converts score differences into positive relative weights while preserving the candidate ordering."
        ),
        "function": (
            "Deterministic ranking weights from retrieval scores when the "
            "semantic head is off."
        ),
        "implementation": (
            "belief_from_hits uses exp((s − max) / 0.12). These are ranking "
            "beliefs, not calibrated purchase probabilities."
        ),
    },
    "normalize": {
        "stage": "retrieve",
        "label": "Normalize ranking weights",
        "purpose": (
            "Scale candidate weights into one consistent ranking distribution that the Decide stage can consume."
        ),
        "why": (
            "The planner needs both candidate order and relative concentration to decide whether the agent should recommend now or ask another question."
        ),
        "this_turn": (
            "Ranking source: deterministic belief weights\nCandidates normalized: 500\nOutput: RankedCandidate[500]\nNext stage: Decide"
        ),
        "how_it_works": (
            "Divides each positive ranking weight by the total and sorts candidates from strongest to weakest. These values represent relative ranking mass, not calibrated purchase probability."
        ),
        "function": (
            "Turn positive weights into RankedCandidate probabilities the planner can read."
        ),
        "implementation": (
            "normalize_probabilities sorts by weight and divides by the total. "
            "The planner uses only parent_asin order and probability."
        ),
    },
    "answer_signature": {
        "stage": "decide",
        "label": "Track what the shopper has already told us",
        "purpose": (
            "Record the shopper information that is already known from the current conversation so the agent does not ask for the same preference again."
        ),
        "why": (
            "Every unnecessary clarification costs another turn. Remembering what the shopper has already disclosed helps the agent reach the target product faster and reduces avoidable MTTC cost."
        ),
        "this_turn": (
            "Known preferences\nProduct type: running shoes\nUse case: jogging\nBudget: under $150\nResult: three shopper requirements are already known."
        ),
        "how_it_works": (
            "Reads the committed SessionState and the shopper’s disclosed answers, then marks those attributes as already resolved before question planning begins."
        ),
        "function": (
            "Cache how each remaining ASIN would answer a structured question."
        ),
        "implementation": (
            "make_answer_signature memoizes retriever.predict_reply(asin, "
            "attribute, disclosed). Empty values become the NO_ADDITIONAL "
            "sentinel so the planner can partition the residual."
        ),
    },
    "eligible_questions": {
        "stage": "decide",
        "label": "Find useful remaining questions",
        "purpose": (
            "Identify which still-unknown product attributes could meaningfully separate the strongest remaining candidates."
        ),
        "why": (
            "The agent should not ask a generic question just because information is missing. It should ask only about preferences that can actually change the ranking. Low-value questions waste turns without improving MRR or Hit@10."
        ),
        "this_turn": (
            "Candidate differences\nCushioning: high\nWeight: high\nBrand: low\nBest unresolved dimension: cushioning vs lightweight design."
        ),
        "how_it_works": (
            "Compares the current ranked candidates and removes attributes the shopper has already answered. Only unresolved dimensions with enough candidate variation are passed to the planner."
        ),
        "function": (
            "List ask_attribute values that can still split the belief, plus "
            "ask-nothing."
        ),
        "implementation": (
            "eligible_questions walks QUESTION_ATTRIBUTES. Turn 10 returns only "
            "None. Already-asked or already-hard typed attributes are skipped; "
            "other may repeat because it reveals the next undisclosed pair."
        ),
    },
    "planner": {
        "stage": "decide",
        "label": "Decide whether another turn is worth it",
        "purpose": (
            "Choose between recommending now and asking one additional high-value clarification question."
        ),
        "why": (
            "Another question may improve the target’s rank, but it also increases MTTC. The planner balances expected ranking improvement against the cost of another conversation turn."
        ),
        "this_turn": (
            "Current ranking confidence: medium\nBest remaining question: cushioning vs lighter weight\nExpected value of asking: high\nDecision: ask one question."
        ),
        "how_it_works": (
            "Uses the ranked-candidate distribution, remaining question value, current turn number, and already-known preferences to choose the next action."
        ),
        "function": (
            "Jointly choose which question to ask and how many products to expose."
        ),
        "implementation": (
            "ScoreAwarePlanner searches ask × k ∈ [0, top_k]. Immediate hit "
            "utility is 0.50 + 0.30/rank + 0.02×(11−turn), plus future_value "
            "of reply partitions. Turn 10 and empty disclosure are a full "
            "slate and no question. Empty pools ask other (or nothing on turn 10)."
        ),
    },
    "sequential_gate": {
        "stage": "decide",
        "label": "Check whether the recommendation slate should change",
        "purpose": (
            "Decide whether the newly ranked products are strong enough to replace the recommendation slate already shown to the shopper."
        ),
        "why": (
            "Replacing recommendations too aggressively makes the conversation unstable, while keeping a weak slate can hide a newly improved top candidate. This gate balances ranking improvement with recommendation stability."
        ),
        "this_turn": (
            "Previous slate: 10 products\nNew ranking: available\nTop candidate changed: no\nDecision: keep the current slate."
        ),
        "how_it_works": (
            "Compares the current ranked candidates with the existing slate and chooses whether to preserve the current recommendations or update them with the latest ranking."
        ),
        "function": (
            "After planning, decide whether to show the planned slate or only rank-1."
        ),
        "implementation": (
            "apply_sequential_gate keeps slate[:1] when the gate is open, it is "
            "not turn 10, the planned slate is wider than one, and either an "
            "informative question remains or leftover candidates still fit "
            "one-per-turn plus the final Top-10. Empty disclosure keeps the "
            "planned Top-K."
        ),
    },
    "gate_rank1": {
        "stage": "decide",
        "label": "Promote the new top candidate",
        "purpose": (
            "Update the recommendation slate when the latest retrieval produces a meaningfully stronger top-ranked product."
        ),
        "why": (
            "The competition rewards placing the hidden target as high as possible. When new information clearly improves the ranking, the agent should surface that improved Rank-1 result immediately."
        ),
        "this_turn": (
            "Previous top product: Product A\nNew top product: Product B\nAction: promote Product B to Rank 1."
        ),
        "how_it_works": (
            "Rebuilds the visible slate around the latest top-ranked candidate when the slate gate authorizes an update."
        ),
        "function": "Expose only the top planned ASIN this turn.",
        "implementation": (
            "Rank-1 can convert now; lower ranks usually wait for the answer and "
            "free no-hit feedback. This branch is skipped when the gate does "
            "not truncate."
        ),
    },
    "keep_planned": {
        "stage": "decide",
        "label": "Keep the current recommendations stable",
        "purpose": (
            "Preserve the recommendation slate when the latest ranking does not justify replacing what the shopper has already seen."
        ),
        "why": (
            "Stable recommendations preserve conversational continuity when new evidence is too weak to justify changing the products already shown to the shopper. A small score change is not enough to replace the whole slate."
        ),
        "this_turn": (
            "Decision: keep the current slate\nReason: no meaningful ranking improvement justified replacement."
        ),
        "how_it_works": (
            "Reuses the existing slate while allowing the underlying session state and candidate beliefs to continue updating."
        ),
        "function": "Keep the planner’s wider recommendation list.",
        "implementation": (
            "Taken on turn 10, on empty disclosure, when the gate is closed, "
            "when there is no useful question and too many leftovers to probe "
            "one-by-one, or when the planned slate is already a singleton."
        ),
    },
    "persist_turn": {
        "stage": "decide",
        "label": "Save the decision for the next turn",
        "purpose": (
            "Store the chosen recommendation slate, planner decision, and conversation state so the next turn continues from the same context."
        ),
        "why": (
            "Without persistence, every shopper message would behave like a fresh search and earlier preferences or recommendation context could be lost across turns."
        ),
        "this_turn": (
            "Saved\nActive preferences: updated\nRecommendation slate: 10 products\nPlanner action: ask/recommend\nReady for next turn: yes"
        ),
        "how_it_works": (
            "Commits the selected slate and decision metadata to SessionState after planning is complete."
        ),
        "function": (
            "Write this turn’s slate and question into session memory for the next turn."
        ),
        "implementation": (
            "persist_turn sets reply_value_lookup from predicted replies "
            "(semicolon restore) and record_action writes last_slate, last_ask, "
            "asked, and shown_asins. Next-turn miss_feedback reads last_slate."
        ),
    },
    "build_response": {
        "stage": "decide",
        "label": "Return the next best action to the shopper",
        "purpose": (
            "Produce the final user-facing response for this turn: either ranked product recommendations or one targeted clarification question."
        ),
        "why": (
            "The final response should move the shopper closer to the target product while using as few turns as possible. A good response either exposes a strong Top-10 slate immediately or asks exactly one question that is expected to improve the next ranking."
        ),
        "this_turn": (
            "Action: recommend\nProducts shown: top 10\nBest match: Product A\nFollow-up question: none"
        ),
        "how_it_works": (
            "Converts the planner and slate decision into the published Agent response format expected by the evaluator and the conversational UI."
        ),
        "function": (
            "Assemble the official respond dict: message, ask_attribute, "
            "recommendations, usage."
        ),
        "implementation": (
            "build_response formats a short English message from slate length "
            "plus explain_question(ask_attribute). recommendations are "
            "{parent_asin} objects only. usage carries this turn’s router tokens."
        ),
    },
}

STAGE_BLURBS: dict[str, str] = {
    "understand": (
        "Observe only. Rewrite, walk the category tree, and extract typed slots "
        "into turn_delta. Constraints are committed later by the router."
    ),
    "router": (
        "Override versus accumulate, probe the hard exact pool, then label "
        "buying, browsing, or override. Unused branches stay on the graph."
    ),
    "retrieve": (
        "Score a nonempty exact pool, or hybrid-recover when it is empty. "
        "Then optional Qwen rerank or deterministic belief, then normalize."
    ),
    "decide": (
        "Search question × slate size, apply the sequential gate, persist "
        "memory, and return the official respond dict."
    ),
}
