"""Purpose: one-turn orchestration: understand → intention router → retrieve → decide.

Input: SessionState, user_message, turn, top_k.
Output: official respond dict. run_traced also returns a TurnTrace.
Role: observe writes turn_delta; the router commits constraints and an exact pool.
After understand, an empty-disclosure turn with at least one unshown
last_ranked ASIN skips the router and retrieve and pages the next top_k
(usually 10). An empty leftover list falls through to normal retrieve.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .decide.clarification.planner import ScoreAwarePlanner
from .decide.clarification.stage import Clarifier
from .decide.clarification.types import Plan
from .decide.ranking import Ranker
from .decide.response.builder import ResponseBuilder
from .intent_router import IntentRouter
from .progress import (
    DECIDE_PLAN_NODES,
    RETRIEVE_NODES,
    ROUTER_NODES,
    emit,
    skip_nodes,
)
from .retrieve.candidates.retrieve import CandidateOrganizer
from .trace import (
    TurnTrace,
    build_decide_trace,
    build_ranking_trace,
    build_retrieve_trace,
    build_router_trace,
    build_understand_trace,
)
from .understand.state.lifecycle import StateDetector

if TYPE_CHECKING:
    from .retrieve.catalog.retriever import CatalogRetriever
    from .understand.state.session import SessionState

EMPTY_DISCLOSURE_SLATE = 10
EMPTY_DISCLOSURE_WHY = "empty disclosure"


def next_ranked_page(
    state: SessionState,
    limit: int = EMPTY_DISCLOSURE_SLATE,
) -> list[str]:
    """Next leftover ASINs from last_ranked, skipping excluded and shown."""

    blocked = set(state.excluded_asins) | set(state.shown_asins)
    leftover: list[str] = []
    for asin in state.last_ranked:
        if asin in blocked:
            continue
        leftover.append(asin)
        if len(leftover) >= limit:
            break
    return leftover


def leftover_page_stats(state: SessionState) -> dict[str, object]:
    """Why next_ranked_page is empty or not. For terminal / circuit detail."""

    blocked = set(state.excluded_asins) | set(state.shown_asins)
    leftover = next_ranked_page(state)
    leftover_n = len(leftover)
    return {
        "last_ranked_n": len(state.last_ranked),
        "last_ranked_head": list(state.last_ranked[:5]),
        "shown_n": len(state.shown_asins),
        "excluded_n": len(state.excluded_asins),
        "blocked_n": len(blocked),
        "leftover_n": leftover_n,
        "leftover_page": leftover,
        "shortcut_ok": leftover_n >= 1,
    }


def pages_empty_disclosure(state: SessionState) -> bool:
    """True when disclosure is empty and last_ranked still has an unshown ASIN."""

    # A no-preference answer to one structured question only exhausts that
    # attribute. It must return through retrieval and Dynamic Slate so another
    # question can be chosen. Preserve paging only for generic/no-question
    # turns that add no new evidence at all.
    if state.last_ask is not None:
        return False
    if state.turn_delta is not None:
        return False
    if state.disclosure_empty is False:
        return False
    return bool(next_ranked_page(state, limit=1))


def _compact_response(response: dict) -> dict:
    """Official respond fields the demo monitor can print at decide reveal."""

    recs: list[str] = []
    for item in response.get("recommendations") or []:
        if isinstance(item, dict) and item.get("parent_asin"):
            recs.append(str(item["parent_asin"]))
    return {
        "message": response.get("message"),
        "ask_attribute": response.get("ask_attribute"),
        "recommendations": recs,
    }


class TurnPipeline:
    """Run one evaluator turn: observe, route, retrieve, rank, plan, respond."""

    def __init__(
        self,
        retriever: CatalogRetriever,
        planner: ScoreAwarePlanner | None = None,
    ) -> None:
        self.retriever = retriever
        self.state_detector = StateDetector()
        self.intent_router = IntentRouter()
        self.organizer = CandidateOrganizer(retriever)
        self.ranker = Ranker(retriever)
        self.clarifier = Clarifier(retriever, planner)
        self.responder = ResponseBuilder()

    def run(
        self,
        state: SessionState,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict:
        response, _trace = self.run_traced(state, user_message, turn, top_k)
        return response

    def run_traced(
        self,
        state: SessionState,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> tuple[dict, TurnTrace]:
        emit("understand", "stage", "running")
        self.state_detector.apply(state, user_message, turn)
        understand = build_understand_trace(state)
        emit("understand", "stage", "completed", understand)
        if pages_empty_disclosure(state):
            return self._run_empty_disclosure(state, understand, top_k)
        emit("router", "stage", "running")
        exact = self.intent_router.apply(state, self.retriever)
        router = build_router_trace(state, exact)
        emit("router", "stage", "completed", router)
        emit("retrieve", "stage", "running")
        hits = self.organizer.apply(state, exact)
        retrieve = build_retrieve_trace(hits, exact)
        ranked = self.ranker.apply(hits, state)
        state.last_ranked = [item.parent_asin for item in ranked]
        ranking = build_ranking_trace(ranked)
        emit(
            "retrieve",
            "stage",
            "completed",
            {**retrieve, "ranked_top": ranking.get("top") or []},
        )
        emit("decide", "stage", "running")
        plan, slate = self.clarifier.apply(state, ranked, top_k)
        decide = build_decide_trace(plan, slate)
        candidate_asins = [hit.parent_asin for hit in hits]
        response = self.responder.apply(
            state, self.retriever, candidate_asins, plan, slate
        )
        emit("decide", "stage", "completed", {**decide, "response": _compact_response(response)})
        return response, TurnTrace(
            understand=understand,
            router=router,
            retrieve=retrieve,
            ranking=ranking,
            decide=decide,
            response=response,
            exact=None if exact is None else set(exact),
        )

    def _run_empty_disclosure(
        self,
        state: SessionState,
        understand: dict,
        top_k: int,
    ) -> tuple[dict, TurnTrace]:
        emit("router", "stage", "skipped", {"why": EMPTY_DISCLOSURE_WHY})
        skip_nodes("router", *ROUTER_NODES, why=EMPTY_DISCLOSURE_WHY)
        emit("retrieve", "stage", "skipped", {"why": EMPTY_DISCLOSURE_WHY})
        skip_nodes("retrieve", *RETRIEVE_NODES, why=EMPTY_DISCLOSURE_WHY)
        leftovers = next_ranked_page(state, limit=max(0, min(EMPTY_DISCLOSURE_SLATE, int(top_k))))
        asins = leftovers
        emit("decide", "stage", "running")
        skip_nodes("decide", *DECIDE_PLAN_NODES, why=EMPTY_DISCLOSURE_WHY)
        plan = Plan(tuple(asins), None, 0.0, EMPTY_DISCLOSURE_WHY)
        slate = list(asins)
        decide = build_decide_trace(plan, slate)
        router = {
            "intention": state.intention,
            "override": False,
            "skipped": True,
            "reason": EMPTY_DISCLOSURE_WHY,
        }
        retrieve = {
            "hit_count": len(asins),
            "top": [
                {
                    "parent_asin": asin,
                    "score": 0.0,
                    "matched_constraints": [],
                }
                for asin in asins
            ],
            "scored_exact": False,
        }
        ranking = {
            "count": len(asins),
            "top": [{"parent_asin": asin, "probability": 0.0} for asin in asins],
        }
        response = self.responder.apply(
            state, self.retriever, asins, plan, slate
        )
        emit(
            "decide",
            "stage",
            "completed",
            {
                **decide,
                "response": _compact_response(response),
                "leftover": leftover_page_stats(state),
            },
        )
        return response, TurnTrace(
            understand=understand,
            router=router,
            retrieve=retrieve,
            ranking=ranking,
            decide=decide,
            response=response,
            exact=None,
        )
