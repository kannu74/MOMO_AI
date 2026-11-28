"""Speech-to-text with faster-whisper on the CPU (keeps the GPU free for the LLM).

Two language modes (backend/language.py switches them; only ONE model is loaded at a time):
  en  English only: config.WHISPER_MODEL (base.en).
  hi  Hindi + Hinglish: config.WHISPER_MODEL_HI (multilingual, loaded instead of the English model).
        WHISPER_HINDI_SCRIPT=latin (default): written in Latin letters ("kal subah alarm lagao", "Tum Hi Ho"),
                         fastest, song names stay searchable; backend.core translates it;
        devanagari:      language="hi" (Devanagari text).
"""
import gc
import re
import threading

import numpy as np
from faster_whisper import WhisperModel

import config

_lock = threading.Lock()
_state = {"lang": None, "model": None, "name": None}

# Whisper's classic hallucinations on music, noise or silence (seen in Momo's logs too)
_HALLUCINATIONS = re.compile(r"^(thanks for watching!?|you\.?|\.+|\s*(\. )+\.?|"
                             r"may the lord bless you\.?|please subscribe.*|subtitles by.*|♪+|"
                             r"धन्यवाद[।.]?|सब्सक्राइब.*)$", re.I)


def load(lang: str = "en") -> None:
    """Load the speech model for a language mode, freeing the other one first."""
    name = config.WHISPER_MODEL_HI if lang == "hi" else config.WHISPER_MODEL
    with _lock:
        if _state["name"] == name and _state["lang"] == lang:
            return
        if _state["name"] != name:
            _state["model"] = None
            gc.collect()
            print(f"Loading speech-to-text model ({name}, {lang})...")
            _state["model"] = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=config.WHISPER_THREADS)
            _state["name"] = name
        _state["lang"] = lang


def transcribe_audio_chunk(audio_np: np.ndarray) -> str:
    if audio_np.size == 0:
        return ""
    if _state["model"] is None:
        load("en")
    audio = audio_np.flatten().astype(np.float32) / 32768.0
    with _lock:
        hindi = _state["lang"] == "hi"
        deva = hindi and config.WHISPER_HINDI_SCRIPT == "devanagari"
        prompt = config.WHISPER_PROMPT_HI if deva else (config.WHISPER_PROMPT_HI_LATIN if hindi else config.WHISPER_PROMPT)
        segments, _ = _state["model"].transcribe(
            audio, beam_size=config.WHISPER_BEAM_HI if deva else 5, vad_filter=True, condition_on_previous_text=False,
            language="hi" if deva else "en", initial_prompt=prompt)
        kept = []
        for s in segments:
            # drop segments Whisper itself thinks are not speech / are guesses (lyrics, noise)
            if s.no_speech_prob > 0.6 and s.avg_logprob < -0.7:
                continue
            if s.avg_logprob < -1.2 or s.compression_ratio > 2.4:
                continue
            kept.append(s.text.strip())
    text = " ".join(kept).strip()
    return "" if _HALLUCINATIONS.match(text) else text
