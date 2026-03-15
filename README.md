# TTSQwen

Two-machine TTS pipeline: Mac CLI client sends text to a Windows GPU server running Qwen3-TTS, receives WAV audio back.

## Architecture

```
Mac (client)                          Windows RTX 5090 (server)
┌─────────────┐    HTTP POST /speak   ┌──────────────────────────────┐
│  CLI client  │ ──────────────────► │  FastAPI server (:9800)       │
│  or curl     │ ◄────────────────── │  ├─ Qwen3-1.7B summarizer    │
│  (afplay)    │    WAV response      │  ├─ TTS 1.7B-CustomVoice     │
└─────────────┘                       │  └─ TTS 1.7B-Base (cloning)  │
                                      └──────────────────────────────┘
```

## API

### `POST /speak`

Single endpoint for all TTS. Returns `audio/wav`.

**Request body:**

| Field       | Type    | Default   | Description                                              |
|-------------|---------|-----------|----------------------------------------------------------|
| `text`      | string  | required  | Text to synthesize                                       |
| `summarize` | bool    | `true`    | Summarize text before synthesis (via Qwen3-1.7B)         |
| `speaker`   | string  | `"Aiden"` | Preset voice: Aiden, Ryan, Vivian, Serena, Dylan, Eric, Uncle_Fu, Ono_Anna, Sohee |
| `language`  | string  | `"English"` | Language: English, Spanish, Chinese, Japanese, Korean, German, French, Russian, Portuguese, Italian |
| `instruct`  | string  | `""`      | Style instruction (e.g. `"Calm, relaxed delivery"`)      |
| `speed`     | float   | `1.0`     | Tempo multiplier via rubberband (e.g. `1.5` for 1.5x)   |
| `voice`     | string  | `null`    | Cloned voice name from `server/voices/` (overrides `speaker`) |

**Response headers:**

| Header             | Description                    |
|--------------------|--------------------------------|
| `X-Summarize-Time` | Summarization time in seconds  |
| `X-TTS-Time`       | TTS generation time in seconds |
| `X-Spoken-Text`    | URL-encoded spoken text        |

### `GET /health`

Returns `{"status": "ok"}`.

### Examples

```bash
# Default (Aiden, English, summarize on)
curl -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world"}' -o out.wav

# Direct TTS, no summarization
curl -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world", "summarize": false}' -o out.wav

# Specific speaker + speed
curl -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world", "speaker": "Ryan", "speed": 1.5}' -o out.wav

# Voice clone (Spanish, Dolina voice)
curl -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hola mundo", "voice": "dolina", "language": "Spanish", "summarize": false}' -o out.wav

# With style instruction
curl -X POST http://10.18.1.2:9800/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello", "instruct": "Fast-paced, clear and energetic delivery"}' -o out.wav
```

## Voice Modes

### Preset speakers (`speaker` field)
Uses the **1.7B-CustomVoice** model. 9 built-in voices with style control via `instruct`.

| Speaker   | Description                          | Native Language |
|-----------|--------------------------------------|-----------------|
| Aiden     | Sunny American male, clear midrange  | English         |
| Ryan      | Dynamic male, strong rhythmic drive  | English         |
| Vivian    | Bright, slightly edgy young female   | Chinese         |
| Serena    | Warm, gentle young female            | Chinese         |
| Dylan     | Youthful Beijing male, clear natural | Chinese         |
| Eric      | Lively Chengdu male, slightly husky  | Chinese         |
| Uncle_Fu  | Seasoned male, low mellow timbre     | Chinese         |
| Ono_Anna  | Playful Japanese female              | Japanese        |
| Sohee     | Warm Korean female                   | Korean          |

### Cloned voices (`voice` field)
Uses the **1.7B-Base** model with in-context learning (ICL). Clone any voice from a reference audio sample.

To add a new voice, place a `.wav` and matching `.txt` (transcript) in `server/voices/`:
```
server/voices/
├── dolina.wav    # 10-30s reference audio
└── dolina.txt    # Transcript of the audio (UTF-8)
```

Then use `"voice": "dolina"` in requests.

## Speed Recommendations

Post-processing speed uses ffmpeg's rubberband filter (pitch-preserving).

| Speed | Use Case                    |
|-------|-----------------------------|
| 1.0x  | Default, relaxed listening  |
| 1.5x  | Background listening        |
| 1.75x | Focused listening           |
| 2.0x  | Max for trained listeners   |

Male voices (Aiden, Ryan) retain clarity better at higher speeds than female voices.

## Models

| Model | Size | Purpose | VRAM |
|-------|------|---------|------|
| Qwen3-1.7B | ~3.4GB | Text summarization | ~4GB |
| Qwen3-TTS-12Hz-1.7B-CustomVoice | ~4.5GB | Preset speaker TTS | ~5GB |
| Qwen3-TTS-12Hz-1.7B-Base | ~4.5GB | Voice cloning TTS | ~5GB |

Total VRAM: ~14GB (fits on RTX 5090 32GB).

TTS uses [faster-qwen3-tts](https://github.com/andimarafioti/faster-qwen3-tts) with CUDA graph capture and SDPA attention for ~3.7x real-time generation.

## Server Setup (Windows)

```bash
cd server
pip install -r requirements.txt
python server.py
```

Requires ffmpeg with librubberband for speed control. Install via [gyan.dev essentials build](https://www.gyan.dev/ffmpeg/builds/).

### Generate preset voice references (one-time)

```bash
python generate_voice_refs.py
```

Saves reference clips for all 9 preset speakers to `server/voices/`, enabling them to be used via voice cloning on the Base model as well.

## Client Setup (Mac)

```bash
cd client
pip install requests
python client.py --server http://10.18.1.2:9800
```

## Configuration

All settings configurable via environment variables:

| Variable          | Default                                   |
|-------------------|-------------------------------------------|
| `TTS_MODEL`       | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`   |
| `TTS_MODEL_BASE`  | `Qwen/Qwen3-TTS-12Hz-1.7B-Base`          |
| `TTS_VOICE`       | `Aiden`                                   |
| `TTS_LANGUAGE`    | `English`                                 |
| `TTS_INSTRUCT`    | (empty)                                   |
| `TTS_SPEED`       | `1.0`                                     |
| `SUMMARIZER_MODEL`| `Qwen/Qwen3-1.7B`                        |
| `HOST`            | `0.0.0.0`                                 |
| `PORT`            | `9800`                                    |
