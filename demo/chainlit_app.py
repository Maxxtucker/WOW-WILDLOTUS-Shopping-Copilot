"""Chainlit demo: live pipeline circuit over the production Agent.

Uses the full ``data/catalog.jsonl`` catalog and default live NLU — the same
``TurnPipeline`` path as ``scripts/nlu_console.py``. The Eval composer button
opens a local-evaluator dock over ``data/public_set.jsonl`` (demo-only; the
agent package does not read those labels). Custom elements load from
``public/elements`` relative to cwd, so run from the ``demo/`` directory:

    . ..\\scripts\\load_nlu_env.ps1
    python -m chainlit run chainlit_app.py -w --port 8005

Each circuit stage reveal also prints turn_delta / session / router / retrieve
top-10 / decide+respond on this terminal.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import chainlit as cl

from agent.progress import progress_listener
from demo.node_catalog import NODE_CATALOG, STAGE_BLURBS
from demo.profile import DEMO_USER_PROFILE
from demo.progress_ui import (
    apply_event,
    apply_understand_event,
    apply_understand_from_trace,
    empty_circuit_state,
    empty_inspect_turn,
    finalize_circuit,
)
from demo.eval_ui import (
    EVAL_COMMAND,
    cancel_eval,
    configure_picker,
    open_picker,
    run_auto,
    run_step,
    step_next,
)
from demo.render import prepare_reply
from demo.turn_monitor import maybe_log_progress_event
from demo.session import get_session_id, next_turn, start_session
from starter.agent import Agent
from agent.decide.clarification.utility import DEFAULT_SLIDER_POSITION

_FULL_CATALOG = _REPO_ROOT / "data" / "catalog.jsonl"
_AGENT: Agent | None = None
_AGENT_LOCK = threading.Lock()
_AGENT_ERROR: str | None = None


def get_agent() -> Agent:
    """Build the process-wide Agent once (full catalog + live NLU)."""

    global _AGENT, _AGENT_ERROR
    with _AGENT_LOCK:
        if _AGENT is not None:
            return _AGENT
        if _AGENT_ERROR is not None:
            raise RuntimeError(_AGENT_ERROR)
        try:
            _AGENT = Agent(_FULL_CATALOG)
        except Exception as exc:
            _AGENT_ERROR = str(exc)
            raise
        return _AGENT


async def _update_element(element: cl.CustomElement, props: dict) -> None:
    element.props = props
    await element.update()


async def _deliver_assistant(
    reply_msg: cl.Message,
    content: str,
    elements: list,
    actions: list,
    *,
    fallback_msg: cl.Message | None = None,
) -> None:
    """Write the reply onto a message that was already sent this turn.

    After a long NLU turn a fresh Message.send() can vanish on reconnect.
    Updating the placeholder (same path as the live circuit) keeps the text.
    """

    text = (content or "").strip() or "I finished this turn but had nothing to say."
    custom = [el for el in (elements or []) if isinstance(el, cl.CustomElement)]
    reply_msg.content = text
    reply_msg.elements = []
    reply_msg.actions = list(actions or [])
    last_exc: Exception | None = None
    for _ in range(3):
        try:
            await reply_msg.update()
            for el in custom:
                el.display = "inline"
                await el.send(for_id=reply_msg.id)
            return
        except Exception as exc:
            last_exc = exc
            await asyncio.sleep(0.4)
    try:
        await cl.Message(content=text, elements=elements, actions=actions).send()
        return
    except Exception as exc:
        last_exc = exc
    if fallback_msg is not None:
        fallback_msg.content = text
        try:
            await fallback_msg.update()
            return
        except Exception as exc:
            last_exc = exc
    if last_exc is not None:
        raise last_exc


def _inspector_props(turns: list[dict], turn: int | None) -> dict:
    return {
        "turns": turns,
        "expanded_turn": turn,
        "selected_node": cl.user_session.get("inspect_node") or "",
        "expanded": bool(cl.user_session.get("inspect_expanded", True)),
        "active_graph": cl.user_session.get("inspect_graph") or "understand",
        "catalog": NODE_CATALOG,
        "stage_blurbs": STAGE_BLURBS,
    }


async def _publish_sidebar(turns: list[dict], expanded_turn: int | None) -> None:
    panel = cl.CustomElement(
        name="NodeInspector",
        props=_inspector_props(turns, expanded_turn),
        display="side",
    )
    sidebar = getattr(cl, "ElementSidebar", None)
    expanded = bool(cl.user_session.get("inspect_expanded", True))
    if sidebar is not None:
        await sidebar.set_title("Inspect" if expanded else "")
        await sidebar.set_elements([panel])
        return
    await panel.send()


async def _show_recommendation_preference() -> None:
    props = {
        "position": DEFAULT_SLIDER_POSITION,
        "locked": False,
    }
    message = cl.Message(content="")
    await message.send()
    element = cl.CustomElement(
        name="RecommendationPreference",
        props=props,
        display="inline",
    )
    await element.send(for_id=message.id)
    cl.user_session.set("recommendation_preference_el", element)
    cl.user_session.set("recommendation_preference_props", props)


async def _lock_recommendation_preference() -> None:
    props = dict(
        cl.user_session.get("recommendation_preference_props")
        or {
            "position": DEFAULT_SLIDER_POSITION,
            "locked": False,
        }
    )
    if props.get("locked"):
        return
    props["locked"] = True
    element = cl.user_session.get("recommendation_preference_el")
    if element is not None:
        await _update_element(element, props)
    cl.user_session.set("recommendation_preference_props", props)


def _circuits_by_turn() -> dict:
    store = cl.user_session.get("circuits_by_turn")
    if not isinstance(store, dict):
        store = {}
        cl.user_session.set("circuits_by_turn", store)
    return store


def _parse_turn(value: object) -> int | None:
    try:
        turn = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return turn if turn > 0 else None


def _remember_circuit_selection(
    turn: int | None,
    *,
    selected_node: str | None = None,
    view_graph: str | None = None,
) -> None:
    """Store inspect selection on circuit state without remounting the canvas."""
    key = _parse_turn(turn)
    if key is None:
        return
    entry = _circuits_by_turn().get(key)
    if not isinstance(entry, dict):
        return
    state = entry.get("state")
    if not isinstance(state, dict):
        return
    if selected_node is not None:
        state["selectedNode"] = selected_node
    if view_graph is not None:
        state["viewGraph"] = view_graph


async def _sync_circuit(
    turn: int | None,
    *,
    selected_node: str | None = None,
    view_graph: str | None = None,
) -> None:
    key = _parse_turn(turn)
    if key is None:
        return
    entry = _circuits_by_turn().get(key)
    if not isinstance(entry, dict):
        return
    state = entry.get("state")
    element = entry.get("el")
    if not isinstance(state, dict) or element is None:
        return
    if selected_node is not None:
        state["selectedNode"] = selected_node
    if view_graph is not None:
        state["viewGraph"] = view_graph
    await _update_element(element, state)


@cl.on_chat_start
async def on_chat_start() -> None:
    session_id = start_session(cl.user_session)
    cl.user_session.set("inspect_turns", [])
    cl.user_session.set("inspect_node", "")
    cl.user_session.set("inspect_expanded", True)
    cl.user_session.set("inspect_graph", "understand")
    cl.user_session.set("inspect_turn", 0)
    cl.user_session.set("circuits_by_turn", {})
    cl.user_session.set("recommendation_preference_el", None)
    cl.user_session.set("recommendation_preference_props", None)
    try:
        await cl.context.emitter.set_commands([EVAL_COMMAND])
    except Exception:
        pass

    preparing = cl.Message(content="")
    await preparing.send()
    prep = cl.CustomElement(
        name="PipelinePreparing",
        props={
            "title": "Starting agent",
            "status": "running",
            "detail": "Loading catalog index and warming NLU…",
        },
        display="inline",
    )
    await prep.send(for_id=preparing.id)

    try:
        agent = await asyncio.to_thread(get_agent)
        agent.reset(session_id, DEMO_USER_PROFILE)
        await _update_element(
            prep,
            {
                "title": "Starting agent",
                "status": "completed",
                "detail": "Ready. Full catalog + live NLU, same path as nlu_console.",
            },
        )
    except Exception as exc:
        await _update_element(
            prep,
            {
                "title": "Starting agent",
                "status": "error",
                "detail": str(exc),
            },
        )
        return

    await _publish_sidebar([], 0)
    await _show_recommendation_preference()
    await cl.Message(
        content=(
            "Hi — tell me what you're looking for.\n\n"
            "Each turn lights understand, then intent router, retrieve, and decide. "
            "The full branch graph stays visible; only the path taken this turn lights up. "
            "Click any node to inspect its function, meaning, and this-turn input/output.\n\n"
            "Use **Eval** next to the composer to score public_set sessions "
            "with the official local evaluator.\n\n"
            'Try: *"I\'d prefer something green and easy to wear."*'
        )
    ).send()


async def handle_user_text(
    user_text: str,
    *,
    session_id: str | None = None,
    turn: int | None = None,
) -> dict | None:
    text = (user_text or "").strip()
    if not text:
        await cl.Message(content="Please type what you're looking for.").send()
        return None

    main_chat_turn = session_id is None

    if turn is None:
        turn = next_turn(cl.user_session)
    if turn is None:
        await cl.Message(
            content=(
                "This demo chat reached the 10-turn limit. "
                "Start a new chat to continue."
            )
        ).send()
        return None

    try:
        agent = get_agent()
    except Exception as exc:
        await cl.Message(content=f"Agent is not ready: {exc}").send()
        return None

    if session_id is None:
        session_id = get_session_id(cl.user_session)
    if main_chat_turn:
        sessions = getattr(agent, "sessions", {})
        state = sessions.get(session_id) if hasattr(sessions, "get") else None
        if state is not None:
            current_props = dict(
                cl.user_session.get("recommendation_preference_props") or {}
            )
            current_props["position"] = state.recommendation_preference_position
            cl.user_session.set("recommendation_preference_props", current_props)
        await _lock_recommendation_preference()

    circuit = empty_circuit_state()
    circuit["turn"] = turn
    circuit["selectedNode"] = ""
    circuit["viewGraph"] = ""
    turn_state = empty_inspect_turn(turn, text, circuit["nodes"])
    turns: list[dict] = list(cl.user_session.get("inspect_turns") or [])
    turns = [row for row in turns if row.get("turn") != turn]
    turns.append(turn_state)
    cl.user_session.set("inspect_turns", turns)
    cl.user_session.set("inspect_turn", turn)
    cl.user_session.set("inspect_graph", "understand")

    progress_msg = cl.Message(content="")
    await progress_msg.send()
    circuit_el = cl.CustomElement(
        name="PipelineCircuit",
        props=circuit,
        display="inline",
    )
    await circuit_el.send(for_id=progress_msg.id)
    reply_msg = cl.Message(content="Working on this turn…")
    await reply_msg.send()
    store = _circuits_by_turn()
    store[turn] = {"state": circuit, "el": circuit_el}
    cl.user_session.set("circuits_by_turn", store)
    await _publish_sidebar(turns, turn)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    def on_event(event: dict) -> None:
        maybe_log_progress_event(
            event,
            turn=turn,
            state=agent.sessions.get(session_id),
            retriever=agent.retriever,
        )
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def pump() -> None:
        while True:
            event = await queue.get()
            if event is None:
                break
            apply_event(circuit, event)
            apply_understand_event(turn_state, event)
            if (
                cl.user_session.get("inspect_turn") == turn
                and not circuit.get("viewGraph")
            ):
                cl.user_session.set(
                    "inspect_graph", circuit.get("activeGraph") or "understand"
                )
            await _update_element(circuit_el, circuit)
            if event.get("node") == "stage" and event.get("status") in {
                "completed",
                "skipped",
                "error",
            }:
                await _publish_sidebar(turns, turn)

    pump_task = asyncio.create_task(pump())

    def run_turn():
        with progress_listener(on_event):
            return agent.respond_traced(
                session_id=session_id,
                user_message=text,
                turn=turn,
                top_k=10,
            )

    try:
        result, trace = await asyncio.to_thread(run_turn)
    except Exception as exc:
        circuit["status"] = "error"
        circuit["error"] = str(exc)
        await queue.put(None)
        await pump_task
        await _update_element(circuit_el, circuit)
        await _deliver_assistant(
            reply_msg,
            f"Turn failed: {exc}",
            [],
            [],
            fallback_msg=progress_msg,
        )
        return None

    await queue.put(None)
    await pump_task
    apply_understand_from_trace(turn_state, trace)
    finalize_circuit(circuit, trace)
    await _update_element(circuit_el, circuit)
    cl.user_session.set("inspect_turns", turns)
    if cl.user_session.get("inspect_turn") == turn and not circuit.get("viewGraph"):
        cl.user_session.set("inspect_graph", "decide")

    state = agent.sessions.get(session_id)
    content, elements, actions = prepare_reply(
        agent.retriever,
        result,
        state=state,
        show_n=10,
    )
    await _deliver_assistant(
        reply_msg,
        content,
        elements,
        actions,
        fallback_msg=progress_msg,
    )
    await _publish_sidebar(turns, turn)
    return result


@cl.on_message
async def on_message(message: cl.Message) -> None:
    command = getattr(message, "command", None) or ""
    text = (message.content or "").strip()
    if command == EVAL_COMMAND["id"] or text.lower() == "/eval":
        await open_picker()
        return
    await handle_user_text(message.content)


@cl.action_callback("quick_reply")
async def on_quick_reply(action: cl.Action) -> None:
    payload = action.payload or {}
    text = str(payload.get("text") or "").strip()
    if not text:
        return
    await handle_user_text(text)


@cl.action_callback("set_recommendation_preference")
async def on_set_recommendation_preference(action: cl.Action) -> None:
    payload = action.payload or {}
    position = payload.get("position")
    try:
        agent = get_agent()
        session_id = get_session_id(cl.user_session)
        agent.set_recommendation_preference(session_id, position)
        state = agent.sessions[session_id]
    except (ValueError, RuntimeError) as exc:
        await cl.Message(content=f"Recommendation preference was not changed: {exc}").send()
        return

    props = {
        "position": state.recommendation_preference_position,
        "locked": state.recommendation_preference_locked,
    }
    element = cl.user_session.get("recommendation_preference_el")
    if element is not None:
        await _update_element(element, props)
    cl.user_session.set("recommendation_preference_props", props)


@cl.action_callback("inspect_node")
async def on_inspect_node(action: cl.Action) -> None:
    payload = action.payload or {}
    node = str(payload.get("node") or "").strip()
    turn = _parse_turn(payload.get("turn"))
    cl.user_session.set("inspect_node", node)
    cl.user_session.set("inspect_expanded", True)
    if turn is not None:
        cl.user_session.set("inspect_turn", turn)
    catalog_row = NODE_CATALOG.get(node) or {}
    stage = str(catalog_row.get("stage") or "")
    if stage:
        cl.user_session.set("inspect_graph", stage)
    _remember_circuit_selection(turn, selected_node=node, view_graph=stage or None)
    turns = list(cl.user_session.get("inspect_turns") or [])
    await _publish_sidebar(turns, cl.user_session.get("inspect_turn"))


@cl.action_callback("view_graph")
async def on_view_graph(action: cl.Action) -> None:
    payload = action.payload or {}
    graph = str(payload.get("graph") or "").strip()
    turn = _parse_turn(payload.get("turn"))
    if turn is not None:
        cl.user_session.set("inspect_turn", turn)
    if graph:
        cl.user_session.set("inspect_graph", graph)
    await _sync_circuit(turn, view_graph=graph)
    turns = list(cl.user_session.get("inspect_turns") or [])
    await _publish_sidebar(turns, cl.user_session.get("inspect_turn"))


@cl.action_callback("eval_configure")
async def on_eval_configure(action: cl.Action) -> None:
    await configure_picker(action.payload or {})


@cl.action_callback("eval_run")
async def on_eval_run(action: cl.Action) -> None:
    await run_auto(action.payload or {})


@cl.action_callback("eval_step_start")
async def on_eval_step_start(action: cl.Action) -> None:
    await run_step(action.payload or {})


@cl.action_callback("eval_step")
async def on_eval_step(action: cl.Action) -> None:
    del action
    await step_next()


@cl.action_callback("eval_cancel")
async def on_eval_cancel(action: cl.Action) -> None:
    del action
    await cancel_eval()


@cl.action_callback("toggle_inspector")
async def on_toggle_inspector(action: cl.Action) -> None:
    payload = action.payload or {}
    expanded = bool(payload.get("expanded", True))
    cl.user_session.set("inspect_expanded", expanded)
    turns = list(cl.user_session.get("inspect_turns") or [])
    await _publish_sidebar(turns, cl.user_session.get("inspect_turn"))
