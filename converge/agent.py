"""Official Agent-interface implementation for Converge."""

from __future__ import annotations

import math
import os
import hashlib
import tempfile
from pathlib import Path
from threading import RLock

from .domain import canonical, classify_constraint
from .planner import NO_ADDITIONAL, ScoreAwarePlanner, explain_question, normalize_probabilities
from .retrieval import CatalogRetriever, SearchHit
from .state import SessionState


class Agent:
    """Offline conversational product-search agent.

    The implementation has two cooperating paths:

    * a protocol-aware response-signature index that models counterfactual
      answers for every catalog product;
    * a fielded BM25/structured fallback for paraphrased or unseen wording.

    It does not read the public labels and does not require an LLM, network
    connection, API key, or non-standard Python package.
    """

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        catalog = Path(catalog_path)
        configured_index = os.environ.get("CONVERGE_INDEX_PATH")
        if configured_index == ":memory:":
            persistent_index: str | Path | None = None
        elif configured_index:
            persistent_index = configured_index
        else:
            # Keep the large FTS/signature index off the Python/SQLite heap on
            # memory-constrained runners.  The OS temp cache is disposable and
            # keyed by the immutable catalog fingerprint; it never modifies the
            # competition data and is automatically validated by the retriever.
            stat = catalog.stat()
            fingerprint = (
                f"{catalog.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
            ).encode("utf-8")
            cache_key = hashlib.sha256(fingerprint).hexdigest()[:16]
            cache_root = Path(
                os.environ.get("CONVERGE_CACHE_DIR") or tempfile.gettempdir()
            ) / "converge-techjam2026"
            persistent_index = cache_root / f"catalog-{cache_key}.sqlite3"
        self.retriever = CatalogRetriever(catalog_path, index_path=persistent_index)
        # Planning only needs the head of the posterior; retrieval still keeps
        # a wider pool for recall.  This bounds counterfactual reply expansion.
        self.planner = ScoreAwarePlanner(max_planning_candidates=500)
        self.sessions: dict[str, SessionState] = {}
        self._lock = RLock()

    def reset(self, session_id: str, user_profile: dict) -> None:
        """Create an isolated state for a new evaluator session."""

        if not session_id:
            raise ValueError("session_id must be non-empty")
        with self._lock:
            self.sessions[session_id] = SessionState(
                session_id=session_id,
                user_profile=dict(user_profile or {}),
            )

    @staticmethod
    def _exact_pool(
        retriever: CatalogRetriever,
        category: str | None,
        constraints: tuple[str, ...],
    ) -> set[str] | None:
        """Intersect exact, evaluator-compatible signals when all are known.

        Returning ``None`` means at least one signal is not represented exactly,
        so the caller should use the robust lexical path instead of over-pruning.
        """

        sets: list[set[str]] = []
        if category:
            values = set(retriever.signature_candidates("category", category))
            if not values:
                return None
            sets.append(values)
        for constraint in constraints:
            attribute = classify_constraint(constraint)
            values = set(
                retriever.signature_candidates(
                    attribute,
                    constraint,
                    response_only=True,
                )
            )
            if not values:
                return None
            sets.append(values)
        if not sets:
            return None
        return set.intersection(*sets)

    def _retrieve(self, state: SessionState) -> list[SearchHit]:
        constraints = state.ranking_constraints
        exact = self._exact_pool(self.retriever, state.category, constraints)
        if exact:
            hits = self.retriever.score_candidates(
                exact,
                required=constraints,
                categories=(() if state.category is None else (state.category,)),
                exclude_asins=state.excluded_asins,
            )
            if hits:
                return hits[:500]

        # Robust fallback: query rewrite contains only the current intent's
        # active evidence.  Sparse prices and store/brand are kept soft.
        profile_tags = state.user_profile.get("preference_tags") or []
        profile_text = " ".join(str(value) for value in profile_tags[:4])
        query = " ".join(
            part
            for part in (
                state.category or "",
                *constraints,
                state.latest_message,
                profile_text,
            )
            if part
        )
        return self.retriever.search(
            query,
            required=constraints,
            preferred=profile_tags[:2],
            categories=(() if state.category is None else (state.category,)),
            exclude_asins=state.excluded_asins,
            limit=500,
            candidate_limit=1_500,
            hard_required=False,
        )

    @staticmethod
    def _belief(hits: list[SearchHit]) -> list[tuple[str, float]]:
        """Map retrieval scores to a conservative probability-like mass.

        A low-capacity temperature transform is deliberate: only ordering is
        needed for ranking, while a flatter distribution prevents the planner
        from treating small hand-score differences as certainty.
        """

        if not hits:
            return []
        maximum = max(hit.score for hit in hits)
        # The structured score is often constant within an exact-signature
        # bucket.  Temperature 0.12 turns the weak popularity/quality prior
        # into useful ordering without claiming that the raw score is a
        # calibrated probability.
        temperature = 0.12
        return [
            (hit.parent_asin, math.exp((hit.score - maximum) / temperature))
            for hit in hits
        ]

    def _answer_signature(self, state: SessionState, parent_asin: str, attribute: str) -> tuple[str, ...]:
        values = self.retriever.predict_reply(parent_asin, attribute, state.disclosed)
        if not values:
            return NO_ADDITIONAL
        return tuple(canonical(value) for value in values)

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict:
        if session_id not in self.sessions:
            raise RuntimeError("reset must be called before respond")
        if not 1 <= int(turn) <= 10:
            raise ValueError("turn must be between 1 and 10")
        if int(top_k) <= 0:
            raise ValueError("top_k must be positive")

        state = self.sessions[session_id]
        state.begin_turn(str(user_message), int(turn))
        hits = self._retrieve(state)
        ranked = normalize_probabilities(self._belief(hits))
        reply_cache: dict[tuple[str, str], tuple[str, ...]] = {}

        def answer_signature(parent_asin: str, attribute: str) -> tuple[str, ...]:
            key = (parent_asin, attribute)
            if key not in reply_cache:
                reply_cache[key] = self._answer_signature(
                    state, parent_asin, attribute
                )
            return reply_cache[key]

        plan = self.planner.plan(
            state,
            ranked,
            min(10, int(top_k)),
            answer_signature,
        )
        slate = list(plan.recommendations)
        # Risk control for a miss-triggered dialog: while an informative answer
        # is pending, only the highest-confidence item is exposed. Rank one can
        # only benefit from converting now; lower-ranked items are usually
        # worth deferring because the answer and the free no-hit feedback can
        # promote them on the next turn. With no useful question, singleton
        # probing is used only when all remaining candidates still fit into the
        # remaining one-at-a-time turns plus the final Top-10; otherwise the
        # planner's wider slate is preserved. Turn 10 is always full Top-K.
        sequential_capacity = 10 + (10 - state.turn)
        if (
            state.gate_open
            and state.turn < 10
            and len(slate) > 1
            and (
                plan.ask_attribute is not None
                or len(ranked) <= sequential_capacity
            )
        ):
            slate = slate[:1]
        if plan.ask_attribute is None:
            state.set_reply_options([])
        else:
            state.set_reply_options(
                [
                    self.retriever.predict_reply(
                        hit.parent_asin,
                        plan.ask_attribute,
                        state.disclosed,
                    )
                    for hit in hits
                ]
            )
        state.record_action(slate, plan.ask_attribute)

        if slate:
            prefix = f"I narrowed this to {len(slate)} high-confidence option"
            if len(slate) != 1:
                prefix += "s"
            message = f"{prefix}. {explain_question(plan.ask_attribute)}"
        else:
            message = (
                "I am narrowing the catalog before showing a low-confidence match. "
                + explain_question(plan.ask_attribute)
            )

        return {
            "message": message,
            "ask_attribute": plan.ask_attribute,
            "recommendations": [
                {"parent_asin": parent_asin} for parent_asin in slate
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }
