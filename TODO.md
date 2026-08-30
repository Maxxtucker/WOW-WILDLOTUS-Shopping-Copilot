# Follow-ups (not in this pass)

- **Linguistic exclusion** is not a designed slot. Do not confuse it with `excluded_asins` (previous-slate miss feedback). Catalog `score_candidates(..., excluded=)` attribute pairs are leftover plumbing and are not wired from NLU. A later pass can add polarity / `is_excluded` on understand slots, then pass those pairs from `retrieve_candidates` into `score_candidates`.

- **Semantic rerank** scores only the first `top_n` hits (default 50, `AGENT_RERANKER_TOP_N`). The rest of the 150/500 retrieve tail keeps structured scores. Keep this. Revisit only if the unscored tail is drowning the slate.
