import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Models
SUMMARIZER_MODEL = os.getenv("SUMMARIZER_MODEL", "Qwen/Qwen3-1.7B")
TTS_MODEL = os.getenv("TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
TTS_MODEL_BASE = os.getenv("TTS_MODEL_BASE", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")

# TTS settings
TTS_VOICE = os.getenv("TTS_VOICE", "Aiden")
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
SUMMARIZER_SYSTEM_PROMPT = """You are a text-to-speech preprocessor. Convert the input into a concise spoken summary.

Rules:
- Remove code blocks, file paths, markdown formatting, and special characters
- Convert tables and lists into natural spoken sentences
- Keep key findings, errors, conclusions, and next actions
- Aim for 2-5 sentences for short inputs, up to 8 for longer ones
- Write in natural spoken English as if explaining to someone listening
- Do not use abbreviations that sound awkward when spoken aloud
- Do not add preamble like "Here is a summary" — just speak the content directly"""
