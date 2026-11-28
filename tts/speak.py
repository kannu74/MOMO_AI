# tts/speak.py
"""Momo's voice: Kokoro-82M (ONNX, fp16) on the CPU. Uses no VRAM and doesn't need torch.

* Voice = one Kokoro voice ("af_heart") or a weighted blend ("af_heart:70,af_bella:30"), see config.VOICE_NAME.
* Sentence pipelining: the next sentence is generated while the current one plays,
  so Momo starts talking as soon as the first sentence is ready.
* Short phrases (e.g. "Yes, Master?") are cached.
* `beep()` plays a locally generated chime for timers and alarms.
* `set_language("hi")` switches to a Hindi voice (config.VOICE_NAME_HI, Devanagari text) using the same model:
  no reload, no extra memory.
"""
import os
import queue
import re
import threading

import numpy as np
import sounddevice as sd

import config

_tts = None
_style = None
_cache = {}
_load_lock = threading.Lock()
_lang = {"code": "en-us", "spec": None}
SR = 24000


def _parse_voice(spec: str):
    """'af_heart' -> 'af_heart';  'af_heart:70,af_bella:30' -> blended style vector."""
    if ":" not in spec and "," not in spec:
        return spec.strip()
    parts = []
    for item in spec.split(","):
        name, _, w = item.strip().partition(":")
        parts.append((name.strip(), float(w or 1)))
    total = sum(w for _, w in parts)
    return sum(_tts.get_voice_style(n) * (w / total) for n, w in parts)


def _load():
    global _tts, _style
    with _load_lock:
        if _tts is None:
            import onnxruntime as ort
            from kokoro_onnx import Kokoro
            for f in (config.VOICE_MODEL, config.VOICE_VOICES):
                if not os.path.exists(f):
                    raise FileNotFoundError(f"{f} missing (see the header of requirements.txt)")
            print(f"Loading Kokoro voice ({os.path.basename(config.VOICE_MODEL)}, CPU)...")
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = config.VOICE_THREADS
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            sess = ort.InferenceSession(config.VOICE_MODEL, opts, providers=["CPUExecutionProvider"])
            _tts = Kokoro.from_session(sess, config.VOICE_VOICES)
            _style = _parse_voice(_lang["spec"] or config.VOICE_NAME)
    return _tts


def set_language(lang: str) -> None:
    """'en' -> English voice, 'hi' -> Hindi voice. Clears the phrase cache (it was in the other voice)."""
    global _style
    spec, code = (config.VOICE_NAME_HI, "hi") if lang == "hi" else (config.VOICE_NAME, "en-us")
    _lang.update(code=code, spec=spec)
    _cache.clear()
    if _tts is not None:
        _style = _parse_voice(spec)


def warm_up(phrases=()):
    """Load the model and pre-generate short fixed phrases."""
    _generate("Ready.")
    for p in phrases:
        _cache[p] = _generate(p)


def _generate(text: str) -> np.ndarray:
    tts = _load()
    samples, _ = tts.create(text, voice=_style, speed=config.VOICE_SPEED, lang=_lang["code"])
    return samples.astype(np.float32)


def _speakable(text: str) -> str:
    text = re.sub(r"\[[^\]]*\]", "", text)                     # no sound tags in Kokoro
    text = re.sub(r"\s*°\s*C\b", " डिग्री" if _lang["code"] == "hi" else " degrees", text)
    text = text.replace("%", " प्रतिशत" if _lang["code"] == "hi" else " percent")
    return re.sub(r"\s+", " ", text).strip()


def _sentences(text: str):
    parts = re.split(r"(?<=[.!?…।])\s+", text.strip())
    return [p for p in parts if re.search(r"\w", p)]


def speak(text: str, emotion: str = ""):
    """Speak `text` and block until playback finishes. (`emotion` is accepted for compatibility, unused.)"""
    if not text:
        return
    if text in _cache:
        sd.play(_cache[text], SR); sd.wait(); return
    try:
        _load()
    except Exception as e:
        print(f"[voice] unavailable ({e}). Momo: {text}")
        return
    sents = _sentences(_speakable(text))
    q = queue.Queue(maxsize=2)

    def producer():
        for s in sents:
            try:
                q.put(_generate(s))
            except Exception as e:
                print(f"[voice] failed on {s!r}: {e}")
        q.put(None)

    threading.Thread(target=producer, daemon=True).start()
    while (wav := q.get()) is not None:
        sd.play(wav, SR)
        sd.wait()


def _chime() -> np.ndarray:
    t = np.linspace(0, 0.18, int(SR * 0.18), endpoint=False)
    env = np.exp(-t * 14)
    note = lambda f: np.sin(2 * np.pi * f * t) * env
    gap = np.zeros(int(SR * 0.06))
    return (0.35 * np.concatenate([note(880), gap, note(1175), gap, note(1568), np.zeros(int(SR * 0.25))])).astype(np.float32)


def beep(times: int = 2):
    """Alarm/timer chime, generated locally."""
    sd.play(np.tile(_chime(), times), SR)
    sd.wait()
