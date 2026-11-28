# CLAUDE.md

Guidance for Claude (and humans) working on this repo.

## What Momo is
A **local-first voice assistant**: a devoted, obedient servant who addresses the user as **"Master"**
(`config.USER_TITLE`). Everything runs on this machine: wake word → speech-to-text → local LLM agent with tools →
local voice. Goal: Alexa-level usefulness (see `ROADMAP.md`) without cloud dependencies. Status: `PROGRESS.md`.

## Run
```powershell
.venv\Scripts\python main_ui.py                     # start Momo (window + voice loop)
.venv\Scripts\python main_ui.py --demo              # preview the window without models
.venv\Scripts\python scripts\show_convos.py last    # read the latest conversation
.venv\Scripts\python scripts\voice_samples.py       # hear every Kokoro voice, pick one for MOMO_VOICE
```
Prereqs: Ollama running with `llama3.1` (default `OLLAMA_MODEL=llama3.1:latest`; the old `qwen3:4b-instruct` still works); mpv installed (`winget install mpv-player.mpv-CI.MSVC`);
Kokoro model files in `tts/models/` (URLs in the header of `requirements.txt`). Use the project `.venv`.

## Architecture
| Path | Role |
|---|---|
| `main_ui.py` | Tk window (avatar GIFs `assets/{idle,listening,thinking,speaking}.gif`, `dance_*.gif` while music plays, status, chat log). Starts `main.main()` in a thread; UI updates arrive via a queue. |
| `main.py` | Voice loop: wake word → duck music (softer, keeps playing) → re-measure mic threshold → record → STT → `backend.core.respond` → speak → unduck. Scheduler thread announces due timers/alarms/reminders. |
| `config.py` | All settings; every value can be overridden in `.env`. |
| `backend/core.py` | Agent: `normalize` (wake word / STT slips) → **fast paths** (regex) or **router** (LLM + tools, sees recent turns *with what the tools did*) → `_guard` → `tools.run_tool` → **templated confirmation** for commands or **responder** LLM for chat/weather → DB. |
| `backend/persona.py` | Character sheet, responder system prompt, router prompt with examples. Personality changes go here. |
| `backend/database.py` | SQLite `data/memory.db` schema + auto-migrations (`MOMO_DB` env overrides the path, for tests). |
| `tools/__init__.py` | Tool registry: LangChain `@tool`s with `Literal` schemas, allowlist, timeouts. |
| `tools/weather.py`, `tools/music.py` | Open-Meteo weather; yt-dlp + mpv (named-pipe IPC) music, playlists, ducking. |
| `tools/clock.py` | Time/date, timers, alarms, reminders + local duration/clock-time parsing. |
| `tools/lists.py`, `tools/calc.py`, `tools/system.py`, `tools/routines.py` | Lists; safe AST calculator + unit conversion; PC volume/media keys (ctypes); good morning / good night. |
| `security/` | `egress.py` (host/recipient allowlists, data minimisation, rate limit), `extractor.py` (structured extractor + injection filter), `outbox.py` (email drafts + approval), `audit.py` (`security_events`). |
| `tools/info.py`, `tools/entertainment.py`, `tools/lyrics.py` | Wikipedia + news (through `security/`); open the 4 streaming sites; lyrics from lrclib.net for the window only (never sent to the LLM). |
| `tools/search.py` | `google_it(topic)`: DuckDuckGo lite search (30 min cache, bot-check detection) → reads the top 3 result pages (`egress.safe_get_page`) → `security/extractor.py` → `<external_data>`. News questions use today's Google News headlines as the stories and read each article. Wikipedia and web search fall back to each other. After headlines Momo offers more: "tell me more about the second one" → `core._news_followup` → google_it on that headline. `GOOGLE_IT=0` turns it all off. |
| `backend/language.py`, `backend/hindi.py` | Language mode en/hi (switches STT, voice, reply language; settings.json); Hindi confirmation templates. |
| `tools/dates.py`, `tools/calendar_tool.py` | Spoken date parsing; calendar (local events + Google iCal read-only). |
| `tts/speak.py` | Kokoro-82M (ONNX fp16) on the **CPU**, voice blends, sentence pipelining, phrase cache, chime. |
| `stt/listen.py` | faster-whisper on the CPU: English mode `base.en` (English only); Hindi mode `small` multilingual (Hindi + Hinglish, Latin letters). Only one loaded. `core.hinglish()` maps Hinglish commands to English in Hindi mode only. |
| `wakeword/` | openWakeWord runtime + `models/hey_momo.onnx` (trained in `../wakeword training/`). |

