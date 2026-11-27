# ruff: noqa: S101
"""A round of device actions that all succeeded ends on a fixed "Done."."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from custom_components.home_generative_agent.agent import graph as graph_module
from custom_components.home_generative_agent.agent.graph import (
    _action_done_reply,
    _after_tools,
    _round_only_acted,
)


def _intent(  # noqa: PLR0913
    *,
    success: list[str] | None = None,
    failed: list[str] | None = None,
    response_type: str = "action_done",
    call_id: str = "a1",
    name: str = "intent__HassTurnOff",
    encode_twice: bool = False,
    **extra: Any,
) -> ToolMessage:
    payload = {
        "speech": {},
        "response_type": response_type,
        "data": {
            "success": [
                {"name": n, "type": "entity", "id": f"light.{n}"}
                for n in (["kitchen"] if success is None else success)
            ],
            "failed": [
                {"name": n, "type": "entity", "id": f"light.{n}"}
                for n in (failed or [])
            ],
        },
        **extra,
    }
    content = json.dumps(payload)
    if encode_twice:
        content = json.dumps(content)
    return ToolMessage(content=content, name=name, tool_call_id=call_id)


def _state(*responses: ToolMessage) -> Any:
    return {
        "messages": [
            HumanMessage(content="turn off the kitchen light"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": r.name or "", "args": {}, "id": r.tool_call_id}
                    for r in responses
                ],
            ),
            *responses,
        ]
    }


@pytest.mark.parametrize(
    "responses",
    [
        [_intent()],
        [_intent(call_id="a1"), _intent(call_id="a2", name="light__HassLightSet")],
        [_intent(encode_twice=True)],
    ],
)
def test_a_round_of_successful_actions_ends_on_the_fixed_reply(
    responses: list[ToolMessage],
) -> None:
    assert _round_only_acted(responses)
    assert _after_tools(cast("Any", _state(*responses)), {}) == "action_done_reply"


@pytest.mark.parametrize(
    "responses",
    [
        # Nothing ran: the model has nothing to describe, but nothing to skip.
        [],
        # A lookup's answer is the reply.
        [
            ToolMessage(
                content="{}", name="homeassistant__GetLiveContext", tool_call_id="l"
            )
        ],
        # A lookup next to an action: the user asked for both.
        [
            _intent(),
            ToolMessage(
                content="{}", name="homeassistant__GetLiveContext", tool_call_id="l"
            ),
        ],
        # A failed or half-done action needs saying.
        [_intent(success=[], failed=["kitchen"])],
        [_intent(failed=["hall"])],
        [_intent(partial_failure="one light did not respond")],
        # Acted on nothing.
        [_intent(success=[])],
        # A query's answer.
        [_intent(response_type="query_answer")],
        # Not JSON: a script's or service tool's text result.
        [ToolMessage(content="Started", name="script__evening", tool_call_id="s")],
        # A held action asking for the PIN.
        [
            ToolMessage(
                content=json.dumps({"status": "requires_pin"}),
                name="intent__HassTurnOn",
                tool_call_id="p",
            )
        ],
        # An error result, whatever its content says.
        [
            ToolMessage(
                content=_intent().content,
                name="intent__HassTurnOff",
                tool_call_id="e",
                status="error",
            )
        ],
    ],
)
def test_anything_else_leaves_the_reply_to_the_model(
    responses: list[ToolMessage],
) -> None:
    assert not _round_only_acted(responses)
    # The model, or the PIN line for a held action: never the fixed reply.
    assert _after_tools(cast("Any", _state(*responses)), {}) != "action_done_reply"


def test_a_pending_pin_line_wins_over_the_fixed_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The PIN line is the reply then; "Done." next to it would say both."""
    monkeypatch.setattr(graph_module, "_pin_line_is_the_reply", lambda _config: True)

    assert _after_tools(cast("Any", _state(_intent())), {}) == "agent"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "expected"),
    [("ru", "Готово."), ("en", "Done."), ("cs-CZ", "Hotovo."), ("de", "Done.")],
)
async def test_the_fixed_reply_is_in_home_assistants_language(
    language: str, expected: str
) -> None:
    hass = SimpleNamespace(config=SimpleNamespace(language=language))
    config: Any = {"configurable": {"hass": hass}}

    result = await _action_done_reply(cast("Any", _state(_intent())), config)

    assert len(result["messages"]) == 1
    reply = result["messages"][0]
    assert isinstance(reply, AIMessage)
    assert reply.content == expected
    assert not reply.tool_calls


def test_the_fixed_reply_goes_on_to_the_summary_step() -> None:
    assert (
        "action_done_reply",
        "summarize_and_remove_messages",
    ) in graph_module.workflow.edges
