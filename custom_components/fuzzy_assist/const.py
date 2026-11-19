"""Constants for Fuzzy Assist."""

DOMAIN = "fuzzy_assist"

CONF_THRESHOLD = "threshold"
CONF_STEP = "step"
CONF_FALLBACK_AGENT = "fallback_agent"

DEFAULT_THRESHOLD = 75  # percent, minimum name match score
DEFAULT_STEP = 20  # percent, for "brighter" / "dimmer"
DEFAULT_FALLBACK_AGENT = "conversation.home_assistant"

# Domains the fuzzy layer can switch on/off. Brightness is lights only.
SUPPORTED_DOMAINS = ("light", "switch", "fan")
