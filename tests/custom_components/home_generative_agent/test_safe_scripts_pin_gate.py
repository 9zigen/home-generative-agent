# ruff: noqa: S101
"""
Scripts the user marks safe run as their own tool with no PIN.

A script that hands a command to the agent to run later cannot be read ahead:
its command is free text and it starts another script, so the gate held it on
every delayed request, a light included. The user can vouch for it instead;
the command it hands over is checked again when it runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest
from homeassistant.setup import async_setup_component

from custom_components.home_generative_agent.agent import graph
from custom_components.home_generative_agent.agent.graph import _is_critical_action
from custom_components.home_generative_agent.agent.helpers import (
    resolve_critical_action_policy,
)
from custom_components.home_generative_agent.const import (
    CONF_CRITICAL_ACTION_PIN_HASH,
    CONF_CRITICAL_ACTION_PIN_SALT,
    CONF_CRITICAL_ACTION_SAFE_SCRIPTS,
    RECOMMENDED_CRITICAL_ACTIONS,
)
from custom_components.home_generative_agent.core.utils import hash_pin

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

RULES = RECOMMENDED_CRITICAL_ACTIONS
LATER = frozenset({"script.schedule_command"})


def _call(action: str, entity_id: str, **data: Any) -> dict[str, Any]:
    step: dict[str, Any] = {"action": action, "target": {"entity_id": entity_id}}
    if data:
        step["data"] = data
    return step


@pytest.fixture
async def home(hass: HomeAssistant) -> HomeAssistant:
    """Set up a lock, a delayed-command pair of scripts and an unlock script."""
    hass.states.async_set("lock.front_door", "locked")
    assert await async_setup_component(
        hass,
        "script",
        {
            "script": {
                "schedule_command": {
                    "alias": "Schedule command",
                    "fields": {"command": {}, "delay_seconds": {}},
                    "sequence": [
                        _call(
                            "script.turn_on",
                            "script.run_command_later",
                            variables={
                                "command": "{{ command }}",
                                "delay_seconds": "{{ delay_seconds }}",
                            },
                        )
                    ],
                },
                "run_command_later": {
                    "alias": "Run command later",
                    "sequence": [
                        {"delay": {"seconds": "{{ delay_seconds | int }}"}},
                        {
                            "action": "conversation.process",
                            "data": {
                                "agent_id": "conversation.home_generative_agent",
                                "text": "{{ command }}",
                            },
                        },
                    ],
                },
                "let_in": {
                    "alias": "Let In",
                    "sequence": [_call("lock.unlock", "lock.front_door")],
                },
                "doorbell": {
                    "alias": "Doorbell",
                    "sequence": [{"delay": {"seconds": 1}}],
                },
            }
        },
    )
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "alias": "Open for the doorbell",
                    "triggers": [
                        {
                            "trigger": "state",
                            "entity_id": "script.doorbell",
                            "to": "on",
                        }
                    ],
                    "actions": [_call("lock.unlock", "lock.front_door")],
                }
            ]
        },
    )
    await hass.async_block_till_done()
    return hass


async def test_a_delayed_command_script_is_held_by_default(home: HomeAssistant) -> None:
    """Its command and the script it starts cannot be read ahead."""
    assert _is_critical_action({}, RULES, "script__schedule_command", home)


@pytest.mark.parametrize(
    "tool_name", ["script__schedule_command", "assist__script__schedule_command"]
)
async def test_a_safe_script_runs_with_no_pin(
    home: HomeAssistant, tool_name: str
) -> None:
    assert not _is_critical_action(
        {"command": "turn on the porch light", "delay_seconds": 60},
        RULES,
        tool_name,
        home,
        safe_scripts=LATER,
    )


async def test_safe_means_its_steps_are_not_read(home: HomeAssistant) -> None:
    """The user vouches for what the script does, whatever it does."""
    assert _is_critical_action({}, RULES, "script__let_in", home)
    assert not _is_critical_action(
        {}, RULES, "script__let_in", home, safe_scripts=frozenset({"script.let_in"})
    )


async def test_a_rule_naming_a_safe_script_still_holds_it(home: HomeAssistant) -> None:
    rules = [*RULES, {"domain": "script", "service": "schedule_command"}]
    assert _is_critical_action(
        {}, rules, "script__schedule_command", home, safe_scripts=LATER
    )


async def test_an_automation_a_safe_script_sets_off_is_still_read(
    home: HomeAssistant,
) -> None:
    """Its run turns the script on, which an automation may act on."""
    assert _is_critical_action(
        {},
        RULES,
        "script__doorbell",
        home,
        safe_scripts=frozenset({"script.doorbell"}),
    )


async def test_only_the_scripts_own_tool_is_let_through(home: HomeAssistant) -> None:
    """Another script, and other ways of running a safe one, are read as before."""
    assert _is_critical_action({}, RULES, "script__let_in", home, safe_scripts=LATER)
    assert _is_critical_action(
        {"name": "Let In", "domain": ["script"]},
        RULES,
        "HassTurnOn",
        home,
        safe_scripts=frozenset({"script.let_in"}),
    )


def test_without_hass_a_safe_script_is_held() -> None:
    """What reacts to its run cannot be read."""
    assert _is_critical_action(
        {}, RULES, "script__schedule_command", None, safe_scripts=LATER
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, frozenset()),
        ([], frozenset()),
        ("script.Schedule_Command", LATER),
        (
            [" script.schedule_command ", "lock.front_door", 3, "", None],
            LATER,
        ),
        ({"script.schedule_command": True}, frozenset()),
    ],
)
def test_the_safe_scripts_option_is_read_strictly(
    value: object, expected: frozenset[str]
) -> None:
    options = {} if value is None else {CONF_CRITICAL_ACTION_SAFE_SCRIPTS: value}
    assert resolve_critical_action_policy(options).safe_scripts == expected


def _guard_ctx(hass: HomeAssistant, options: dict[str, Any]) -> Any:
    hashed, salt = hash_pin("4826")
    config = {
        "configurable": {
            "options": {
                CONF_CRITICAL_ACTION_PIN_HASH: hashed,
                CONF_CRITICAL_ACTION_PIN_SALT: salt,
                **options,
            },
            "pending_actions": {},
            "user_id": "robot",
            "thread_id": "conv1",
            "hass": hass,
        }
    }
    return graph.ToolExecutionContext(
        hass=hass,
        store=MagicMock(),
        config=cast("Any", config),
        ha_llm_api=None,
        critical_actions=list(RULES),
        pin_enabled=True,
        pin_hash=hashed,
        pin_salt=salt,
        pending_actions={},
        state=cast("Any", {}),
    )


async def test_the_guard_reads_the_safe_scripts_option(home: HomeAssistant) -> None:
    """The option set in the form reaches the gate."""
    args = {"command": "turn on the porch light", "delay_seconds": 60}
    held = graph._critical_action_guard(
        "script__schedule_command", dict(args), _guard_ctx(home, {}), {"id": "c1"}
    )
    assert held is not None
    let_through = graph._critical_action_guard(
        "script__schedule_command",
        dict(args),
        _guard_ctx(
            home, {CONF_CRITICAL_ACTION_SAFE_SCRIPTS: ["script.schedule_command"]}
        ),
        {"id": "c2"},
    )
    assert let_through is None
