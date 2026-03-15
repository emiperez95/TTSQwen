"""Generate reference audio clips from CustomVoice preset speakers.

Saves each preset voice as a .wav + .txt pair in server/voices/,
so they can be used with the Base model for voice cloning.

Usage: python generate_voice_refs.py
"""

import soundfile as sf
import torch
from faster_qwen3_tts import FasterQwen3TTS
from pathlib import Path

from config import TTS_MODEL

VOICES_DIR = Path(__file__).parent / "voices"

# Reference text each speaker will say (used as ref_text for cloning)
REFS = {
    "Aiden": ("English", "The ancient forest stretched endlessly before them, its towering trees whispering secrets of a forgotten age. Somewhere in the distance, a river sang its eternal song."),
    "Ryan": ("English", "The ancient forest stretched endlessly before them, its towering trees whispering secrets of a forgotten age. Somewhere in the distance, a river sang its eternal song."),
    "Vivian": ("Chinese", "古老的森林在他们面前无尽延伸，高耸的树木低语着被遗忘时代的秘密。远处，一条河流唱着它永恒的歌。"),
    "Serena": ("Chinese", "古老的森林在他们面前无尽延伸，高耸的树木低语着被遗忘时代的秘密。远处，一条河流唱着它永恒的歌。"),
    "Dylan": ("Chinese", "古老的森林在他们面前无尽延伸，高耸的树木低语着被遗忘时代的秘密。远处，一条河流唱着它永恒的歌。"),
    "Eric": ("Chinese", "古老的森林在他们面前无尽延伸，高耸的树木低语着被遗忘时代的秘密。远处，一条河流唱着它永恒的歌。"),
    "Uncle_Fu": ("Chinese", "古老的森林在他们面前无尽延伸，高耸的树木低语着被遗忘时代的秘密。远处，一条河流唱着它永恒的歌。"),
    "Ono_Anna": ("Japanese", "古代の森が彼らの前に果てしなく広がり、そびえ立つ木々が忘れられた時代の秘密をささやいていた。"),
    "Sohee": ("Korean", "고대의 숲이 그들 앞에 끝없이 펼쳐져 있었고, 우뚝 솟은 나무들이 잊혀진 시대의 비밀을 속삭이고 있었다."),
}


def main():
    VOICES_DIR.mkdir(exist_ok=True)

    print(f"Loading model: {TTS_MODEL}")
    model = FasterQwen3TTS.from_pretrained(
        TTS_MODEL,
        device="cuda",
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )

    for speaker, (language, text) in REFS.items():
        out_wav = VOICES_DIR / f"{speaker.lower()}.wav"
        out_txt = VOICES_DIR / f"{speaker.lower()}.txt"

        if out_wav.exists():
            print(f"Skipping {speaker} (already exists)")
            continue

        print(f"Generating {speaker}...")
        wavs, sr = model.generate_custom_voice(
            text=text,
            language=language,
            speaker=speaker,
        )

        audio = wavs[0]
        if isinstance(audio, torch.Tensor):
            audio = audio.cpu().numpy()

        sf.write(str(out_wav), audio, sr)
        out_txt.write_text(text)
        print(f"  Saved {out_wav} ({len(audio)/sr:.1f}s)")

    print("Done! Voice references saved to", VOICES_DIR)


if __name__ == "__main__":
    main()
