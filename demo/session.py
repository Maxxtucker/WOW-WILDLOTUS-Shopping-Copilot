"""Map one Chainlit chat to one Agent session (session_id + turn)."""

from __future__ import annotations

import uuid
from typing import Any

KEY_SESSION_ID = "agent_session_id"
KEY_TURN = "agent_turn"
MAX_TURN = 10


def start_session(user_session: Any) -> str:
    """Call once in on_chat_start. Returns the new session_id."""

    session_id = str(uuid.uuid4())
    user_session.set(KEY_SESSION_ID, session_id)
    user_session.set(KEY_TURN, 0)
    return session_id


def get_session_id(user_session: Any) -> str:
    sid = user_session.get(KEY_SESSION_ID)
    if not sid:
        raise RuntimeError("Chat session is not initialized; call reset first")
    return str(sid)


def next_turn(user_session: Any) -> int | None:
    """Increment turn. Returns the new turn, or None if over MAX_TURN."""

    turn = int(user_session.get(KEY_TURN) or 0) + 1
    if turn > MAX_TURN:
        return None
    user_session.set(KEY_TURN, turn)
    return turn
