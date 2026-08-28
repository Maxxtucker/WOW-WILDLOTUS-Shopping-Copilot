"""Purpose: official Agent interface. reset creates a session; respond hands one turn to TurnPipeline.

Input: catalog_path; optional understand_mode (nlu or regex); reset(session_id, user_profile); respond(...).
Output: {message, ask_attribute, recommendations, usage}.
Role: the only implementation class the evaluator calls through starter.agent. Process-wide shared index; per-session SessionState.
"""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from .retrieve.catalog.index_path import resolve_index_path
from .retrieve.catalog.retriever import CatalogRetriever
from .decide.clarification.planner import ScoreAwarePlanner
from .pipeline import TurnPipeline
from .understand.mode import (
    MODE_NLU,
    MODE_REGEX,
    configure_understand,
    resolve_understand_mode,
)
from .understand.observation.llm_nlu import load_nlu_env, warmup_nlu
from .understand.observation.runtime import ensure_llm_runtime
from .understand.state.session import SessionState


class Agent:
    """Conversational product-search agent.

    The implementation has two cooperating paths:

    * a protocol-aware response-signature index that models counterfactual
      answers for every catalog product;
    * a fielded BM25/structured fallback for paraphrased or unseen wording.

    It does not read the public labels. Understand defaults to local NLU
    (``understand_mode="nlu"``): Agent startup loads ``scripts/nlu.env``,
    starts Ollama when needed, and retries a failed extract three times
    before falling back to regex. Pass ``understand_mode="regex"`` to skip
    the LLM entirely.

    Each ``respond`` call runs :class:`~agent.pipeline.TurnPipeline`.
    """

    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        *,
        understand_mode: str | None = None,
    ) -> None:
        persistent_index = resolve_index_path(catalog_path)
        self.retriever = CatalogRetriever(catalog_path, index_path=persistent_index)
        # Planning only needs the head of the posterior; retrieval still keeps
        # a wider pool for recall.  This bounds counterfactual reply expansion.
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

    def reset(self, session_id: str, user_profile: dict) -> None:
        """Create an isolated state for a new evaluator session."""

        if not session_id:
            raise ValueError("session_id must be non-empty")
        with self._lock:
            self.sessions[session_id] = SessionState(
                session_id=session_id,
                user_profile=dict(user_profile or {}),
            )

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
        return self.pipeline.run(state, str(user_message), int(turn), int(top_k))