GPU budget (RTX 4050, 6 GB): only the LLM. llama3.1 8B (~6 GB incl. 6k context) doesn't fully fit: ~85% GPU, rest CPU.
qwen3:4b (~3.4 GB) fits entirely. Voice, Whisper and wake word are CPU.
torch is no longer imported anywhere.

## Safety rules (non-negotiable)
1. **Web text reaches the LLM only through `security/extractor.py`** (sanitised, injection-filtered, minimised,
   escaped inside `<external_data trust="untrusted">`), only the responder (no tools) sees it, and it is never stored
   in history or shown to the router. All other tools return numbers, enums or locally built messages.
   News headlines are read out by a template (no LLM). Song titles are never put in prompts.
2. Tools can only contact hosts in `config.ALLOWED_HOSTS`. The one exception: `google_it` reads the pages the
   search engine returned, via `egress.safe_get_page` (https:443, public IPs only, no LAN/localhost, redirects
   re-checked, HTML only, size cap, rate limit, `SEARCH_BLOCKED_HOSTS`). URLs never come from the LLM; only the
   cleaned topic (grounded in the user's words) is sent to the search engine.
3. Every tool argument is schema-validated; only tools in `tools.TOOLS` can run.
4. Anything that acts outside this PC needs human approval. **Email: only drafted by voice; sent only by a mouse
   click on Approve in the window** (`security/outbox.py`; voice can cancel, never approve). Recipients must be in
   `EMAIL_CONTACTS` and are re-checked at send time. Nothing sends email automatically.
5. Only `open_entertainment`'s four fixed URLs can be opened in a browser; Momo never controls a web page.
   `google_it` only reads pages; it never submits forms, logs in or sends anything but a plain GET.
6. Music is only stopped/paused when the user's words say so (`core._guard`); `forget` only runs on "forget".

## Gotchas
- Run from the `MOMO_AI` folder: `.\.venv\Scripts\python.exe main_ui.py`.
- `tools/system.py` presses real Windows keys. In tests, stub `tools.system._press`.
- Test the agent against a copy of the DB: `MOMO_DB=<copy> python ...`, and stub `tools.music.player` / `_search`
  so nothing plays.
- The tool history stored per user message (`messages.tools`) is shown to the LLM, so tool results must stay
  locally built (rule 1).

## Conventions
- Spoken replies: ≤ 2 sentences, no markdown/emojis/bracket tags. `backend/core.clean_reply` enforces this.
- Commands get a templated reply (`core.template_reply`: "Yes, Master. <tool result>"), so tool results must be
  complete, speakable sentences. A result ending in "?" makes Momo keep listening for the answer.
- New tool = function in `tools/<name>.py` + `@tool` wrapper with `Literal` args in `tools/__init__.py` + a router
  example in `persona.ROUTER_PROMPT` + the "You can:" line in `persona.CHARACTER` + `ROADMAP.md`/`PROGRESS.md`.
  Add a fast path in `core.FAST_PATHS` if the phrasing is unambiguous.
- Schema changes: add to `SCHEMA` and, for existing tables, a step in `database._migrate`.
- Personal data (`data/`, `audio/`, `.env`) and model files (`tts/models/`) are never committed.
- Tests: `scripts/test_google_it.py` (security/unit, `--live` for one real search); `scripts/eval_models.py all`
  (model × google_it evals: routing, answers, injection, latency; results in `data/evals/`); `eval_models.py security`
  runs only the poisoned-page test (no network). An eval sends ~100 searches: DuckDuckGo may then block the IP for hours.
- Update `PROGRESS.md` when finishing a feature.
