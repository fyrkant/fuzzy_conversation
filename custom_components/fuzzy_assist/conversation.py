"""Conversation agent: built-in Assist first, fuzzy matching when it fails."""

from __future__ import annotations

import logging
from typing import Literal

from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import (
    async_should_expose,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    intent,
)
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import matcher
from .const import (
    CONF_FALLBACK_AGENT,
    CONF_STEP,
    CONF_THRESHOLD,
    DEFAULT_FALLBACK_AGENT,
    DEFAULT_STEP,
    DEFAULT_THRESHOLD,
    DOMAIN,
    SUPPORTED_DOMAINS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the conversation agent entity."""
    async_add_entities([FuzzyAssistAgent(entry)])


class FuzzyAssistAgent(conversation.ConversationEntity):
    """Wraps the built-in agent and catches what it misses."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = entry.entry_id

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """English only: the parser's vocabulary is English."""
        return ["en"]

    @property
    def _threshold(self) -> float:
        return float(self._entry.options.get(CONF_THRESHOLD, DEFAULT_THRESHOLD)) / 100

    @property
    def _step(self) -> int:
        return int(self._entry.options.get(CONF_STEP, DEFAULT_STEP))

    @property
    def _fallback(self) -> str:
        return self._entry.options.get(CONF_FALLBACK_AGENT, DEFAULT_FALLBACK_AGENT)

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        """Try the built-in agent, then fuzzy-match if it gave up."""
        builtin = await conversation.async_converse(
            self.hass,
            user_input.text,
            user_input.conversation_id,
            user_input.context,
            language=user_input.language,
            agent_id=self._fallback,
            device_id=user_input.device_id,
            satellite_id=user_input.satellite_id,
        )
        if builtin.response.response_type != intent.IntentResponseType.ERROR:
            return builtin

        fuzzy = await self._async_fuzzy(user_input)
        if fuzzy is None:
            return builtin  # keep the built-in error message
        return conversation.ConversationResult(
            response=fuzzy, conversation_id=builtin.conversation_id
        )

    # --- fuzzy path -------------------------------------------------------

    async def _async_fuzzy(
        self, user_input: conversation.ConversationInput
    ) -> intent.IntentResponse | None:
        cmd = matcher.parse(user_input.text, step=self._step)
        if cmd is None:
            _LOGGER.debug("No command in %r", user_input.text)
            return None

        candidates = self._candidates()
        match = matcher.resolve(cmd.target_phrase, candidates, threshold=self._threshold)
        _LOGGER.debug("%r -> %s, match %s", user_input.text, cmd, match)

        response = intent.IntentResponse(language=user_input.language)
        if match.ambiguous:
            names = ", ".join(c.name for c in match.ambiguous)
            response.async_set_error(
                intent.IntentResponseErrorCode.NO_VALID_TARGETS,
                f"Which one? {names}",
            )
            return response
        if match.candidate is None:
            return None

        target = match.candidate
        action, value = cmd.action, cmd.value
        if action in (matcher.ACTION_UP, matcher.ACTION_DOWN):
            current = self._current_brightness(target)
            delta = value if action == matcher.ACTION_UP else -(value or 0)
            action, value = matcher.ACTION_SET, max(1, min(100, current + delta))

        if action == matcher.ACTION_SET and (
            target.kind == "entity" and target.domain != "light"
        ):
            action = matcher.ACTION_ON  # switches/fans: "to 100%" just means on

        if target.kind == "entity":
            slots = {"name": {"value": target.name}, "domain": {"value": target.domain}}
        else:
            slots = {"area": {"value": target.name}, "domain": {"value": "light"}}

        if action == matcher.ACTION_SET:
            intent_type = "HassLightSet"
            slots["brightness"] = {"value": value}
            speech = f"{target.name} set to {value}%"
        elif action == matcher.ACTION_OFF:
            intent_type = intent.INTENT_TURN_OFF
            speech = f"Turned off {target.name}"
        else:
            intent_type = intent.INTENT_TURN_ON
            speech = f"Turned on {target.name}"

        try:
            result = await intent.async_handle(
                self.hass,
                DOMAIN,
                intent_type,
                slots,
                text_input=user_input.text,
                context=user_input.context,
                language=user_input.language,
                assistant=conversation.DOMAIN,
                device_id=user_input.device_id,
                satellite_id=user_input.satellite_id,
                conversation_agent_id=user_input.agent_id,
            )
        except intent.IntentError as err:
            _LOGGER.debug("Intent %s failed: %s", intent_type, err)
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                f"Sorry, I couldn't do that for {target.name}",
            )
            return response

        if not result.speech.get("plain", {}).get("speech"):
            result.async_set_speech(speech)
        return result

    # --- helpers ------------------------------------------------------------

    def _candidates(self) -> list[matcher.Candidate]:
        """Exposed lights/switches/fans plus the areas that contain them."""
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        area_reg = ar.async_get(self.hass)

        result: list[matcher.Candidate] = []
        area_ids: set[str] = set()
        for state in self.hass.states.async_all(SUPPORTED_DOMAINS):
            if not async_should_expose(self.hass, conversation.DOMAIN, state.entity_id):
                continue
            names = [state.name]
            entry = ent_reg.async_get(state.entity_id)
            if entry is not None:
                names.extend(a for a in entry.aliases if isinstance(a, str))
                if (area_id := self._area_of(entry, dev_reg)) is not None:
                    area_ids.add(area_id)
            result.append(
                matcher.Candidate(
                    "entity", state.entity_id, state.name, state.domain, tuple(names)
                )
            )

        for area_id in area_ids:
            if (area := area_reg.async_get_area(area_id)) is None:
                continue
            names = (area.name, *sorted(area.aliases))
            result.append(matcher.Candidate("area", area.id, area.name, None, names))
        return result

    @staticmethod
    def _area_of(entry: er.RegistryEntry, dev_reg: dr.DeviceRegistry) -> str | None:
        if entry.area_id:
            return entry.area_id
        if entry.device_id and (device := dev_reg.async_get(entry.device_id)):
            return device.area_id
        return None

    def _current_brightness(self, target: matcher.Candidate) -> int:
        """Brightness in % of the target (brightest light for an area)."""
        if target.kind == "entity":
            return _pct(self.hass.states.get(target.id))

        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        best = 0
        for state in self.hass.states.async_all("light"):
            entry = ent_reg.async_get(state.entity_id)
            if entry is None or self._area_of(entry, dev_reg) != target.id:
                continue
            if not async_should_expose(self.hass, conversation.DOMAIN, state.entity_id):
                continue
            best = max(best, _pct(state))
        return best


def _pct(state: State | None) -> int:
    if state is None or state.state != "on":
        return 0
    brightness = state.attributes.get("brightness")
    if brightness is None:
        return 100  # on/off-only light
    return round(int(brightness) / 255 * 100)
