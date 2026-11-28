"""Render one sentence in every female English Kokoro voice so you can pick Momo's voice.

    .venv\\Scripts\\python scripts\\voice_samples.py      # -> data/voice_samples/voice_<name>.wav

Then set it in .env:   MOMO_VOICE=af_bella      or a blend:   MOMO_VOICE=af_heart:60,af_bella:40
"""
import os
import sys

import soundfile as sf

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from tts import speak  # noqa: E402

TEXT = "Of course, Master. Your timer is set, and I'll let you know the moment it's done."
OUT = os.path.join(ROOT, "data", "voice_samples")

os.makedirs(OUT, exist_ok=True)
tts = speak._load()
for v in [v for v in tts.get_voices() if v[:2] in ("af", "bf")]:
    wav, sr = tts.create(TEXT, voice=v, speed=1.0, lang="en-gb" if v.startswith("b") else "en-us")
    sf.write(os.path.join(OUT, f"voice_{v}.wav"), wav, sr)
    print("wrote", f"voice_{v}.wav")
