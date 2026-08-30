"""Build Chainlit message parts from an Agent respond dict."""

from __future__ import annotations

from typing import Any

import chainlit as cl

from demo.actions import MORE_LIKE_THIS, build_dynamic_actions, clarification_prompt
from demo.hydrate import expand_recommendations_for_ui, hydrate_many
from demo.images import load_image_index

# Side-car from scripts/build_catalog_images.py (optional until built).
_IMAGE_INDEX = load_image_index()


def format_assistant_text(result: dict, cards: list[dict[str, Any]]) -> str:
    """Official agent message. Clarify chips still render under the shelf."""

    official = str(result.get("message") or "").strip()
    if official:
        return official
    if not cards:
        return (
            "I couldn't find a strong match yet.\n\n"
            "Tell me a bit more — budget, brand, or what you want it for."
        )
    return "Here are my strongest matches so far."


def build_elements(
    cards: list[dict[str, Any]],
    *,
    message: str = "",
    clarify_prompt: str | None = None,
    clarify_actions: list[dict[str, str]] | None = None,
) -> list[cl.CustomElement]:
    if not cards:
        return []
    return [
        cl.CustomElement(
            name="ProductShelf",
            props={
                "message": message,
                "hero": cards[0],
                "others": cards[1:11],
                "clarify_prompt": clarify_prompt or "",
                "clarify_actions": clarify_actions or [],
                "explore_label": MORE_LIKE_THIS["label"],
                "explore_text": MORE_LIKE_THIS["text"],
                "show_explore": True,
            },
        )
    ]


def visible_reply_content(
    result: dict,
    cards: list[dict[str, Any]],
    *,
    clarify_prompt: str | None = None,
) -> str:
    """Plain-text bubble body. Always non-empty when the agent returned a reply."""

    text = format_assistant_text(result, cards).strip()
    extra = cards_as_markdown(cards, clarify_prompt=clarify_prompt).strip()
    if extra:
        return f"{text}\n{extra}"
    prompt = (clarify_prompt or "").strip()
    if prompt:
        return f"{text}\n\n{prompt}"
    return text or "I finished this turn but had nothing to say."


def cards_as_markdown(
    cards: list[dict[str, Any]],
    *,
    clarify_prompt: str | None = None,
) -> str:
    """Fallback list when CustomElement assets are unavailable."""

    if not cards:
        return ""
    lines = ["", "**⭐ Best match**"]
    top = cards[0]
    price = top.get("price")
    price_text = "Price n/a" if price is None else f"${float(price):.2f}"
    lines.append(f"- **{top.get('title')}** — {price_text}")
    if len(cards) > 1:
        lines.append("")
        lines.append("**Other good matches**")
        for card in cards[1:]:
            price = card.get("price")
            price_text = "Price n/a" if price is None else f"${float(price):.2f}"
            lines.append(f"- {card.get('title')} — {price_text}")
    if clarify_prompt:
        lines.extend(["", clarify_prompt])
    return "\n".join(lines)


def prepare_reply(
    retriever: Any,
    result: dict,
    *,
    state: Any = None,
    show_n: int = 8,
    use_custom_elements: bool = True,
) -> tuple[str, list[cl.CustomElement], list[cl.Action]]:
    # UI may show a shelf of several; Agent.respond still used top_k=10 for scoring.
    # Planner slates are often size-1 while asking — pad display-only from the pool.
    display_recs = expand_recommendations_for_ui(
        retriever,
        state,
        result.get("recommendations") or [],
        limit=show_n,
    )
    cards = hydrate_many(
        retriever,
        display_recs,
        limit=show_n,
        image_index=_IMAGE_INDEX,
    )
    ask = result.get("ask_attribute")
    clarify = clarification_prompt(ask, cards)
    actions = build_dynamic_actions(
        state,
        cards,
        ask_attribute=ask,
    )
    content = visible_reply_content(result, cards, clarify_prompt=clarify)

    if use_custom_elements:
        # Cards only. Official text stays on the Message so a dropped
        # CustomElement still leaves a readable bubble.
        elements = build_elements(cards, message="", clarify_prompt="")
    else:
        elements = []
    return content, elements, actions
