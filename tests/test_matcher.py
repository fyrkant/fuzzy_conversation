"""Tests for the pure matcher, using the real names from Mattias's HA."""

import importlib.util
from pathlib import Path
import sys

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "fuzzy_matcher",
    Path(__file__).parents[1] / "custom_components" / "fuzzy_assist" / "matcher.py",
)
m = importlib.util.module_from_spec(_SPEC)
sys.modules["fuzzy_matcher"] = m
_SPEC.loader.exec_module(m)


def ent(entity_id, name, *aliases):
    return m.Candidate("entity", entity_id, name, entity_id.split(".")[0], (name, *aliases))


def area(area_id, name, *aliases):
    return m.Candidate("area", area_id, name, None, (name, *aliases))


CANDIDATES = [
    ent("light.living_room_ceiling", "Living Room Ceiling"),
    ent("light.teak", "Teak"),
    ent("light.kitchen_ceiling", "Kitchen Ceiling"),
    ent("light.desk", "Desk"),
    ent("light.entrance_ceiling", "Entrance Ceiling"),
    ent("light.bedroom_ceiling", "Bedroom Ceiling"),
    ent("light.kids_room", "Kids' Room Light"),
    ent("switch.ipad_charger", "iPad Charger"),
    area("living_room", "Living Room"),
    area("kitchen", "Kitchen"),
    area("bedroom", "Bedroom"),
    area("entrance", "Entrance"),
    area("kids_room", "Kids' Room"),
]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Turn living room ceiling light to a hundred percent", "turn living room ceiling light to 100 percent"),
        ("set it to seventy-five %", "set it to 75 percent"),
        ("twenty five percent", "25 percent"),
        ("one hundred", "100"),
        ("the other one", "the other one"),
        ("Kids' room", "kids room"),
    ],
)
def test_normalize(text, expected):
    assert m.normalize(text) == expected


@pytest.mark.parametrize(
    ("text", "action", "value", "target_id"),
    [
        # The sentences that failed with the built-in matcher
        ("Turn living room ceiling light to a hundred percent", m.ACTION_SET, 100, "light.living_room_ceiling"),
        ("Turn living room light to a hundred percent", m.ACTION_SET, 100, "living_room"),
        ("living room ceiling light at sixty percent please", m.ACTION_SET, 60, "light.living_room_ceiling"),
        # Misheard / unusual phrasing
        ("turn on the livingroom seiling lamp", m.ACTION_ON, None, "light.living_room_ceiling"),
        ("set the living rum seiling to half", m.ACTION_SET, 50, "light.living_room_ceiling"),
        ("turn the ceiling light in the living room to full", m.ACTION_SET, 100, "light.living_room_ceiling"),
        ("kitchen ceiling max brightness", m.ACTION_SET, 100, "light.kitchen_ceiling"),
        ("desk lamp off", m.ACTION_OFF, None, "light.desk"),
        ("kill the desk lamp", m.ACTION_OFF, None, "light.desk"),
        ("switch on teak", m.ACTION_ON, None, "light.teak"),
        ("teak light on please", m.ACTION_ON, None, "light.teak"),
        ("lights off in the bedroom", m.ACTION_OFF, None, "bedroom"),
        ("make the kitchen brighter", m.ACTION_UP, 20, "kitchen"),
        ("dim the bedroom ceiling a bit", m.ACTION_DOWN, 10, "light.bedroom_ceiling"),
        ("the entrance a lot darker", m.ACTION_DOWN, 40, "entrance"),
        ("bedroom ceiling to zero", m.ACTION_OFF, None, "light.bedroom_ceiling"),
        ("turn off the ipad charger", m.ACTION_OFF, None, "switch.ipad_charger"),
        ("kids room light at thirty", m.ACTION_SET, 30, "light.kids_room"),
    ],
)
def test_parse_and_resolve(text, action, value, target_id):
    cmd = m.parse(text)
    assert cmd is not None, text
    assert cmd.action == action
    assert cmd.value == value
    match = m.resolve(cmd.target_phrase, CANDIDATES)
    assert match.candidate is not None, (text, cmd, match)
    assert match.candidate.id == target_id


def test_ambiguous_ceiling():
    cmd = m.parse("turn off the ceiling light")
    match = m.resolve(cmd.target_phrase, CANDIDATES)
    assert match.candidate is None
    assert len(match.ambiguous) >= 3


@pytest.mark.parametrize(
    "text",
    ["what time is it", "tell me a joke", "play some music"],
)
def test_not_a_command(text):
    cmd = m.parse(text)
    assert cmd is None or m.resolve(cmd.target_phrase, CANDIDATES).candidate is None


def test_unknown_device_rejected():
    cmd = m.parse("turn on the garage heater")
    assert m.resolve(cmd.target_phrase, CANDIDATES).candidate is None


def test_partial_unique_name():
    cmd = m.parse("turn off the charger")
    match = m.resolve(cmd.target_phrase, CANDIDATES)
    assert match.candidate is not None and match.candidate.id == "switch.ipad_charger"
