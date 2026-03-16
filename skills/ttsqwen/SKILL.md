---
name: ttsqwen
description: Text-to-speech via TTSQwen API. Use when the user wants to generate speech, read text aloud, narrate content, create audio from text, or use TTS. Triggers include "speak this", "read aloud", "generate audio", "TTS", "text to speech", "narrate", "say this out loud".
allowed-tools: Bash(curl:*)
---

# TTSQwen — Text-to-Speech API

TTS server running at `http://10.18.1.2:9800`. Converts text to speech using Qwen3-TTS models on a GPU server.

## Quick Start

```bash
# Generate speech (returns WAV audio)
curl -s -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world"}' -o output.wav

# Health check
curl -s http://10.18.1.2:9800/health
```

## POST /speak

Returns `audio/wav`. All fields except `text` are optional.

| Field       | Type   | Default     | Description                                              |
|-------------|--------|-------------|----------------------------------------------------------|
| `text`      | string | (required)  | Text to synthesize                                       |
| `summarize` | bool   | `true`      | Condense text into 2-8 spoken sentences before synthesis |
| `speaker`   | string | `"Aiden"`   | Preset voice (see below)                                 |
| `language`  | string | `"English"` | English, Spanish, Chinese, Japanese, Korean, German, French, Russian, Portuguese, Italian |
| `instruct`  | string | `""`        | Style instruction (e.g. `"Calm, relaxed delivery"`)      |
| `speed`     | float  | `1.0`       | Tempo multiplier (1.0–2.0 recommended)                   |
| `voice`     | string | `null`      | Cloned voice name (overrides `speaker`)                  |

### Response Headers

| Header             | Value                          |
|--------------------|--------------------------------|
| `X-Summarize-Time` | Summarization time in seconds  |
| `X-TTS-Time`       | TTS generation time in seconds |
| `X-Spoken-Text`    | URL-encoded text that was spoken |

## Preset Speakers

| Speaker    | Style                               | Native Language |
|------------|-------------------------------------|-----------------|
| Aiden      | Sunny American male, clear midrange | English         |
| Ryan       | Dynamic male, strong rhythmic drive | English         |
| Vivian     | Bright, slightly edgy young female  | Chinese         |
| Serena     | Warm, gentle young female           | Chinese         |
| Dylan      | Youthful Beijing male, clear natural| Chinese         |
| Eric       | Lively Chengdu male, slightly husky | Chinese         |
| Uncle_Fu   | Seasoned male, low mellow timbre    | Chinese         |
| Ono_Anna   | Playful Japanese female             | Japanese        |
| Sohee      | Warm Korean female                  | Korean          |

## Presets (Pre-configured Combos)

| Preset                 | Speaker/Voice | Language | Speed | Summarize | Instruct |
|------------------------|---------------|----------|-------|-----------|----------|
| Claude Response        | Aiden         | English  | 1.3x  | Yes       | Fast-paced, clear and direct delivery. Cold, concise tone. |
| DnD Narrator (Dolina)  | dolina (clone)| Spanish  | 1.0x  | No        | — |
| DnD Narrator (Aiden)   | Aiden         | Spanish  | 1.0x  | No        | Deep, slow and dramatic narrator voice. Calm and mysterious tone. |

## Usage Examples

```bash
# Default: Aiden, English, with summarization
curl -s -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Long text that will be summarized first..."}' -o out.wav

# Direct TTS without summarization
curl -s -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Say this exactly as written", "summarize": false}' -o out.wav

# Specific speaker + faster speed
curl -s -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello", "speaker": "Ryan", "speed": 1.5}' -o out.wav

# Voice clone (Spanish)
curl -s -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hola mundo", "voice": "dolina", "language": "Spanish", "summarize": false}' -o out.wav

# With style instruction
curl -s -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Welcome", "instruct": "Whispered, intimate delivery"}' -o out.wav
```

## Guidelines

- **Use `summarize: true`** (default) for long or technical text — it strips code, markdown, and condenses to natural speech
- **Use `summarize: false`** for short text or when exact wording matters
- **Speed 1.0–1.3x** for most use cases; male voices (Aiden, Ryan) handle higher speeds better
- **`instruct`** controls delivery style — keep it short and descriptive
- **`voice`** overrides `speaker` — use it for cloned voices only
- Output is always `audio/wav` (PCM 16-bit, 24kHz)
- To play on Mac: pipe to `afplay` or save to file
