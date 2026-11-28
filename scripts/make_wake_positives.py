"""Wake word v3 (Roadmap Phase 2): synthetic "hey momo" positives from every English Kokoro voice.

    .venv\\Scripts\\python scripts\\make_wake_positives.py            # -> ../wakeword training/synthetic_positives/

Writes 16 kHz mono WAVs (the format the training notebook reads) named <voice>_<speed>_<variant>.wav.
Use them in `train_hey_momo.ipynb` as extra positives next to `audio/`. Group them by voice when splitting
(the `group` column), so the same synthetic voice never lands in both train and test.
Real recordings stay the most important positives; these add speaker variety to raise recall.
"""
import os
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tts import speak  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "wakeword training", "synthetic_positives")
PHRASES = {"a": "Hey Momo.", "b": "Hey, Momo!", "c": "Hey Momo?"}
SPEEDS = (0.85, 1.0, 1.15)
SR_OUT = 16000


def to_16k(wav: np.ndarray, sr: int) -> np.ndarray:
    try:
        from scipy.signal import resample_poly
        return resample_poly(wav, SR_OUT, sr).astype(np.float32)
    except ImportError:
        t = np.arange(int(len(wav) * SR_OUT / sr)) * sr / SR_OUT
        return np.interp(t, np.arange(len(wav)), wav).astype(np.float32)


def trim(wav: np.ndarray, top_db=35) -> np.ndarray:
    env = np.abs(wav)
    thr = env.max() * 10 ** (-top_db / 20)
    idx = np.where(env > thr)[0]
    return wav[max(0, idx[0] - 800): idx[-1] + 1600] if len(idx) else wav


def main():
    os.makedirs(OUT, exist_ok=True)
    tts = speak._load()
    voices = [v for v in tts.get_voices() if v[:2] in ("af", "am", "bf", "bm")]
    n = 0
    for v in voices:
        for spd in SPEEDS:
            for key, text in PHRASES.items():
                lang = "en-gb" if v.startswith("b") else "en-us"
                wav, sr = tts.create(text, voice=v, speed=spd, lang=lang)
                clip = trim(to_16k(wav, sr))
                clip = 0.9 * clip / (np.abs(clip).max() + 1e-9)
                sf.write(os.path.join(OUT, f"{v}_{int(spd * 100)}_{key}.wav"), clip, SR_OUT)
                n += 1
        print(f"{v}: done ({n} clips so far)", flush=True)
    print(f"Wrote {n} clips to {os.path.abspath(OUT)}")


if __name__ == "__main__":
    main()
