# ruff: noqa: S101
"""A reply that is only a PIN is checked by the agent itself, not the model."""

from __future__ import annotations

import json
import types
from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from custom_components.home_generative_agent.agent import graph
from custom_components.home_generative_agent.agent.helpers import (
    PIN_ANSWER_KWARG,
    disclose_pin_prompts,
    pin_only_reply_action,
    register_pending_action,
    start_pin_turn,
)
from custom_components.home_generative_agent.const import (
    CONF_CRITICAL_ACTION_PIN_HASH,
    CONF_CRITICAL_ACTION_PIN_SALT,
)
from custom_components.home_generative_agent.core.utils import hash_pin

from .test_conversation_units import (
    HGAConversationEntity,
    _DeltaChatLog,
    _pin_entity,
    frozen_assistant_content,  # noqa: F401 - fixture
    ha_conversation,
)

PIN = "3851"
UNLOCK_ARGS: dict[str, Any] = {"domain": ["lock"], "name": "Front Door"}


class _FakeAPI:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def async_call_tool(self, tool_input: Any) -> Any:
        self.calls.append(tool_input.tool_name)
        return {"success": True}


def _held(pending: dict[str, Any], thread_id: str = "conv1") -> str:
    """Hold an unlock in a turn and deliver its prompt; return the action id."""
    reply = start_pin_turn(pending, thread_id, "unlock the front door")
    action_id = register_pending_action(
        pending,
        {
            "tool_name": "HassTurnOff",
            "tool_args": dict(UNLOCK_ARGS),
            "user": "robot",
            "thread_id": thread_id,
            "turn_id": reply.turn_id,
        },
    )
    disclose_pin_prompts(pending, reply)
    assert action_id is not None
    return action_id


@pytest.mark.parametrize(
    "text",
    [
        PIN,
        "3 8 5 1",
        "PIN code 3851.",
        "Пин-код три восемь пять один",
        "три, восемь, пять, один.",
    ],
)
def test_a_pin_only_reply_names_its_action_and_pin(text: str) -> None:
    pending: dict[str, Any] = {}
    action_id = _held(pending)
    reply = start_pin_turn(pending, "conv1", text)

    assert pin_only_reply_action(pending, reply) == (action_id, PIN)


@pytest.mark.parametrize(
    "text",
    [
        "12",  # too short: the misheard-PIN path asks again
        "open the front door 3851",  # a request with a number in it
        "3851 and 1234",  # two numbers
        "never mind",
    ],
)
def test_other_replies_go_to_the_model(text: str) -> None:
    pending: dict[str, Any] = {}
    _held(pending)
    reply = start_pin_turn(pending, "conv1", text)

    assert pin_only_reply_action(pending, reply) is None


def test_a_pin_with_no_prompt_waiting_goes_to_the_model() -> None:
    pending: dict[str, Any] = {}
    _held(pending, "conv2")
    reply = start_pin_turn(pending, "conv1", PIN)

    assert pin_only_reply_action(pending, reply) is None


def _entity(api: _FakeAPI, pending: dict[str, Any]) -> tuple[Any, list[Any], Any]:
    entity = _pin_entity()
    recorded: list[Any] = []

    async def _record(thread_id: str, action_id: str, chat_log: Any) -> None:
        recorded.append((thread_id, action_id, chat_log.content[-1].content))

    entity._async_record_pin_turn = _record
    hashed, salt = hash_pin(PIN)
    cfg: dict[str, Any] = {
        "hass": None,
        "options": {
            CONF_CRITICAL_ACTION_PIN_HASH: hashed,
            CONF_CRITICAL_ACTION_PIN_SALT: salt,
        },
        "pending_actions": pending,
        "thread_id": "conv1",
        "user_id": "robot",
        "pin_owner": None,
        "ha_llm_api": api,
    }
    return entity, recorded, cfg


