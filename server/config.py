import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Models
SUMMARIZER_MODEL = os.getenv("SUMMARIZER_MODEL", "Qwen/Qwen3-1.7B")
TTS_MODEL = os.getenv("TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
TTS_MODEL_BASE = os.getenv("TTS_MODEL_BASE", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")

# TTS settings
TTS_VOICE = os.getenv("TTS_VOICE", "aiden")  # Default clone voice (Base model)
TTS_SPEAKER = os.getenv("TTS_SPEAKER", "")  # Preset speaker (CustomVoice model, on-demand)
TTS_LANGUAGE = os.getenv("TTS_LANGUAGE", "English")
TTS_INSTRUCT = os.getenv("TTS_INSTRUCT", "")
TTS_SPEED = float(os.getenv("TTS_SPEED", "1.0"))
TTS_SAMPLE_RATE = 24000

# Model management
MODEL_IDLE_TIMEOUT = int(os.getenv("MODEL_IDLE_TIMEOUT", "120"))  # seconds, 0=never unload

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "9800"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]

# Telemetry
OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://10.18.1.1:4318")

# SFX / SSML
SFX_DIR = Path(__file__).parent / "sfx"

# History
HISTORY_MAX_ENTRIES = 50

# Validation limits
MAX_TEXT_LENGTH = 10_000
MIN_SPEED = 0.5
MAX_SPEED = 3.0
VALID_LANGUAGES = {"English", "Chinese", "Japanese", "Korean", "Spanish",
                   "German", "French", "Russian", "Portuguese", "Italian"}

# Preset speakers metadata (name → {language, description})
PRESET_SPEAKERS = {
    "Aiden": {"language": "English", "description": "Sunny American male, clear midrange"},
    "Ryan": {"language": "English", "description": "Dynamic male, strong rhythmic drive"},
    "Vivian": {"language": "Chinese", "description": "Bright, slightly edgy young female"},
    "Serena": {"language": "Chinese", "description": "Warm, gentle young female"},
    "Dylan": {"language": "Chinese", "description": "Youthful Beijing male, clear natural"},
    "Eric": {"language": "Chinese", "description": "Lively Chengdu male, slightly husky"},
    "Uncle_Fu": {"language": "Chinese", "description": "Seasoned male, low mellow timbre"},
    "Ono_Anna": {"language": "Japanese", "description": "Playful Japanese female"},
    "Sohee": {"language": "Korean", "description": "Warm Korean female"},
}

# Summarizer prompt
SUMMARIZER_SYSTEM_PROMPT = """You are a text-to-speech preprocessor. Convert the input into a concise spoken briefing that covers all key points.

Rules:
- Mention every option, feature, or item discussed — do not skip any
- For each, give a one-sentence verdict with its key tradeoff
- End with the recommendation or conclusion if one exists
- Write in plain spoken sentences — no bullet points, no markdown, no lists
- Separate distinct topics or options with blank lines (paragraph breaks)
- Use natural phrasing with contractions
- Remove code, tables, URLs, and special characters
- Expand abbreviations and numbers into spoken form
- Do not add preamble — just speak the content directly"""
