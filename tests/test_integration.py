"""End-to-end tests inside a real Home Assistant instance (pytest-homeassistant)."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import (
    async_expose_entity,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import area_registry as ar, entity_registry as er, intent
from homeassistant.setup import async_setup_component

from custom_components.fuzzy_assist.const import DOMAIN

LIGHTS = {
    "light.living_room_ceiling": ("Living Room Ceiling", "living_room", 128),
    "light.teak": ("Teak", "living_room", 200),
    "light.kitchen_ceiling": ("Kitchen Ceiling", "kitchen", 255),
    "light.bedroom_ceiling": ("Bedroom Ceiling", "bedroom", 100),
    "light.desk": ("Desk", "bedroom", 50),
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components/fuzzy_assist."""
    return


@pytest.fixture
async def setup(hass: HomeAssistant):
    """HA with areas, lights, exposure and Fuzzy Assist set up."""
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    assert await async_setup_component(hass, "intent", {})
    assert await async_setup_component(hass, "light", {})

    area_reg = ar.async_get(hass)
    ent_reg = er.async_get(hass)
    areas = {}
    for area_id, name in (
        ("living_room", "Living Room"),
        ("kitchen", "Kitchen"),
        ("bedroom", "Bedroom"),
    ):
        areas[area_id] = area_reg.async_create(name).id

    for entity_id, (name, area_key, brightness) in LIGHTS.items():
        object_id = entity_id.split(".")[1]
        entry = ent_reg.async_get_or_create(
            "light", "test", object_id, suggested_object_id=object_id,
            original_name=name,
        )
        ent_reg.async_update_entity(entry.entity_id, area_id=areas[area_key])
        hass.states.async_set(
            entry.entity_id,
            "on",
            {
                "friendly_name": name,
                "brightness": brightness,
                "supported_color_modes": ["brightness"],
                "color_mode": "brightness",
            },
        )
        async_expose_entity(hass, conversation.DOMAIN, entry.entity_id, True)

    calls_on = async_mock_service(hass, "light", "turn_on")
    calls_off = async_mock_service(hass, "light", "turn_off")

    entry = MockConfigEntry(domain=DOMAIN, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    agent_id = next(
        s.entity_id
        for s in hass.states.async_all("conversation")
        if s.entity_id != conversation.HOME_ASSISTANT_AGENT
    )
    return agent_id, calls_on, calls_off


def _ids(call) -> set[str]:
    eid = call.data["entity_id"]
    return set(eid) if isinstance(eid, list) else {eid}


async def _say(hass: HomeAssistant, agent_id: str, text: str):
    return await conversation.async_converse(
        hass, text, None, Context(), language="en", agent_id=agent_id
    )


async def test_builtin_still_handles_normal_commands(hass, setup):
    agent_id, calls_on, _ = setup
    result = await _say(hass, agent_id, "turn on the teak")
    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    assert _ids(calls_on[-1]) == {"light.teak"}


async def test_a_hundred_percent(hass, setup):
    agent_id, calls_on, _ = setup
    # Confirm the built-in agent alone fails this sentence
    plain = await _say(
        hass, conversation.HOME_ASSISTANT_AGENT,
        "Turn living room ceiling light to a hundred percent",
    )
    assert plain.response.response_type == intent.IntentResponseType.ERROR
    before = len(calls_on)

    result = await _say(hass, agent_id, "Turn living room ceiling light to a hundred percent")
    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE, (
        result.response.speech
    )
    assert len(calls_on) == before + 1
    assert _ids(calls_on[-1]) == {"light.living_room_ceiling"}
    assert calls_on[-1].data["brightness_pct"] == 100
    assert result.response.speech["plain"]["speech"]


async def test_area_a_hundred_percent(hass, setup):
    agent_id, calls_on, _ = setup
    result = await _say(hass, agent_id, "Turn living room light to a hundred percent")
    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE, (
        result.response.speech
    )
    targeted = set().union(*(_ids(c) for c in calls_on))
    assert {"light.living_room_ceiling", "light.teak"} <= targeted
    assert all(c.data["brightness_pct"] == 100 for c in calls_on)


async def test_sixty_percent_please(hass, setup):
    agent_id, calls_on, _ = setup
    result = await _say(hass, agent_id, "living room ceiling light at sixty percent please")
    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE, (
        result.response.speech
    )
    assert calls_on[-1].data == {"entity_id": "light.living_room_ceiling", "brightness_pct": 60}


async def test_misheard_name(hass, setup):
    agent_id, _, calls_off = setup
    result = await _say(hass, agent_id, "kill the kichen seiling lamp")
    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE, (
        result.response.speech
    )
    assert _ids(calls_off[-1]) == {"light.kitchen_ceiling"}


async def test_relative_brighter(hass, setup):
    agent_id, calls_on, _ = setup
    # Desk is at 50/255 ~ 20 %; "brighter" adds 20 -> 40 %
    result = await _say(hass, agent_id, "make the desk lamp brighter")
    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE, (
        result.response.speech
    )
    assert calls_on[-1].data == {"entity_id": "light.desk", "brightness_pct": 40}


async def test_ambiguous_asks_which(hass, setup):
    agent_id, calls_on, calls_off = setup
    result = await _say(hass, agent_id, "ceiling light off please")
    assert result.response.response_type == intent.IntentResponseType.ERROR
    assert "Which one" in result.response.speech["plain"]["speech"]
    assert not calls_off


async def test_gibberish_keeps_builtin_error(hass, setup):
    agent_id, calls_on, calls_off = setup
    result = await _say(hass, agent_id, "purple monkey dishwasher")
    assert result.response.response_type == intent.IntentResponseType.ERROR
    assert not calls_on and not calls_off



async def test_config_flow(hass: HomeAssistant):
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"threshold": 75, "step": 20, "fallback_agent": "conversation.home_assistant"},
    )
    assert result["type"] == "create_entry"
    assert result["options"]["threshold"] == 75
