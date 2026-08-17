"""Constants and defaults for credential validators."""

# Standard default endpoints and models
DEFAULT_BODS_BASE = "https://data.bus-data.dft.gov.uk/api/v1"
DEFAULT_LDBWS_BASE = (
    "https://api1.raildata.org.uk/1010-live-departure-board-dep1_2/LDBWS"
)
DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "o3-mini",
    "gpt-4-turbo",
    "gpt-3.5-turbo",
]

EXCLUDED_MODEL_PREFIXES = (
    "text-embedding-",
    "whisper-",
    "tts-",
    "dall-e-",
    "text-moderation-",
    "omni-moderation-",
    "davinci-",
    "babbage-",
    "canary-",
)

EXCLUDED_MODEL_SUBSTRINGS = (
    "embedding",
    "moderation",
    "tts",
    "whisper",
    "realtime",
    "audio",
)

PRIORITY_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "o3-mini",
    "o1",
    "o1-mini",
    "o1-preview",
    "gpt-4-turbo",
    "gpt-4",
    "gpt-3.5-turbo",
]