async def _answer(
    monkeypatch: pytest.MonkeyPatch, entity: Any, cfg: dict[str, Any], text: str
) -> tuple[Any, _DeltaChatLog, Any]:
    monkeypatch.setattr(
        ha_conversation,
        "async_get_result_from_chat_log",
        lambda _user_input, chat_log: chat_log.content[-1].content,
        raising=False,
    )
    reply = start_pin_turn(cfg["pending_actions"], "conv1", text)
    cfg["pin_reply"] = reply
    chat_log = _DeltaChatLog([])
    result = await HGAConversationEntity._async_confirm_pin_reply(
        entity, cast("Any", None), cast("Any", chat_log), reply, cast("Any", cfg)
    )
    return result, chat_log, reply


async def test_a_correct_pin_runs_the_action_without_the_model(
    monkeypatch: pytest.MonkeyPatch,
    frozen_assistant_content: None,  # noqa: ARG001, F811
) -> None:
    """The field test: the model said "wrong PIN" to the correct one, unchecked."""
    api = _FakeAPI()
    pending: dict[str, Any] = {}
    action_id = _held(pending)
    entity, recorded, cfg = _entity(api, pending)

    result, _chat_log, reply = await _answer(monkeypatch, entity, cfg, "3, 8, 5, 1.")

    assert api.calls == ["HassTurnOff"]
    assert reply.confirmed
    assert result == 'PIN accepted: unlock "Front Door".'
    assert action_id not in pending
    assert recorded == [("conv1", action_id, result)]


async def test_a_wrong_pin_is_counted_and_asked_again_in_fixed_words(
    monkeypatch: pytest.MonkeyPatch,
    frozen_assistant_content: None,  # noqa: ARG001, F811
) -> None:
    api = _FakeAPI()
    pending: dict[str, Any] = {}
    action_id = _held(pending)
    entity, recorded, cfg = _entity(api, pending)

    result, _chat_log, reply = await _answer(monkeypatch, entity, cfg, "1 2 3 4")

    assert api.calls == []
    assert reply.spent
    assert pending[action_id]["attempts"] == 1
    assert result.startswith("That PIN was incorrect.")
    # The microphone stays open for the retry.
    assert result.endswith("?")
    # Not tagged as answered: the request can still end unconfirmed.
    assert [r[1] for r in recorded] == [None]

    # The retry is checked the same way.
    result, _chat_log, reply = await _answer(monkeypatch, entity, cfg, PIN)
    assert api.calls == ["HassTurnOff"]
    assert result == 'PIN accepted: unlock "Front Door".'


async def test_a_pin_not_checked_is_left_to_the_model(
    monkeypatch: pytest.MonkeyPatch,
    frozen_assistant_content: None,  # noqa: ARG001, F811
) -> None:
    """Another user's action: refused before the check, nothing used up."""
    api = _FakeAPI()
    pending: dict[str, Any] = {}
    action_id = _held(pending)
    entity, recorded, cfg = _entity(api, pending)
    cfg["user_id"] = "someone else"

    result, chat_log, reply = await _answer(monkeypatch, entity, cfg, PIN)

    assert result is None
    assert chat_log.content == []
    assert not reply.spent
    assert not reply.confirmed
    assert pending[action_id]["attempts"] == 0
    assert recorded == []


async def test_the_turn_is_stored_with_the_pin_masked(
    frozen_assistant_content: None,  # noqa: ARG001, F811
) -> None:
    saver = InMemorySaver()
    entity = _pin_entity()
    entity.entry = types.SimpleNamespace(
        runtime_data=types.SimpleNamespace(store=None, checkpointer=saver)
    )
    app = graph.workflow.compile(checkpointer=saver)
    config: Any = {"configurable": {"thread_id": "conv1"}}
    await app.aupdate_state(
        config,
        {"messages": [HumanMessage(content="unlock the front door")]},
        as_node="summarize_and_remove_messages",
    )
    chat_log = _DeltaChatLog(
        [
            ha_conversation.AssistantContent(
                agent_id="conversation.hga",
                content='PIN accepted: unlock "Front Door".',
            )
        ]
    )

    await HGAConversationEntity._async_record_pin_turn(
        entity, "conv1", "action-1", cast("Any", chat_log)
    )

    state = await app.aget_state(config)
    human, answer = state.values["messages"][-2:]
    assert human.content == "[PIN]"
    assert answer.content == 'PIN accepted: unlock "Front Door".'
    assert answer.additional_kwargs[PIN_ANSWER_KWARG] == "action-1"
    # The next message starts a fresh run.
    assert state.next == ()


