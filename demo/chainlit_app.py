"""Chainlit demo: chat → Agent.respond → product cards → next turn.

Uses the small ``data/catalog.demo.jsonl`` (real ASINs + main_image_url)
for fast local UI. Custom elements load from ``public/elements`` relative to
cwd, so run from the ``demo/`` directory:

    python -m chainlit run chainlit_app.py -w
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is importable when Chainlit loads this file as a script.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import chainlit as cl

from demo.profile import DEMO_USER_PROFILE
from demo.render import prepare_reply
from demo.session import get_session_id, next_turn, start_session
from starter.agent import Agent

# Small imaged subset for demo; evaluation still uses data/catalog.jsonl.
_DEMO_CATALOG = _REPO_ROOT / "data" / "catalog.demo.jsonl"

AGENT = Agent(
    _DEMO_CATALOG,
    understand_mode="regex",
)


@cl.on_chat_start
async def on_chat_start() -> None:
    session_id = start_session(cl.user_session)
    AGENT.reset(session_id, DEMO_USER_PROFILE)
    await cl.Message(
        content=(
            "Hi — tell me what you're looking for.\n\n"
            'Try: *"Running shoes for jogging under $150."*'
        )
    ).send()


async def handle_user_text(user_text: str) -> None:
    text = (user_text or "").strip()
    if not text:
        await cl.Message(content="Please type what you're looking for.").send()
        return

    turn = next_turn(cl.user_session)
    if turn is None:
        await cl.Message(
            content=(
                "This demo chat reached the 10-turn limit. "
                "Start a new chat to continue."
            )
        ).send()
        return

    session_id = get_session_id(cl.user_session)
    thinking = cl.Message(content="Searching the catalog…")
    await thinking.send()

    result = AGENT.respond(
        session_id=session_id,
        user_message=text,
        turn=turn,
        top_k=10,
    )
    state = AGENT.sessions.get(session_id)
    content, elements, actions = prepare_reply(
        AGENT.retriever,
        result,
        state=state,
        show_n=8,
    )
    thinking.content = content
    thinking.elements = elements
    thinking.actions = actions
    await thinking.update()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    await handle_user_text(message.content)


@cl.action_callback("quick_reply")
async def on_quick_reply(action: cl.Action) -> None:
    payload = action.payload or {}
    text = str(payload.get("text") or "").strip()
    if not text:
        return
    # Do not echo as an assistant bubble; treat the click as the next user turn.
    await handle_user_text(text)
