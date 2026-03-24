#!/usr/bin/env python3
"""Interactive CLI client for TTSQwen server."""

import argparse
import io
import shutil
import sys
import tempfile
import subprocess

import requests


def play_wav(wav_bytes: bytes):
    """Play WAV audio using afplay (macOS)."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as f:
        f.write(wav_bytes)
        f.flush()
        subprocess.run(["afplay", f.name], check=True)


def send_text(server: str, text: str, summarize: bool) -> None:
    """Send text to server and play the response (buffered)."""
    endpoint = f"{server}/speak"
    payload = {"text": text, "summarize": summarize}

    try:
        resp = requests.post(endpoint, json=payload, timeout=120)
        resp.raise_for_status()
    except requests.ConnectionError:
        print(f"Error: cannot connect to {server}")
        return
    except requests.HTTPError as e:
        print(f"Error: {e}")
        return

    t_sum = resp.headers.get("X-Summarize-Time", "0")
    t_tts = resp.headers.get("X-TTS-Time", "0")
    spoken = resp.headers.get("X-Spoken-Text", "")
    if spoken:
        print(f"  Spoken: {spoken}")
    print(f"  Summarize: {t_sum}s | TTS: {t_tts}s | Size: {len(resp.content)} bytes")

    play_wav(resp.content)


def send_text_stream(server: str, text: str, summarize: bool) -> None:
    """Send text to server and play streamed MP3 response."""
    endpoint = f"{server}/speak/stream"
    payload = {"text": text, "summarize": summarize}

    try:
        resp = requests.post(endpoint, json=payload, stream=True, timeout=120)
        resp.raise_for_status()
    except requests.ConnectionError:
        print(f"Error: cannot connect to {server}")
        return
    except requests.HTTPError as e:
        print(f"Error: {e}")
        return

    t_sum = resp.headers.get("X-Summarize-Time", "0")
    spoken = resp.headers.get("X-Spoken-Text", "")
    if spoken:
        print(f"  Spoken: {spoken}")
    print(f"  Summarize: {t_sum}s | Streaming...")

    if shutil.which("ffplay"):
        # Stream directly to ffplay for real-time playback
        proc = subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-i", "pipe:0"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for chunk in resp.iter_content(chunk_size=4096):
                proc.stdin.write(chunk)
            proc.stdin.close()
            proc.wait()
        except BrokenPipeError:
            pass
    else:
        # Fallback: buffer to temp file and play with afplay
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as f:
            for chunk in resp.iter_content(chunk_size=4096):
                f.write(chunk)
            f.flush()
            subprocess.run(["afplay", f.name], check=True)


def main():
    parser = argparse.ArgumentParser(description="TTSQwen CLI client")
    parser.add_argument(
        "--server",
        default="http://localhost:9800",
        help="Server URL (default: http://localhost:9800)",
    )
    parser.add_argument(
        "--no-summarize",
        action="store_true",
        help="Send text directly to TTS without summarization",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream audio (plays as it generates, requires ffplay for real-time)",
    )
    args = parser.parse_args()

    summarize = not args.no_summarize
    mode = "summarize + TTS" if summarize else "TTS only"
    stream_label = " [streaming]" if args.stream else ""
    print(f"TTSQwen client — {args.server} — mode: {mode}{stream_label}")
    if args.stream and not shutil.which("ffplay"):
        print("  Warning: ffplay not found, streaming will buffer to file before playing")
    print("Type text and press Enter. Ctrl+C to quit.\n")

    try:
        while True:
            try:
                text = input("> ").strip()
            except EOFError:
                break

            if not text:
                continue

            if args.stream:
                send_text_stream(args.server, text, summarize)
            else:
                send_text(args.server, text, summarize)
            print()
    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == "__main__":
    main()
