"""Purpose: optional Qwen cross-encoder reranking for semantic shopping fit.

Input: SessionState, SearchHit head, and catalog product records.
Output: semantic scores and fused ranking weights, or None for safe fallback.
Role: lazy local reranker between retrieval scoring and slate planning.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, Sequence

from ...progress import progress_enabled
from ...retrieve.from_slots import (
    constraint_groups,
    preferred_groups,
    session_budget,
)

if TYPE_CHECKING:
    from ...retrieve.catalog.retriever import CatalogRetriever
    from ...retrieve.catalog.types import SearchHit
    from ...understand.state.session import SessionState


DEFAULT_MODEL = "Qwen/Qwen3-Reranker-0.6B"
SHOPPING_INSTRUCTION = (
    "Judge how well the product matches the current shopping request. "
    "Focus on semantic use case, style, comfort, fit, and stated soft preferences. "
    "Required numeric and exact constraints are checked separately. "
    "Aggregate profile preference tags are weak tie-breakers only. They must "
    "never override the current request. Do not invent missing attributes."
)


class CrossEncoderLike(Protocol):
    def predict(
        self,
        inputs: Sequence[tuple[str, str]],
        *,
        batch_size: int,
        show_progress_bar: bool,
        activation_fn: object,
    ) -> object:
        ...


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().casefold()
    if not value:
        return default
    return value not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return value if math.isfinite(value) else default


def reranker_env_file() -> Path:
    return Path(__file__).resolve().parents[3] / "scripts" / "reranker.env"


def load_reranker_env(
    path: Path | None = None,
    *,
    overwrite: bool = False,
) -> dict[str, str]:
    """Load local reranker settings without importing ML dependencies."""

    source = path or reranker_env_file()
    loaded: dict[str, str] = {}
    if not source.is_file():
        return loaded
    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if not key:
            continue
        if key in os.environ and os.environ[key] != "" and not overwrite:
            loaded[key] = os.environ[key]
            continue
        os.environ[key] = value
        loaded[key] = value
    return loaded


@dataclass(frozen=True, slots=True)
class RerankerConfig:
    """Runtime settings for an optional local CrossEncoder."""

    mode: str = "auto"
    model: str = DEFAULT_MODEL
    revision: str | None = None
    device: str | None = None
    local_files_only: bool = True
    top_n: int = 50
    batch_size: int = 8
    max_length: int = 512
    buying_weight: float = 0.35
    browsing_weight: float = 0.55
    temperature: float = 0.20

    @classmethod
    def from_env(cls) -> "RerankerConfig":
        mode = os.environ.get("AGENT_RERANKER_MODE", "auto").strip().casefold()
        if mode not in {"off", "auto", "required"}:
            mode = "auto"
        revision = os.environ.get("AGENT_RERANKER_REVISION", "").strip() or None
        device = os.environ.get("AGENT_RERANKER_DEVICE", "").strip() or None
        return cls(
            mode=mode,
            model=(
                os.environ.get("AGENT_RERANKER_MODEL", DEFAULT_MODEL).strip()
                or DEFAULT_MODEL
            ),
            revision=revision,
            device=device,
            local_files_only=_env_bool("AGENT_RERANKER_LOCAL_FILES_ONLY", True),
            top_n=_env_int("AGENT_RERANKER_TOP_N", 50),
            batch_size=_env_int("AGENT_RERANKER_BATCH_SIZE", 8),
            max_length=_env_int("AGENT_RERANKER_MAX_LENGTH", 512, minimum=128),
            buying_weight=max(
                0.0,
                min(1.0, _env_float("AGENT_RERANKER_BUYING_WEIGHT", 0.35)),
            ),
            browsing_weight=max(
                0.0,
                min(1.0, _env_float("AGENT_RERANKER_BROWSING_WEIGHT", 0.55)),
            ),
            temperature=max(
                0.01, _env_float("AGENT_RERANKER_TEMPERATURE", 0.20)
            ),
        )


def _format_groups(groups: Sequence[tuple[str, Sequence[str]]]) -> str:
    parts: list[str] = []
    for attribute, values in groups:
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        if cleaned:
            parts.append(f"{attribute}={' OR '.join(cleaned)}")
    return "; ".join(parts) or "(none)"


def build_shopping_query(state: "SessionState") -> str:
    """Build current-intent text; never replay raw history or superseded needs."""

    budget = session_budget(state, hard_only=True)
    if budget is None:
        budget_text = "(none)"
    else:
        minimum, maximum = budget
        if minimum is not None and maximum is not None:
            budget_text = f"{minimum:g} to {maximum:g}"
        elif maximum is not None:
            budget_text = f"at most {maximum:g}"
        elif minimum is not None:
            budget_text = f"at least {minimum:g}"
        else:
            budget_text = "(none)"
    profile = ", ".join(state.preference_tags) or "(none)"
    return "\n".join(
        (
            f"Category: {state.category or '(unspecified)'}",
            f"Required: {_format_groups(constraint_groups(state))}",
            f"Budget: {budget_text}",
            f"Preferred: {_format_groups(preferred_groups(state))}",
            f"Profile preference tags (weak tie-break only): {profile}",
        )
    )


def _compact(value: object, *, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        text = "; ".join(
            f"{key}: {item}" for key, item in value.items() if item not in (None, "", [])
        )
    elif isinstance(value, (list, tuple)):
        text = "; ".join(str(item) for item in value if item not in (None, ""))
    else:
        text = str(value)
    return " ".join(text.split())[:limit]


def build_product_document(product: dict[str, object]) -> str:
    """Create a concise catalog-native document for query-product scoring."""

    fields = (
        ("Title", _compact(product.get("title"), limit=300)),
        ("Category", _compact(product.get("categories"), limit=300)),
        ("Brand", _compact(product.get("store"), limit=120)),
        ("Price", _compact(product.get("price"), limit=80) or "unknown"),
        ("Features", _compact(product.get("features"), limit=900)),
        ("Details", _compact(product.get("details"), limit=700)),
        ("Description", _compact(product.get("description"), limit=900)),
    )
    return "\n".join(f"{name}: {value}" for name, value in fields if value)


def _sigmoid(value: float) -> float:
    if value >= 0:
        factor = math.exp(-value)
        return 1.0 / (1.0 + factor)
    factor = math.exp(value)
    return factor / (1.0 + factor)


def _identity(value: object) -> object:
    """Keep CrossEncoder outputs as logits before applying one stable sigmoid."""

    return value


def semantic_belief(
    hits: Sequence["SearchHit"],
    scores: Sequence[float],
    *,
    semantic_weight: float,
    temperature: float,
) -> list[tuple[str, float]]:
    """Rerank only the scored head and keep the unscored tail behind it."""

    if not hits or not scores:
        return []
    head_size = min(len(hits), len(scores))
    rows: list[tuple[int, str, float]] = []
    for index, (hit, semantic) in enumerate(zip(hits[:head_size], scores, strict=False)):
        base = 1.0 / math.log2(index + 2.0)
        combined = (1.0 - semantic_weight) * base + semantic_weight * semantic
        rows.append((index, hit.parent_asin, combined))
    rows.sort(key=lambda row: (-row[2], row[0], row[1]))

    maximum = max(row[2] for row in rows)
    weighted = [
        (parent_asin, math.exp((combined - maximum) / temperature))
        for _index, parent_asin, combined in rows
    ]
    tail_anchor = min(weight for _asin, weight in weighted) * 0.95
    for offset, hit in enumerate(hits[head_size:], start=1):
        weighted.append((hit.parent_asin, tail_anchor * math.exp(-offset / 80.0)))
    return weighted


class QwenSemanticReranker:
    """Lazy CrossEncoder wrapper with an offline-safe auto mode."""

    def __init__(
        self,
        config: RerankerConfig | None = None,
        *,
        model: CrossEncoderLike | None = None,
    ) -> None:
        load_reranker_env()
        self.config = config or RerankerConfig.from_env()
        self._model = model
        self._load_attempted = model is not None
        self.last_error: str | None = None
        self.last_trace: dict[str, object] = {}

    @property
    def enabled(self) -> bool:
        return self.config.mode != "off"

    def _ensure_model(self) -> CrossEncoderLike | None:
        if not self.enabled:
            return None
        if self._model is not None:
            return self._model
        if self._load_attempted:
            return None
        self._load_attempted = True
        try:
            # Some AutoProcessor paths do not consistently forward
            # local_files_only. Set both library-level offline flags before
            # importing the Hugging Face stack so evaluation never waits on
            # network retries.
            if self.config.local_files_only:
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(
                self.config.model,
                device=self.config.device,
                prompts={"shopping": SHOPPING_INSTRUCTION},
                default_prompt_name="shopping",
                revision=self.config.revision,
                local_files_only=self.config.local_files_only,
                trust_remote_code=False,
                max_length=self.config.max_length,
            )
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            if self.config.mode == "required":
                raise RuntimeError(
                    f"Required reranker {self.config.model!r} could not load: {exc}"
                ) from exc
            return None
        return self._model

    def score(
        self,
        state: "SessionState",
        hits: Sequence["SearchHit"],
        retriever: "CatalogRetriever",
    ) -> list[float] | None:
        self.last_trace = {}
        model = self._ensure_model()
        if model is None or not hits:
            return None
        query = build_shopping_query(state)
        pairs: list[tuple[str, str]] = []
        for hit in hits[: self.config.top_n]:
            product = retriever.get_product(hit.parent_asin)
            if product is None:
                pairs.append((query, "Product metadata unavailable."))
            else:
                pairs.append((query, build_product_document(product)))
        try:
            raw = model.predict(
                pairs,
                batch_size=self.config.batch_size,
                show_progress_bar=False,
                activation_fn=_identity,
            )
            values = raw.tolist() if hasattr(raw, "tolist") else list(raw)  # type: ignore[arg-type]
            if not isinstance(values, list):
                values = [values]
            values = [
                value[0]
                if isinstance(value, (list, tuple)) and len(value) == 1
                else value
                for value in values
            ]
            scores = [_sigmoid(float(value)) for value in values]
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            if self.config.mode == "required":
                raise RuntimeError(f"Required reranker inference failed: {exc}") from exc
            return None
        if len(scores) != len(pairs) or not all(math.isfinite(value) for value in scores):
            self.last_error = "reranker returned invalid score count or non-finite values"
            if self.config.mode == "required":
                raise RuntimeError(self.last_error)
            return None
        return scores

    def belief(
        self,
        state: "SessionState",
        hits: Sequence["SearchHit"],
        retriever: "CatalogRetriever",
    ) -> list[tuple[str, float]] | None:
        scores = self.score(state, hits, retriever)
        if scores is None:
            return None
        weight = (
            self.config.browsing_weight
            if state.intention == "browsing"
            else self.config.buying_weight
        )
        weighted = semantic_belief(
            hits,
            scores,
            semantic_weight=weight,
            temperature=self.config.temperature,
        )
        if not progress_enabled():
            return weighted
        head_size = min(len(hits), len(scores))
        combined = [
            {
                "parent_asin": hit.parent_asin,
                "base_rank_prior": round(1.0 / math.log2(index + 2.0), 8),
                "semantic": round(float(score), 8),
                "combined": round(
                    (1.0 - weight) * (1.0 / math.log2(index + 2.0))
                    + weight * float(score),
                    8,
                ),
            }
            for index, (hit, score) in enumerate(
                zip(hits[:head_size], scores, strict=False)
            )
        ]
        head_weights = weighted[:head_size]
        tail_weights = weighted[head_size:]
        self.last_trace = {
            "head_size": head_size,
            "tail_size": max(0, len(hits) - head_size),
            "semantic_weight": weight,
            "temperature": self.config.temperature,
            "semantic_scores": [
                {
                    "parent_asin": hit.parent_asin,
                    "semantic": round(float(score), 8),
                }
                for hit, score in zip(hits[:head_size], scores, strict=False)
            ][:5],
            "combined": sorted(
                combined,
                key=lambda row: (
                    -float(row["combined"]),
                    str(row["parent_asin"]),
                ),
            )[:5],
            "head_weights": [
                {"parent_asin": asin, "weight": round(float(value), 8)}
                for asin, value in head_weights[:5]
            ],
            "tail_anchor": (
                None
                if not tail_weights
                else round(float(tail_weights[0][1]), 8)
            ),
            "tail_decay_denominator": 80.0,
        }
        return weighted
