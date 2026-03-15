import os

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

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "9800"))

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
