# Momo Roadmap

Goal: an assistant on par with Alexa for daily use, running locally: a devoted servant who calls you "Master".
Tools are grouped by **risk tier**, which decides when they can be built.

| Tier | Risk | Rule |
|---|---|---|
| 0 Local | none | no network, no outside text |
| 1 Structured network | very low | only numbers/enums come back; text is built locally |
| 2 Online free text | high (prompt injection) | only after the guardrails layer |
| 3 Outside actions | side effects | spoken confirmation before acting |

## Phase 0: Foundation ✅
- Removed developer/GitHub mode; local LLM via Ollama + LangChain; SQLite history.
- Custom "hey momo" wake word (openWakeWord, CNN1D, trained with 2,000 h of negatives).

## Phase 1: Voice, personality, weather & music ✅
| Item | Tier | Tool / component |
|---|---|---|
| Local LLM `llama3.1` 8B (was `qwen3:4b-instruct`) (router + responder) | – | `backend/core.py` |
| Local voice, CPU only (Kokoro-82M; replaced Chatterbox to free ~2 GB VRAM) | – | `tts/speak.py` |
| Servant personality + long-term memory + per-turn tool memory | 0 | `persona.py`, `remember`, `forget` |
| ~~Emotion system~~ (removed 2026-11-26) | – | – |
| Weather for Bengaluru (now / today / tomorrow) | 1 | `get_weather` |
| Music from YouTube, controls, ducking | 1 | `play_music`, `music_control` |
| Playlists (create/add/remove/list/delete, play in order or shuffled) | 0 | `manage_playlist` |

## Phase 2: Everyday local skills (Tier 0) (in progress)
- ✅ Time & date, timers, alarms, reminders (SQLite + scheduler thread; Momo speaks when they fire) — `tools/clock.py`
- ✅ To-do, shopping and named lists — `tools/lists.py`
- ✅ System volume, media keys — `tools/system.py`; calculator & unit conversion — `tools/calc.py`
- ✅ Routines: "good morning" (time + weather + reminders + optional playlist), "good night" — `tools/routines.py`
- ✅ Voice choice / blends (`MOMO_VOICE`) instead of cloning (Kokoro can't clone); ~~per-mood GIFs~~ (moods removed)
- ⏳ Wake word v3: synthetic positives generated (`scripts/make_wake_positives.py`, 252 clips); retraining to do

## Phase 3: Guardrails, then online knowledge (Tier 2)
- [x] Guardrails: egress allowlist, structured extractor, `<external_data trust="untrusted">` tagging, injection
      filter, output check, web data never reaches the router (the only LLM with tools), audit log
- [x] Wikipedia (`get_info`), news headlines (`get_news`, background refresh for NEWS_TOPICS)
- [x] Email drafting with on-screen approval only (pulled forward from Phase 4)
- [x] Open Netflix / Hotstar / Prime Video / YouTube (fixed URLs, launch only)
- [x] Hinglish speech (multilingual Whisper `small`) + Hinglish commands; instant small-talk replies; shutdown
- [x] General web search: `google_it` (DuckDuckGo + top pages through the extractor), 2026-11-28
- [ ] Cricket scores (live, structured)

## Phase 4: Outside actions (Tier 3)
- Smart home via Home Assistant (local API)
- Calendar, messaging/email: always "should I?" confirmation
- Voice-tone emotion detection (emotion2vec) so Momo hears *how* you say things
