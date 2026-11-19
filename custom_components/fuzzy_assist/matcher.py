"""Fuzzy command parsing and target resolution for Fuzzy Assist.

Pure Python on purpose: no Home Assistant imports, so it can be unit tested
on its own. The conversation entity feeds it the exposed devices and areas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re

# --- actions ---------------------------------------------------------------

ACTION_ON = "on"
ACTION_OFF = "off"
ACTION_SET = "set"  # absolute brightness
ACTION_UP = "up"  # relative brightness
ACTION_DOWN = "down"

# --- vocabulary --------------------------------------------------------------

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
# Words that mean a fixed brightness on their own.
_LEVEL_WORDS = {
    "full": 100, "fully": 100, "max": 100, "maximum": 100, "brightest": 100,
    "half": 50, "halfway": 50,
    "min": 1, "minimum": 1, "lowest": 1, "dimmest": 1,
}

_OFF_PHRASES = ("turn off", "switch off", "shut off", "shut down", "lights out",
                "power off", "kill")
_ON_PHRASES = ("turn on", "switch on", "power on", "light up")
_UP_PHRASES = ("brighter", "brighten", "turn up", "more light", "increase",
               "raise", "lighter")
_DOWN_PHRASES = ("dimmer", "dim", "darker", "turn down", "less light",
                 "decrease", "lower")
_SMALL_STEP = ("a bit", "a little", "slightly", "a touch", "bit")
_BIG_STEP = ("a lot", "much", "way")

# Dropped before matching the target name. Domain words ("light", "lamp")
# are dropped from candidate names too, so "desk lamp" still finds "Desk".
_STOPWORDS = {
    "a", "an", "the", "to", "at", "in", "into", "of", "on", "off", "for", "my",
    "our", "please", "can", "could", "would", "will", "you", "hey", "hi", "ok",
    "okay", "uh", "um", "now", "just", "and", "set", "make", "put", "turn",
    "switch", "shut", "power", "kill", "get", "it", "its", "is", "be", "all",
    "up", "down", "bit", "little", "slightly", "touch", "lot", "much", "way",
    "more", "less", "light", "lights", "lamp", "lamps", "bulb", "bulbs",
    "brightness", "bright", "percent", "pct", "level", "room's",
    "brighter", "brighten", "dimmer", "dim", "darker", "lighter", "increase",
    "decrease", "raise", "lower", "out", "level", "value", "with", "by",
    "there", "here", "some", "me", "so", "too",
} | set(_LEVEL_WORDS) | set(_UNITS) | set(_TENS) | {"hundred"}

_PUNCT = re.compile(r"[^\w\s%]")
_SPACES = re.compile(r"\s+")


# --- data classes ------------------------------------------------------------


@dataclass(frozen=True)
class Command:
    """What the user asked for, before we know which device they meant."""

    action: str
    target_phrase: str
    value: int | None = None  # brightness % for ACTION_SET, step for UP/DOWN


@dataclass(frozen=True)
class Candidate:
    """Something the user could be talking about."""

    kind: str  # "entity" or "area"
    id: str  # entity_id or area_id
    name: str  # the name HA knows it by (passed to the intent)
    domain: str | None = None  # entity domain, None for areas
    spoken_names: tuple[str, ...] = field(default_factory=tuple)  # name + aliases


@dataclass(frozen=True)
class Match:
    """Result of resolving a target phrase."""

    candidate: Candidate | None
    score: float
    ambiguous: tuple[Candidate, ...] = ()


# --- normalisation -----------------------------------------------------------


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, turn number words into digits."""
    text = text.lower().replace("’", "'")
    text = text.replace("per cent", "percent").replace("%", " percent ")
    text = text.replace("-", " ")
    text = text.replace("'", "")  # kids' -> kids, room's -> rooms
    text = _PUNCT.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    return _words_to_numbers(text)


def _words_to_numbers(text: str) -> str:
    """Replace spelled-out numbers 0-100 with digits.

    Handles "a hundred", "one hundred", "hundred", "seventy five",
    "twenty-five" (hyphen already removed) and plain units.
    """
    tokens = text.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        # "a hundred" / "one hundred" / "hundred"
        if tok in ("a", "one") and nxt == "hundred":
            out.append("100")
            i += 2
            continue
        if tok == "hundred":
            out.append("100")
            i += 1
            continue
        if tok in _TENS:
            value = _TENS[tok]
            if nxt in _UNITS and 0 < _UNITS[nxt] < 10:
                value += _UNITS[nxt]
                i += 1
            out.append(str(value))
            i += 1
            continue
        if tok in _UNITS and tok != "one":
            out.append(str(_UNITS[tok]))
            i += 1
            continue
        # "one" is too often a pronoun ("the other one"); only convert it
        # when it is clearly a number.
        if tok == "one" and nxt == "percent":
            out.append("1")
            i += 1
            continue
        out.append(tok)
        i += 1
    return " ".join(out)


def _has_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    padded = f" {text} "
    return any(f" {p} " in padded for p in phrases)


def _tokens(text: str) -> list[str]:
    return [t for t in text.split() if t not in _STOPWORDS and not t.isdigit()]


