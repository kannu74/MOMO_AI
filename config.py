"""Central settings for Momo. Override any value in .env."""
import glob
import json
import os
import shutil

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(ROOT, ".env"))


def _env(name, default):
    return os.getenv(name, default)


# --- LLM (local, via Ollama) ---
# llama3.1 = Llama 3 (8B) with tool calling; the original llama3:8b can't call tools in Ollama (Momo's router needs it).
# 8B Q4_K_M is ~5 GB: on the 6 GB RTX 4050 ~85% sits on the GPU, the rest on the CPU. Old default: qwen3:4b-instruct.
OLLAMA_MODEL = _env("OLLAMA_MODEL", "llama3.1:latest")
OLLAMA_URL = _env("OLLAMA_URL", "http://localhost:11434")
HISTORY_LIMIT = int(_env("HISTORY_LIMIT", 10))          # messages of chat context
OLLAMA_NUM_CTX = int(_env("OLLAMA_NUM_CTX", 6144))      # the voice no longer uses the GPU, so the LLM gets more room

# --- How Momo addresses you ---
USER_TITLE = _env("USER_TITLE", "Master")

# --- Wake word ---
WAKEWORD_MODEL_NAME = _env("WAKEWORD_MODEL_NAME", "hey_momo")
WAKEWORD_MODEL_PATH = os.path.join(ROOT, "wakeword", "models", f"{WAKEWORD_MODEL_NAME}.onnx")
_meta = os.path.join(ROOT, "wakeword", "models", f"{WAKEWORD_MODEL_NAME}.json")
WAKEWORD_THRESHOLD = float(_env("WAKEWORD_THRESHOLD",
                                json.load(open(_meta))["threshold"] if os.path.exists(_meta) else 0.5))

# --- Microphone: part of the device name (see `python -m sounddevice`); empty = Windows default ---
MIC_NAME = _env("MIC_NAME", "USB Condenser")
WAKE_LOG_MIN = float(_env("WAKE_LOG_MIN", 0.2))         # log wake scores above this (near misses)

# --- Conversation timing (seconds) ---
END_SILENCE_SEC = float(_env("END_SILENCE_SEC", 1.5))   # pause that means "I'm done talking"
START_TIMEOUT_SEC = float(_env("START_TIMEOUT_SEC", 8))  # time to start talking after "Yes?"
FOLLOWUP_SEC = float(_env("FOLLOWUP_SEC", 8))            # keep listening after a reply, no wake word needed
MAX_UTTERANCE_SEC = float(_env("MAX_UTTERANCE_SEC", 25))  # hard cap on one request

# --- Speech-to-text ---
# English mode: English only (base.en: fast, ~0.5 s). Hindi mode loads WHISPER_MODEL_HI instead (only one in memory).
WHISPER_MODEL = _env("WHISPER_MODEL", "base.en")
WHISPER_THREADS = int(_env("WHISPER_THREADS", 8))
# Hindi mode ("Momo, switch to Hindi"): Hindi and Hinglish, with WHISPER_MODEL_HI (multilingual). How it's written:
#   latin       (default) "kal subah saat baje alarm lagao": ~2 s, names stay in Latin
#               letters (good for YouTube). Measured: all 12 pure-Hindi test commands understood.
#   devanagari  "कल सुबह सात बजे अलार्म लगाओ" with WHISPER_MODEL_HI (loaded instead of WHISPER_MODEL):
#               small 86% / 3.3 s, medium 90% / 5.8 s per request on this CPU.
WHISPER_HINDI_SCRIPT = _env("WHISPER_HINDI_SCRIPT", "latin")
WHISPER_MODEL_HI = _env("WHISPER_MODEL_HI", "small")
WHISPER_PROMPT_HI_LATIN = _env("WHISPER_PROMPT_HI_LATIN", "Momo, kal subah saat baje ka alarm lagao. Arijit Singh ka "
                               "gaana bajao. Aaj mausam kaisa hai? Meri shopping list mein doodh daalo. Paanch minute "
                               "ka timer laga do. Gaana band karo.")
WHISPER_BEAM_HI = int(_env("WHISPER_BEAM_HI", 1))
WHISPER_PROMPT_HI = _env("WHISPER_PROMPT_HI", "मोमो, गाना बजाओ, टाइमर लगाओ, अलार्म, याद दिलाना, मौसम, शॉपिंग लिस्ट, "
                         "अरिजीत सिंह, नेटफ्लिक्स।")
# Hints Whisper towards Latin-letter Hinglish and the names you use (add your favourite artists here).
WHISPER_PROMPT = _env("WHISPER_PROMPT", "Hey Momo, play music, add this to my playlist, set a timer, weather.")

# --- Voice (Kokoro-82M via onnxruntime, on the CPU: no VRAM) ---
VOICE_MODEL = _env("VOICE_MODEL", os.path.join(ROOT, "tts", "models", "kokoro-v1.0.fp16.onnx"))
VOICE_VOICES = _env("VOICE_VOICES", os.path.join(ROOT, "tts", "models", "voices-v1.0.bin"))
# One voice ("af_heart") or a blend ("af_heart:70,af_bella:30"). Samples: scripts/voice_samples.py
VOICE_NAME = _env("MOMO_VOICE", "af_heart")
VOICE_SPEED = float(_env("VOICE_SPEED", 1.0))
VOICE_THREADS = int(_env("VOICE_THREADS", 8))
VOICE_NAME_HI = _env("MOMO_VOICE_HI", "hf_alpha")    # Hindi voices: hf_alpha, hf_beta (female), hm_omega, hm_psi

