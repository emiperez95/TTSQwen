# TTSQwen

TTS server running on Windows PC (WSL) at `http://10.18.1.2:9800`. Mac is the development machine; Windows is the GPU server.

## SSH Access

```bash
# Connect to Windows PC (SSH host configured as "windows-pc")
ssh windows-pc

# Run commands inside WSL from SSH
ssh windows-pc 'wsl --exec bash -lc "COMMAND"'

# Quoting rules: outer single quotes for SSH, inner double quotes for bash -lc
# WRONG: ssh windows-pc "wsl --exec bash -lc 'cd ~/Projects && ls'"   (breaks on special chars)
# RIGHT: ssh windows-pc 'wsl --exec bash -lc "cd ~/Projects && ls"'
```

## Server Management

```bash
# Service status
ssh windows-pc 'wsl --exec bash -lc "systemctl --user status ttsqwen"'

# Restart after code changes
ssh windows-pc 'wsl --exec bash -lc "cd ~/Projects/TTSQwen && git pull && systemctl --user restart ttsqwen"'

# Health check
curl -s http://10.18.1.2:9800/health

# Model status (loaded/idle times)
curl -s http://10.18.1.2:9800/status | python3 -m json.tool
```

## Debugging

```bash
# Live log stream (follow mode) — see requests, generation times, errors in real-time
ssh windows-pc 'wsl --exec bash -lc "journalctl --user -u ttsqwen -f --no-pager"'

# Last N log lines
ssh windows-pc 'wsl --exec bash -lc "journalctl --user -u ttsqwen --no-pager -n 30"'

# Filter for specific log types
ssh windows-pc 'wsl --exec bash -lc "journalctl --user -u ttsqwen --no-pager -n 100 | grep Summarize"'
ssh windows-pc 'wsl --exec bash -lc "journalctl --user -u ttsqwen --no-pager -n 100 | grep HLS"'
ssh windows-pc 'wsl --exec bash -lc "journalctl --user -u ttsqwen --no-pager -n 100 | grep Stream"'
```

### Log format reference

```
# TTS generation (per sentence)
[TTS] generate=1.97s encode=0.00s speed_adj=0.00s | audio=3.4s 157KB | input=47 chars | voice=clone:aiden

# Summarization (shows input/output for comparison)
[Summarize] 3.49s | 1523→312 chars (80% reduction)
  IN:  <original text up to 500 chars>
  OUT: <summarized text up to 500 chars>

# MP3 streaming chunks
[Stream] chunk 0: wav=165KB → mp3=70KB (encode=0.08s, elapsed=1.87s)
[Stream] TTFB=1.87s, voice=aiden
[Stream] complete: 5 chunks, 191KB total, 4.27s, voice=aiden

# HLS segments
[HLS] session abc123: init segment (753B)
[HLS] session abc123: segment (3.4s, 59KB, elapsed=1.71s)
[HLS] session abc123 complete (3.66s)
[HLS] session abc123 cancelled by client
```

## Deploy Workflow

```bash
# 1. Make changes locally (Mac)
# 2. Commit and push
git add ... && git commit -m "..." && git push
# 3. Pull and restart on server
ssh windows-pc 'wsl --exec bash -lc "cd ~/Projects/TTSQwen && git pull && systemctl --user restart ttsqwen"'
# 4. Wait ~20s for model preloading, then verify
sleep 20 && curl -s http://10.18.1.2:9800/health
```

## Project Structure

- `server/` — FastAPI server (runs on Windows GPU)
- `server/static/` — Web UI (Alpine.js)
- `server/sfx/` — Sound effects for SSML
- `server/voices/` — Reference audio for voice cloning
- `client/` — Mac CLI client
- `skills/ttsqwen/` — Claude Code skill definition

## Key Files

- `server/server.py` — Endpoints: /speak, /speak/stream, /speak/hls
- `server/tts_engine.py` — TTS generation, chained voice cloning, SSML streaming
- `server/hls_manager.py` — HLS session/segment management
- `server/audio_ops.py` — ffmpeg wrappers: WAV→MP3, WAV→fMP4, silence, SFX
- `server/ssml_parser.py` — SSML tag parsing, sentence break injection
- `server/model_manager.py` — Model loading/unloading with idle timeout, pinning
- `server/summarizer.py` — Qwen3 text summarization
- `server/telemetry.py` — OpenTelemetry traces, metrics, logs
- `server/config.py` — All configuration constants
