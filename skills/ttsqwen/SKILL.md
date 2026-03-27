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
| `voice`     | string | `"aiden"`   | Voice name (see cloned voices below)                     |
| `speaker`   | string | `null`      | Preset speaker — loads CustomVoice model on demand, supports `instruct` |
| `language`  | string | `"English"` | English, Spanish, Chinese, Japanese, Korean, German, French, Russian, Portuguese, Italian |
| `instruct`  | string | `""`        | Style instruction (e.g. `"Calm, relaxed delivery"`) — `speaker` only, not `voice` |
| `speed`     | float  | `1.0`       | Tempo multiplier (0.5–3.0, default 1.0)                 |
| `summarize_prompt` | string | `null` | Custom system prompt for the summarizer (overrides default) |

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
| Claude Response        | aiden (clone)      | English  | 1.3x  | Yes       |
| DnD Narrator           | dnd_narrator (clone)| Spanish | 1.0x  | No        |

## Preset Speakers (on-demand)

9 built-in voices via `speaker` field. Loads the CustomVoice model on demand (slower first call). Supports `instruct` for style control.

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

## Voices

Use via the `voice` field (default: `aiden`). These run on the Base model which stays loaded.

| Voice          | Description                              |
|----------------|------------------------------------------|
| aiden          | Sunny American male, clear midrange (default) |
| ryan           | Dynamic male, strong rhythmic drive      |
| dnd_narrator   | DnD narrator — Spanish fantasy storyteller|
| michael_caine  | Michael Caine — warm British male        |
| rioplatense    | Rioplatense Spanish male                 |
| dolina         | Dolina — Argentine narrator              |
| espanol_neutro | Neutral Latin American Spanish male      |
| jeremy_irons   | Jeremy Irons — distinguished British male|
| vivian         | Bright, slightly edgy young female (Chinese) |
| serena         | Warm, gentle young female (Chinese)      |
| dylan          | Youthful Beijing male (Chinese)          |
| eric           | Lively Chengdu male, slightly husky (Chinese) |
| uncle_fu       | Seasoned male, low mellow timbre (Chinese) |
| ono_anna       | Playful Japanese female                  |
| sohee          | Warm Korean female                       |

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
  -d '{"text": "The door creaks open. <break time=\"1.5s\"/> A cold wind rushes in.", "preset": "DnD Narrator"}' -o out.wav

# Sound effect + background ambient
curl -s -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "The old man coughs. <audio src=\"cough\"/> <break time=\"800ms\"/> The treasure lies beneath the mountain. <bg src=\"tavern\" vol=\"0.12\"/>", "preset": "DnD Narrator"}' -o out.wav
```

Plain text (no tags) works exactly as before — fully backward compatible.

## POST /speak/stream

Same request body as `/speak`, but returns **chunked `audio/mpeg`** (MP3). Audio starts playing within ~2s while the rest is still being generated — much lower perceived latency for multi-sentence text.

| Difference from `/speak` | Details |
|--------------------------|---------|
| Response format          | `audio/mpeg` (MP3) instead of `audio/wav` |
| Delivery                 | Chunked transfer — streams as it generates |
| Background audio (`<bg>`)| Falls back to buffered MP3 (mixing needs full audio) |
| `X-TTS-Time` header      | Not available (total time unknown when headers are sent) |

**When to use `/speak/stream` vs `/speak`:**
- Use `/speak/stream` for longer text (2+ sentences) — client hears audio sooner
- Use `/speak` for short text or when you need the complete WAV file
- Use `/speak` when you need `X-TTS-Time` header or WAV format

```bash
# Stream to file
curl -s -X POST http://10.18.1.2:9800/speak/stream \
  -H "Content-Type: application/json" \
  -d '{"text": "Long text here...", "preset": "Claude Response"}' -o out.mp3

# Stream directly to ffplay for real-time playback (best experience)
curl -s -N -X POST http://10.18.1.2:9800/speak/stream \
  -H "Content-Type: application/json" \
  -d '{"text": "Long text here...", "preset": "Claude Response"}' | ffplay -nodisp -autoexit -i pipe:0
```

## POST /speak/hls

Same request body as `/speak`, but returns a **JSON response with an HLS playlist URL** for browser streaming. Audio is encoded as fMP4 (AAC 44100Hz stereo) segments. iOS Safari plays natively; other browsers use HLS.js.

**Response:**
```json
{"session_id": "abc123", "playlist_url": "/hls/abc123/playlist.m3u8", "summarize_time": 3.5, "spoken_text": "..."}
```

**HLS routes:**
| Route | Description |
|-------|-------------|
| `GET /hls/{session_id}/playlist.m3u8` | EVENT playlist — poll to discover new segments |
| `GET /hls/{session_id}/init.m4s` | fMP4 init segment (codec info) |
| `GET /hls/{session_id}/{index}.m4s` | fMP4 audio segments |
| `DELETE /hls/{session_id}` | Abort generation and clean up (call on user navigate-away) |

Sessions expire after 5 minutes automatically.

```bash
# Create HLS session
curl -s -X POST http://10.18.1.2:9800/speak/hls \
  -H "Content-Type: application/json" \
  -d '{"text": "Long text here...", "preset": "Claude Response"}'

# Cancel generation
curl -s -X DELETE http://10.18.1.2:9800/hls/{session_id}
```

**When to use `/speak/hls`:**
- Use for browser playback — especially iOS Safari (native HLS support)
- Use when building web UIs that need streaming audio
- Use `/speak/stream` instead for CLI/non-browser clients

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
- **Use `voice`** (not `speaker`) for fast responses — Base model stays loaded
- **Use `speaker`** only if you need `instruct` style control — loads CustomVoice on demand
- **Use `summarize: true`** (default) for long/technical text
- **Use `summarize: false`** for short text or exact wording
- **Speed 1.0–1.3x** for most use cases; male voices handle higher speeds better
- **SSML tags** (`<audio>`, `<break>`, `<bg>`) enable sound effects, pauses, and ambient audio — great for DnD narration
- **Check available SFX** with `GET /api/sfx` before using `<audio>` or `<bg>` tags
- **Use `/speak/stream`** for longer text in CLI — starts playing in ~2s instead of waiting for full generation
- **Use `/speak/hls`** for browser playback — iOS Safari native, others via HLS.js
- **Call `DELETE /hls/{session_id}`** when user navigates away to stop generation and free GPU
- Output: `audio/wav` from `/speak`, `audio/mpeg` from `/speak/stream`, fMP4 HLS from `/speak/hls`
- To play WAV on Mac: pipe to `afplay` or save to file
- To play streaming MP3: pipe curl output to `ffplay -nodisp -autoexit -i pipe:0`
- For latest info: `curl http://10.18.1.2:9800/help`