def name_tokens(name: str) -> list[str]:
    """Tokens of a device/area name, normalised the same way as speech."""
    return _tokens(normalize(name))


# --- parsing -----------------------------------------------------------------


def parse(text: str, step: int = 20) -> Command | None:
    """Work out the action and the words that name the target."""
    norm = normalize(text)
    if not norm:
        return None
    words = norm.split()

    number = _find_level(words)
    is_off = _has_phrase(norm, _OFF_PHRASES) or (
        "off" in words and number is None
    )
    is_on = _has_phrase(norm, _ON_PHRASES) or "on" in words
    is_up = _has_phrase(norm, _UP_PHRASES)
    is_down = _has_phrase(norm, _DOWN_PHRASES)

    target = " ".join(_tokens(norm))

    if number is not None and not is_off:
        if number <= 0:
            return Command(ACTION_OFF, target)
        return Command(ACTION_SET, target, min(number, 100))
    if is_up or is_down:
        size = step
        if _has_phrase(norm, _SMALL_STEP):
            size = max(step // 2, 5)
        elif _has_phrase(norm, _BIG_STEP):
            size = min(step * 2, 100)
        return Command(ACTION_UP if is_up else ACTION_DOWN, target, size)
    if is_off:
        return Command(ACTION_OFF, target)
    if is_on:
        return Command(ACTION_ON, target)
    return None


def _find_level(words: list[str]) -> int | None:
    """Brightness level in the sentence, if any."""
    for i, word in enumerate(words):
        if word.isdigit():
            return int(word)
        if word in _LEVEL_WORDS:
            # "full" in "fully off" is not a level; "half" usually is.
            nxt = words[i + 1] if i + 1 < len(words) else ""
            if nxt in ("off", "on") and word in ("full", "fully"):
                continue
            return _LEVEL_WORDS[word]
    return None


# --- resolution --------------------------------------------------------------


_TOKEN_FLOOR = 0.65  # below this two words count as unrelated


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _token_sim(a: str, b: str) -> float:
    """Similarity of two words, with no partial credit for unrelated words.

    Without the floor, "kitchen" vs "ceiling" (0.29) would nudge one ceiling
    light ahead of the others and we'd guess instead of asking.
    """
    r = _ratio(a, b)
    return r if r >= _TOKEN_FLOOR else 0.0


def similarity(phrase: list[str], name: list[str]) -> tuple[float, float]:
    """How well spoken tokens match a name's tokens.

    Returns (score, coverage): score 0..1 for the whole name, coverage 0..1
    for how much of what was said is found in the name. Word order doesn't
    matter ("ceiling in the living room"), words can be misheard ("seiling")
    and spaces can go missing ("livingroom").
    """
    if not phrase or not name:
        return 0.0, 0.0
    name_cov = sum(max(_token_sim(n, p) for p in phrase) for n in name) / len(name)
    phrase_cov = sum(max(_token_sim(p, n) for n in name) for p in phrase) / len(phrase)
    token_score = 0.6 * name_cov + 0.4 * phrase_cov
    glued = _ratio("".join(phrase), "".join(name))
    sorted_glued = _ratio("".join(sorted(phrase)), "".join(sorted(name)))
    return max(token_score, glued, sorted_glued), phrase_cov


def resolve(
    phrase: str,
    candidates: list[Candidate],
    threshold: float = 0.75,
    tie_margin: float = 0.03,
    partial_coverage: float = 0.85,
) -> Match:
    """Pick the device or area the phrase most likely refers to.

    1. A clear best match above the threshold wins.
    2. Otherwise, if what was said is part of exactly one name ("charger"
       -> "iPad Charger") that one wins; if it's part of several
       ("ceiling") the result is ambiguous so the reply can ask which.
    """
    spoken = phrase.split()
    if not spoken:
        return Match(None, 0.0)

    scored: list[tuple[float, float, Candidate]] = []
    for cand in candidates:
        best, cov = 0.0, 0.0
        for spoken_name in cand.spoken_names or (cand.name,):
            s, c = similarity(spoken, name_tokens(spoken_name))
            best, cov = max(best, s), max(cov, c)
        scored.append((best, cov, cand))
    if not scored:
        return Match(None, 0.0)

    # Highest score first; on a tie prefer a specific device over an area.
    scored.sort(key=lambda sc: (sc[0], sc[2].kind == "entity"), reverse=True)
    top_score, _, top = scored[0]

    if top_score >= threshold:
        close = [
            c for s, _, c in scored[1:]
            if top_score - s <= tie_margin and c.kind == top.kind and c.id != top.id
        ]
        if not close or top_score >= 0.999:
            return Match(top, top_score)
        nearby = tuple(
            c for s, _, c in scored[1:]
            if top_score - s <= 0.1 and c.kind == top.kind and c.id != top.id
        )
        return Match(None, top_score, ambiguous=(top, *nearby))

    partial = [(s, c) for s, cov, c in scored if cov >= partial_coverage]
    if len(partial) == 1:
        s, c = partial[0]
        return Match(c, s)
    if len(partial) > 1:
        return Match(None, top_score, ambiguous=tuple(c for _, c in partial[:6]))
    return Match(None, top_score)
