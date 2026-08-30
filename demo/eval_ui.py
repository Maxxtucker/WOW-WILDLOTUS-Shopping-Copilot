"""Chainlit widgets for the demo evaluator dock."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import chainlit as cl

from demo.eval_harness import (
    EVALUATORS,
    StepState,
    apply_step_response,
    group_metrics,
    evaluator_is_supported,
    normalize_evaluator,
    run_evaluate,
    sample_summaries,
    select_samples,
    start_step_run,
)

EVAL_COMMAND = {
    "id": "Eval",
    "icon": "flask-conical",
    "description": "Choose local_evaluator or agent_evaluator",
    "button": True,
}


def _dump_props(props: dict) -> str:
    return json.dumps(props, default=str)


async def _update_element(element: cl.CustomElement, props: dict) -> None:
    element.props = props
    element.content = _dump_props(props)
    await element.update()


def picker_props(**overrides: Any) -> dict:
    catalog = cl.user_session.get("eval_catalog")
    if not isinstance(catalog, list):
        catalog = sample_summaries()
        cl.user_session.set("eval_catalog", catalog)
    props = {
        "evaluators": list(EVALUATORS),
        "selectedEvaluator": "",
        "catalog": catalog,
        "selection": "one",
        "sampleId": catalog[0]["sample_id"] if catalog else "",
        "rangeStart": "1",
        "rangeEnd": "10",
        "randomN": "5",
        "mode": "auto",
        "status": "idle",
        "statusDetail": "",
        "selectedCount": 0,
        "warning": "",
        "canStep": False,
        "total": len(catalog),
    }
    props.update(overrides)
    return props


async def open_picker() -> None:
    existing = cl.user_session.get("eval_picker_el")
    if existing is not None:
        props = cl.user_session.get("eval_picker_props") or picker_props()
        props["status"] = "idle"
        props["statusDetail"] = ""
        props["canStep"] = False
        await _update_element(existing, props)
        cl.user_session.set("eval_picker_props", props)
        return
    await asyncio.to_thread(sample_summaries)
    props = picker_props()
    message = cl.Message(content="", author="Evaluator")
    await message.send()
    element = cl.CustomElement(
        name="EvaluatorPicker",
        props=props,
        display="inline",
    )
    await element.send(for_id=message.id)
    cl.user_session.set("eval_picker_el", element)
    cl.user_session.set("eval_picker_props", props)


async def refresh_picker(**updates: Any) -> None:
    props = cl.user_session.get("eval_picker_props") or picker_props()
    props.update(updates)
    element = cl.user_session.get("eval_picker_el")
    if element is not None:
        await _update_element(element, props)
    cl.user_session.set("eval_picker_props", props)


async def send_score_card(*, kind: str, payload: dict) -> None:
    message = cl.Message(content="", author="Evaluator")
    await message.send()
    card = cl.CustomElement(
        name="EvalScoreCard",
        props={"kind": kind, **payload},
        display="inline",
    )
    await card.send(for_id=message.id)


def _samples_from_payload(payload: dict) -> list[dict]:
    return select_samples(
        str(payload.get("selection") or "one"),
        sample_id=payload.get("sampleId") or payload.get("sample_id"),
        start=payload.get("rangeStart") or payload.get("start"),
        end=payload.get("rangeEnd") or payload.get("end"),
        n=payload.get("randomN") or payload.get("n"),
    )


def _cancel_flag() -> dict:
    flag = cl.user_session.get("eval_cancel")
    if not isinstance(flag, dict):
        flag = {"cancelled": False}
        cl.user_session.set("eval_cancel", flag)
    return flag


async def run_auto(payload: dict) -> None:
    from demo.chainlit_app import get_agent

    evaluator = normalize_evaluator(payload.get("evaluator") or payload.get("selectedEvaluator"))
    if not evaluator_is_supported(evaluator):
        await refresh_picker(status="error", statusDetail="Select local_evaluator or agent_evaluator first.")
        return
    try:
        samples = _samples_from_payload(payload)
    except ValueError as exc:
        await refresh_picker(status="error", statusDetail=str(exc))
        return
    flag = {"cancelled": False}
    cl.user_session.set("eval_cancel", flag)
    await refresh_picker(
        status="running",
        canStep=False,
        selectedCount=len(samples),
        statusDetail=f"Running {len(samples)} session(s)…",
        warning=(
            f"All {len(samples)} sessions × up to 10 live NLU turns can take a long time."
            if len(samples) >= 50
            else ""
        ),
    )
    try:
        agent = get_agent()
    except Exception as exc:
        await refresh_picker(status="error", statusDetail=str(exc))
        return
    finished: list[dict] = []
    for index, sample in enumerate(samples, start=1):
        if flag.get("cancelled"):
            await refresh_picker(
                status="idle",
                statusDetail=f"Cancelled after {len(finished)} session(s).",
                canStep=False,
            )
            if finished:
                await send_score_card(kind="group", payload=group_metrics(finished))
            return
        sample_id = str(sample.get("sample_id") or "")
        await refresh_picker(
            status="running",
            statusDetail=f"Running {sample_id} ({index}/{len(samples)})",
            selectedCount=len(samples),
        )
        try:
            result = await asyncio.to_thread(run_evaluate, agent, [sample], evaluator)
        except Exception as exc:
            await refresh_picker(status="error", statusDetail=str(exc))
            return
        sessions = result.get("sessions") if isinstance(result, dict) else None
        row = sessions[0] if sessions else None
        if not isinstance(row, dict):
            await refresh_picker(status="error", statusDetail="Evaluator returned no session.")
            return
        finished.append(row)
        await send_score_card(kind="session", payload=row)
    await send_score_card(kind="group", payload=group_metrics(finished))
    await refresh_picker(
        status="done",
        statusDetail=f"Finished {len(finished)} session(s).",
        canStep=False,
    )


async def _reset_eval_agent(state: StepState) -> None:
    from demo.chainlit_app import get_agent

    agent = get_agent()
    profile = state.current_sample.get("user_profile")
    if not isinstance(profile, dict):
        profile = {}
    await asyncio.to_thread(agent.reset, state.session_id, profile)


async def play_pending_turn(state: StepState) -> None:
    from demo.chainlit_app import handle_user_text

    if state.cancelled or _cancel_flag().get("cancelled"):
        await refresh_picker(status="idle", statusDetail="Cancelled.", canStep=False)
        if state.finished:
            await send_score_card(kind="group", payload=group_metrics(state.finished))
        return
    sample_id = str(state.current_sample.get("sample_id") or "")
    text = state.pending_message
    turn = state.turn
    await cl.Message(
        content=f"**Customer** (`{sample_id}` · turn {turn}): {text}",
        author="Evaluator",
    ).send()
    await refresh_picker(
        status="step",
        canStep=False,
        statusDetail=f"{sample_id} turn {turn}…",
        selectedCount=len(state.samples),
    )
    result = await handle_user_text(text, session_id=state.session_id, turn=turn)
    # ScenarioUserAgent may call a remote OpenAI-compatible endpoint while
    # producing the next customer message.  Keep that synchronous call off
    # Chainlit's event loop so the dock remains responsive in agent mode.
    outcome = await asyncio.to_thread(apply_step_response, state, result)
    if outcome.get("session_done"):
        session_row = outcome.get("session")
        if isinstance(session_row, dict):
            await send_score_card(kind="session", payload=session_row)
        if outcome.get("group_done"):
            await send_score_card(kind="group", payload=group_metrics(state.finished))
            await refresh_picker(
                status="done",
                canStep=False,
                statusDetail=f"Finished {len(state.finished)} session(s).",
            )
            cl.user_session.set("eval_step", None)
            return
        await _reset_eval_agent(state)
        next_id = str(state.current_sample.get("sample_id") or "")
        await refresh_picker(
            status="step",
            canStep=True,
            statusDetail=f"Next sample ready: {next_id}",
        )
        return
    await refresh_picker(
        status="step",
        canStep=True,
        statusDetail=f"Next: {sample_id} turn {state.turn}",
    )


async def run_step(payload: dict) -> None:
    evaluator = normalize_evaluator(payload.get("evaluator") or payload.get("selectedEvaluator"))
    if not evaluator_is_supported(evaluator):
        await refresh_picker(status="error", statusDetail="Select local_evaluator or agent_evaluator first.")
        return
    try:
        samples = _samples_from_payload(payload)
    except ValueError as exc:
        await refresh_picker(status="error", statusDetail=str(exc))
        return
    cl.user_session.set("eval_cancel", {"cancelled": False})
    try:
        # Starting a step run generates the first customer message.  In
        # agent_evaluator mode that can involve a synchronous LLM request.
        state = await asyncio.to_thread(start_step_run, samples, evaluator)
    except ValueError as exc:
        await refresh_picker(status="error", statusDetail=str(exc))
        return
    cl.user_session.set("eval_step", state)
    await refresh_picker(
        status="step",
        selectedCount=len(samples),
        warning=(
            f"All {len(samples)} sessions × up to 10 live NLU turns can take a long time."
            if len(samples) >= 50
            else ""
        ),
    )
    await _reset_eval_agent(state)
    await play_pending_turn(state)


async def step_next() -> None:
    state = cl.user_session.get("eval_step")
    if not isinstance(state, StepState):
        await refresh_picker(status="error", statusDetail="No step-through run is active.")
        return
    await play_pending_turn(state)


async def cancel_eval() -> None:
    flag = _cancel_flag()
    flag["cancelled"] = True
    state = cl.user_session.get("eval_step")
    if isinstance(state, StepState):
        state.cancelled = True
        if state.finished:
            await send_score_card(kind="group", payload=group_metrics(state.finished))
        cl.user_session.set("eval_step", None)
    await refresh_picker(status="idle", statusDetail="Cancelled.", canStep=False)
