---
name: ttsqwen
description: Text-to-speech via TTSQwen API. Use when the user wants to generate speech, read text aloud, narrate content, create audio from text, or use TTS. Triggers include "speak this", "read aloud", "generate audio", "TTS", "text to speech", "narrate", "say this out loud".
allowed-tools: Bash(curl:*)
---

# TTSQwen — Text-to-Speech API

TTS server running at `http://10.18.1.2:9800`. Converts text to speech using Qwen3-TTS models on a GPU server.

For the latest API docs, presets, and voices, check `GET /help`:
```bash
curl -s http://10.18.1.2:9800/help
```

## Quick Start

```bash
# Simplest: use a preset (only text required)
curl -s -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world", "preset": "Claude Response"}' -o output.wav

# Health check
curl -s http://10.18.1.2:9800/health
```

## POST /speak

Returns `audio/wav`. When using a preset, only `text` is required.

| Field       | Type   | Default     | Description                                              |
|-------------|--------|-------------|----------------------------------------------------------|
| `text`      | string | (required)  | Text to synthesize (max 10000 chars)                     |
| `preset`    | string | `null`      | Named preset — fills in all other fields automatically   |
| `summarize` | bool   | `true`      | Condense text into spoken summary before synthesis       |
| `speaker`   | string | `"Aiden"`   | Preset voice (see below)                                 |
| `voice`     | string | `null`      | Cloned voice name (overrides `speaker`)                  |
| `language`  | string | `"English"` | English, Spanish, Chinese, Japanese, Korean, German, French, Russian, Portuguese, Italian |
| `instruct`  | string | `""`        | Style instruction (e.g. `"Calm, relaxed delivery"`) — preset speakers only |
| `speed`     | float  | `1.0`       | Tempo multiplier (0.5–3.0, default 1.0)                 |

When using a preset, explicit fields override preset defaults.

### Response Headers

| Header             | Value                          |
|--------------------|--------------------------------|
| `X-Summarize-Time` | Summarization time in seconds  |
| `X-TTS-Time`       | TTS generation time in seconds |
| `X-Spoken-Text`    | URL-encoded text that was spoken |

## Presets

Use presets for the simplest API calls. Just `text` + `preset` name.

| Preset                 | Voice              | Language | Speed | Summarize |
|------------------------|--------------------|----------|-------|-----------|
| Claude Response        | Aiden (preset)     | English  | 1.3x  | Yes       |
| Alfred                 | michael_caine (clone) | English | 1.0x | No        |
| Jarvis                 | Aiden (preset)     | English  | 1.1x  | No        |
| Asistente IA           | rioplatense (clone)| Spanish  | 1.0x  | No        |
| DnD Narrator (Dolina)  | dolina (clone)     | Spanish  | 1.0x  | No        |
| DnD Narrator (Aiden)   | Aiden (preset)     | Spanish  | 1.0x  | No        |

## Preset Speakers

9 built-in voices with style control via `instruct`.

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

## Cloned Voices

Use via the `voice` field. `instruct` is NOT supported for cloned voices.

| Voice          | Description                              |
|----------------|------------------------------------------|
| michael_caine  | Michael Caine — warm British male        |
| rioplatense    | Rioplatense Spanish male                 |
| dolina         | Dolina — Argentine narrator              |
| espanol_neutro | Neutral Latin American Spanish male      |
| jeremy_irons   | Jeremy Irons — distinguished British male|

## SSML-like Markup

Text can include tags for sound effects, pauses, and background ambient audio. When any tag is detected, summarization is automatically skipped.

### Tags (self-closing)

| Tag | Description |
|-----|-------------|
| `<audio src="name"/>` | Insert a sound effect from `server/sfx/` |
| `<break time="500ms"/>` | Insert silence (`ms` or `s` units, max 10s) |
| `<bg src="name" vol="0.15"/>` | Mix looped background audio underneath entire output |

### Available SFX

Check what sound effects are available:
```bash
curl -s http://10.18.1.2:9800/api/sfx
```

### SSML Examples

```bash
# Pauses between sentences
curl -s -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "The door creaks open. <break time=\"1.5s\"/> A cold wind rushes in.", "preset": "DnD Narrator (Aiden)"}' -o out.wav

# Sound effect + background ambient
curl -s -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "The old man coughs. <audio src=\"cough\"/> <break time=\"800ms\"/> The treasure lies beneath the mountain. <bg src=\"tavern\" vol=\"0.12\"/>", "preset": "DnD Narrator (Dolina)"}' -o out.wav
```

Plain text (no tags) works exactly as before — fully backward compatible.

## Usage Examples

```bash
# Using a preset (simplest — recommended)
curl -s -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world", "preset": "Alfred"}' -o out.wav

# Spanish AI assistant
curl -s -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Buenos días, el sistema está listo.", "preset": "Asistente IA"}' -o out.wav

# Manual: specific speaker + speed
curl -s -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello", "speaker": "Ryan", "speed": 1.5, "summarize": false}' -o out.wav

# Manual: voice clone
curl -s -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hola mundo", "voice": "rioplatense", "language": "Spanish", "summarize": false}' -o out.wav
```

## Guidelines

- **Use presets** whenever possible — simplest API, just text + preset name
- **Use `summarize: true`** (default) for long/technical text
- **Use `summarize: false`** for short text or exact wording
- **`instruct`** only works with preset speakers, NOT cloned voices
- **Speed 1.0–1.3x** for most use cases; male voices handle higher speeds better
- **SSML tags** (`<audio>`, `<break>`, `<bg>`) enable sound effects, pauses, and ambient audio — great for DnD narration
- **Check available SFX** with `GET /api/sfx` before using `<audio>` or `<bg>` tags
- Output is always `audio/wav` (PCM 16-bit, 24kHz)
- To play on Mac: pipe to `afplay` or save to file
- For latest info: `curl http://10.18.1.2:9800/help`
