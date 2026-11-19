# Fuzzy Assist

A small, fully local conversation agent for Home Assistant that sits on top of the built-in Assist agent.

1. Every sentence goes to the built-in agent first, so anything it already understands works exactly as before.
2. If the built-in agent gives up, Fuzzy Assist parses the sentence itself:
   - number words → digits ("a hundred", "seventy-five", "half", "full", "max")
   - actions: on / off / set brightness / brighter / dimmer ("a bit", "a lot")
   - fuzzy name matching against exposed lights, switches, fans and their areas
     (misheard words, missing spaces, any word order, aliases)
3. Clear match → calls HA's own intents (`HassTurnOn`, `HassTurnOff`, `HassLightSet`). Several equally good matches → replies "Which one? …" and does nothing.
4. No match → the built-in agent's original error is returned.

No LLM and no cloud. Matching uses only `difflib`.

## Install

HACS → three-dot menu → Custom repositories → add `https://github.com/fyrkant/fuzzy_conversation` as an *Integration*, download **Fuzzy Assist**, restart HA. Then:

1. Settings → Devices & services → Add integration → **Fuzzy Assist**
2. Settings → Voice assistants → your pipeline → set the conversation agent to Fuzzy Assist

The integration domain is `fuzzy_assist` (files live in `custom_components/fuzzy_assist`).

## Files

- `custom_components/fuzzy_assist/matcher.py`: parsing and matching in pure Python (no HA imports)
- `custom_components/fuzzy_assist/conversation.py`: the conversation entity
- `tests/`: unit tests for the matcher plus end-to-end tests in a real HA test instance

## Tuning (Settings → Devices & services → Fuzzy Assist → Configure)

- **Name match threshold** (default 75): raise it if it guesses wrong, lower it if it misses names
- **Brighter/dimmer step** (default 20 %)
- **Agent to try first** (default: Home Assistant)

## Run the tests

Needs Python 3.14.

```
pip install -r requirements_test.txt
pytest
```
