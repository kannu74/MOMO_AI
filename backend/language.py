"""Language mode: "en" (English only) or "hi" (Hindi + Hinglish, answers in Hindi).

Switching ("Momo, switch to Hindi", "Momo, switch to English", or the EN / हिंदी buttons in the window):
  * speech-to-text: loads that language's Whisper model and frees the other (only one in memory),
  * voice: Kokoro English voice <-> Hindi voice (same model, nothing reloaded),
  * brain: backend.core answers in that language; an optional per-language Ollama model (OLLAMA_MODEL_HI)
    replaces the current one and the old one is unloaded from the GPU,
  * the choice is saved in data/settings.json and used at the next start.
"""
import json
import os
import re
import threading

import config

NAMES = {"en": "English", "hi": "हिंदी"}
_SETTINGS = os.path.join(config.ROOT, "data", "settings.json")
_lock = threading.Lock()
_listeners = []
state = {"lang": None, "busy": False}

# "switch to hindi", "hindi mode", "hindi mein baat karo", "हिंदी में बात करो", "स्विच टू हिंदी"
TO_HINDI = re.compile(r"\b(?:switch|change|go)\s+(?:to\s+)?(?:pure\s+)?(?:hindi|hinglish)\b|\b(?:hindi|hinglish)\s+mode\b|"
                      r"\bhindi\s+(?:mein|me|main)\s+(?:baat|bol)|\bspeak\s+(?:in\s+)?hindi\b|"
                      r"(?:स्विच|चेंज)\s*(?:टू)?\s*हिंदी|हिंदी\s+(?:में|मे)\s+(?:बात|बोल)|हिंदी\s+मोड", re.I)
TO_ENGLISH = re.compile(r"\b(?:switch|change|go)\s+(?:back\s+)?(?:to\s+)?english\b|\benglish\s+mode\b|"
                        r"\b(?:english|angrezi)\s+(?:mein|me|main)\s+(?:baat|bol)|\bspeak\s+(?:in\s+)?english\b|"
                        r"(?:स्विच|चेंज)\s*(?:टू)?\s*(?:इंग्लिश|अंग्रेज़ी|अंग्रेजी)|"
                        r"(?:इंग्लिश|अंग्रेज़ी|अंग्रेजी)\s+(?:में|मे)\s+(?:बात|बोल)|इंग्लिश\s+मोड", re.I)


def requested(text: str):
    """'hi' / 'en' if the user asked to switch language, else None."""
    if TO_HINDI.search(text or ""):
        return "hi"
    if TO_ENGLISH.search(text or ""):
        return "en"
    return None


def on_change(fn):
    _listeners.append(fn)


def saved() -> str:
    try:
        with open(_SETTINGS, encoding="utf-8") as f:
            lang = json.load(f).get("language")
    except Exception:
        lang = None
    return lang if lang in NAMES else (config.LANGUAGE if config.LANGUAGE in NAMES else "en")


def _save(lang):
    try:
        data = {}
        if os.path.exists(_SETTINGS):
            with open(_SETTINGS, encoding="utf-8") as f:
                data = json.load(f)
        data["language"] = lang
        with open(_SETTINGS, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[lang] could not save: {e}")


def current() -> str:
    return state["lang"] or "en"


def set_language(lang: str) -> bool:
    """Switch everything to `lang`. Returns False if it was already active or a switch is running."""
    from backend import core
    from stt import listen
    from tts import speak
    if lang not in NAMES:
        return False
    with _lock:
        if state["busy"] or state["lang"] == lang:
            return False
        state["busy"] = True
    try:
        for fn in _listeners:
            fn("switching", lang)
        listen.load(lang)                                          # frees the other Whisper model first
        speak.set_language(lang)
        core.set_llm((config.OLLAMA_MODEL_HI if lang == "hi" else "") or config.OLLAMA_MODEL)
        core.LANG["code"] = lang
        state["lang"] = lang
        _save(lang)
        print(f"[lang] now {NAMES[lang]}")
    finally:
        state["busy"] = False
    for fn in _listeners:
        fn("done", lang)
    return True