# --- Language mode: "en" (English + Hinglish) or "hi" (pure Hindi). Switch by voice or in the window. ---
LANGUAGE = _env("LANGUAGE", "en")                   # start-up default; the last choice is remembered in data/
USER_TITLE_HI = _env("USER_TITLE_HI", "मालिक")
# Optional: a different Ollama model per language. Only the active one stays loaded (the other is unloaded,
# so the GPU never holds both). Empty = OLLAMA_MODEL for both.
OLLAMA_MODEL_HI = _env("OLLAMA_MODEL_HI", "")

# --- Home location for weather (Open-Meteo, no API key) ---
HOME_NAME = _env("HOME_NAME", "Bengaluru")
HOME_LAT = float(_env("HOME_LAT", 12.9716))
HOME_LON = float(_env("HOME_LON", 77.5946))
HOME_TZ = _env("HOME_TZ", "Asia/Kolkata")

# --- Music (mpv + yt-dlp) ---
def _find_mpv():
    found = shutil.which("mpv") or glob.glob(os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\mpv*\mpv.exe"))
    return found if isinstance(found, str) else (found[0] if found else "mpv.exe")


MPV_PATH = _env("MPV_PATH", _find_mpv())
MUSIC_VOLUME = int(_env("MUSIC_VOLUME", 60))
# While Momo listens/speaks the music keeps playing, just softer: volume x DUCK_RATIO (never below DUCK_MIN).
DUCK_RATIO = float(_env("DUCK_RATIO", 0.5))
DUCK_MIN = int(_env("DUCK_MIN", 20))

# --- Routines ---
MORNING_PLAYLIST = _env("MORNING_PLAYLIST", "")     # saved playlist to start on "good morning" (empty = none)

# --- Web knowledge & news (security/: egress allowlist -> structured extractor -> <external_data>) ---
NEWS_TOPICS = [t.strip() for t in _env("NEWS_TOPICS", "technology, india, anime").split(",") if t.strip()]
NEWS_REGION = _env("NEWS_REGION", "IN")              # Google News edition (IN, US, GB...)
NEWS_REFRESH_MIN = int(_env("NEWS_REFRESH_MIN", 60))  # background refresh of NEWS_TOPICS (0 = off)
WEB_MAX_FETCHES = int(_env("WEB_MAX_FETCHES", 40))   # per 5 minutes, all web tools together (one google_it = 1 + pages)
WEB_MAX_BYTES = 2_000_000                           # biggest response Momo will read
INFO_MAX_FACTS = int(_env("INFO_MAX_FACTS", 5))      # context minimisation: sentences handed to the LLM
INFO_MAX_CHARS = int(_env("INFO_MAX_CHARS", 900))

# --- google_it(topic): web search (DuckDuckGo; Google itself needs JavaScript) + reading the top result pages ---
# Only the cleaned topic is sent to the search engine. Pages are read with security.egress.safe_get_page (public
# https hosts only) and reach the LLM only through security/extractor.py, like Wikipedia. GOOGLE_IT=0 turns it off.
SEARCH_ENABLED = _env("GOOGLE_IT", "1").lower() not in ("0", "false", "off", "no")
SEARCH_URL = "https://lite.duckduckgo.com/lite/"
SEARCH_RESULTS = int(_env("SEARCH_RESULTS", 6))         # results whose titles/snippets are considered
SEARCH_FETCH_PAGES = int(_env("SEARCH_FETCH_PAGES", 3))  # top pages actually read (in parallel)
SEARCH_MAX_FACTS = int(_env("SEARCH_MAX_FACTS", 8))      # sentences handed to the LLM, all sources together
SEARCH_MAX_CHARS = int(_env("SEARCH_MAX_CHARS", 1500))
# Pages Momo never reads (social media / video / shops: little text, lots of junk). Sub-domains included.
SEARCH_BLOCKED_HOSTS = {h.strip().lower() for h in _env(
    "SEARCH_BLOCKED_HOSTS", "facebook.com, instagram.com, x.com, twitter.com, tiktok.com, youtube.com, "
    "pinterest.com, linkedin.com, amazon.com, amazon.in, flipkart.com").split(",") if h.strip()}

# --- Email (drafted by voice, sent ONLY after you press Approve in the window) ---
# EMAIL_CONTACTS="me=you@example.com; mom=mom@example.com"  -- the ONLY addresses Momo can ever email
EMAIL_CONTACTS = {k.strip().lower(): v.strip() for k, v in
                  (p.split("=", 1) for p in _env("EMAIL_CONTACTS", "").split(";") if "=" in p)}
SMTP_HOST = _env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(_env("SMTP_PORT", 465))
SMTP_USER = _env("SMTP_USER", "")
SMTP_PASSWORD = _env("SMTP_PASSWORD", "")           # Gmail: an App Password, not your normal password
EMAIL_FROM = _env("EMAIL_FROM", SMTP_USER)
EMAIL_APPROVAL_PIN = _env("EMAIL_APPROVAL_PIN", "")  # optional: also type this PIN in the approval window
EMAIL_DRAFT_TTL_MIN = int(_env("EMAIL_DRAFT_TTL_MIN", 15))

# --- Calendar: local events + Google Calendar read-only ("Secret address in iCal format") ---
CALENDAR_ICS_URL = _env("CALENDAR_ICS_URL", "")
CALENDAR_REMIND_MIN = int(_env("CALENDAR_REMIND_MIN", 30))   # reminder before events you add by voice (0 = off)

# --- Network allowlist: the only hosts Momo's tools may contact (security/egress.py enforces it) ---
ALLOWED_HOSTS = {"api.open-meteo.com", "www.youtube.com", "youtube.com",
                 "en.wikipedia.org", "hi.wikipedia.org", "news.google.com", "calendar.google.com", "lrclib.net", "lite.duckduckgo.com", SMTP_HOST}