def _held_result(action_id: str) -> ToolMessage:
    return ToolMessage(
        content=json.dumps({"status": "requires_pin", "action_id": action_id}),
        tool_call_id="call-1",
        name="HassTurnOff",
    )


def test_an_answered_request_does_not_read_as_ended_unconfirmed() -> None:
    answered = AIMessage(
        content='PIN accepted: unlock "Front Door".',
        additional_kwargs={PIN_ANSWER_KWARG: "a1"},
    )
    messages = [_held_result("a1"), HumanMessage(content="[PIN]"), answered]

    marked = graph._mark_ended_pin_requests(messages, {})

    assert json.loads(cast("str", marked[0].content))["status"] == "ended"
    assert marked[1:] == messages[1:]


def test_a_request_the_model_confirmed_does_not_read_as_ended_unconfirmed() -> None:
    done = ToolMessage(
        content=json.dumps({"status": "completed", "action_id": "a1"}),
        tool_call_id="call-2",
        name="confirm_sensitive_action",
    )
    messages = [_held_result("a1"), HumanMessage(content="1 2 3 4"), done]

    marked = graph._mark_ended_pin_requests(messages, {})

    assert marked[1:] == messages[1:]


def test_a_request_answered_for_another_action_still_reads_as_ended() -> None:
    answered = AIMessage(content="ok", additional_kwargs={PIN_ANSWER_KWARG: "other"})
    refused = ToolMessage(
        content=json.dumps({"status": "awaiting_user_pin", "action_id": "a1"}),
        tool_call_id="call-2",
        name="confirm_sensitive_action",
    )
    messages = [_held_result("a1"), HumanMessage(content="x"), refused, answered]

    marked = graph._mark_ended_pin_requests(messages, {})

    assert marked[1].content == graph._ENDED_PIN_REQUEST_REPLY


async def test_an_action_dropped_before_the_check_is_answered_in_fixed_words(
    monkeypatch: pytest.MonkeyPatch,
    frozen_assistant_content: None,  # noqa: ARG001, F811
) -> None:
    """Expired by the time the PIN arrives: no model, nothing to confirm."""
    api = _FakeAPI()
    pending: dict[str, Any] = {}
    action_id = _held(pending)
    entity, recorded, cfg = _entity(api, pending)
    reply = start_pin_turn(pending, "conv1", PIN)
    # Expired after the turn started, before the check.
    pending[action_id]["created_at"] = "2000-01-01T00:00:00+00:00"
    cfg["pin_reply"] = reply
    monkeypatch.setattr(
        ha_conversation,
        "async_get_result_from_chat_log",
        lambda _user_input, chat_log: chat_log.content[-1].content,
        raising=False,
    )
    chat_log = _DeltaChatLog([])

    result = await HGAConversationEntity._async_confirm_pin_reply(
        entity, cast("Any", None), cast("Any", chat_log), reply, cast("Any", cfg)
    )

    assert api.calls == []
    assert action_id not in pending
    assert result == "Pending action not found or expired. Make the request again."
    assert recorded == [("conv1", None, result)]


async def test_the_hash_runs_off_the_event_loop() -> None:
    """PBKDF2 is slow; the direct path calls it from the conversation handler."""
    from custom_components.home_generative_agent.agent.tools import (  # noqa: PLC0415
        confirm_pending_action,
    )

    pending: dict[str, Any] = {}
    action_id = _held(pending)
    _, _, cfg = _entity(_FakeAPI(), pending)
    jobs: list[Any] = []

    async def _executor(func: Any, *args: Any) -> Any:
        jobs.append(func)
        return func(*args)

    cfg["hass"] = types.SimpleNamespace(
        async_add_executor_job=_executor,
        config=types.SimpleNamespace(language="en"),
    )
    cfg["pin_reply"] = start_pin_turn(pending, "conv1", "1 2 3 4")

    await confirm_pending_action(cast("Any", cfg), action_id, "1234")

    assert len(jobs) == 1
    assert pending[action_id]["attempts"] == 1
