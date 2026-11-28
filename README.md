# 🤖 Momo

Momo is a **local-first voice assistant** for Windows. Say **"Hey Momo"**, talk, and she answers out loud. Wake word,
speech-to-text, the LLM agent with its tools, and the voice all run on your own laptop. Only weather, music, Wikipedia,
news and web search use the internet. Momo is a devoted, obedient servant who calls you **"Master"** (you can change
this with `USER_TITLE` in `.env`).

```
"Hey Momo"  →  wake word (openWakeWord)  →  speech-to-text (faster-whisper)
            →  agent: fast paths / router LLM + tools (Ollama, llama3.1)  →  reply LLM
            →  voice (Kokoro-82M)  +  avatar window (Tk)
```

Progress log: [`PROGRESS.md`](PROGRESS.md) · Plan: [`ROADMAP.md`](ROADMAP.md) · Notes for contributors: [`CLAUDE.md`](CLAUDE.md)

---

## ✨ Current features

### Voice & window
- **Custom "Hey Momo" wake word**, trained for this project (`wakeword/models/hey_momo.onnx`).
- **Follow-up listening:** after she answers, Momo keeps listening for ~8 s, so you don't need to say "Hey Momo" again.
- **Local voice:** Kokoro-82M on the CPU, faster than real time. Pick a voice or blend voices with `MOMO_VOICE`.
- **Avatar window:** animated GIFs for idle / listening / thinking / speaking, a dance animation while music plays,
  a chat log, and live timers, alarms and reminders under the avatar (click **x** to cancel one).
- **Instant replies** with no LLM call for small talk ("hello", "thank you", "who are you", "what can you do").
- **Shut down:** say "Momo, shut down", click **⏻ Shut down**, or close the window. A popup asks you to confirm.

### Music (YouTube via yt-dlp + mpv)
- "Play *song / artist*", pause, resume, skip, stop, volume up / down / max / "set volume to 40".
- **Playlists:** create, "add this song to *chill*", remove, list, delete, play in order or shuffled.
- **Ducking:** when you say "Hey Momo", the music drops to half volume and keeps playing, then comes back up.

### Everyday skills
- **Time & date**, **timers**, **alarms**, **reminders** for any day ("friday", "5 december", "next monday").
  Momo speaks when one goes off, and tells you about the ones you missed while she was off.
- **Calendar:** add / show (a day or a week) / cancel events by voice. Can also read your Google Calendar (read-only).
- **Lists:** to-do, shopping, or any named list, with several items at once ("add milk and eggs").
- **Calculator** and **unit conversion** (length, mass, volume, temperature, speed, time, data, area).
- **PC control:** system volume and media keys.
- **Routines:** "good morning" (time, weather, today's alarms and reminders, optional playlist) and "good night".
- **Memory:** "remember that…" saves a fact about you. "forget…" deletes it. Every conversation is saved in a local
  SQLite database.

### Knowledge (online, read-only)
- **Weather** for your home city (now / today / tomorrow) from Open-Meteo.
- **Wikipedia** answers ("who is…", "what is…").
- **News headlines** by topic (Google News). Ask "tell me more about the second one" to hear that article.
- **Web search (`google_it`)** for recent or changing things: "who won…", "price of…", "google *X*".
  It searches DuckDuckGo and reads the top 3 pages.
- **Open Netflix, Hotstar, Prime Video or YouTube** in your default browser, Brave, Chrome or Edge.
  Momo only opens these 4 sites and never clicks anything on them.

### Email (with your approval)
- "Email mom that I'll be late" **writes a draft**. The email is sent only when you **click Approve & send** in the
  window. Voice can cancel a draft but can never send one. Momo can only email addresses listed in `EMAIL_CONTACTS`.

### Hindi / Hinglish mode
- Say "Momo, switch to Hindi" (or click **EN | हिंदी**). This switches speech recognition, the voice and the reply
  language. Hinglish commands like "Arijit Singh ka gaana bajao", "awaaz badhao" and "alarm lagao" work.

### Security
- Web text reaches the LLM only through a sanitiser that removes prompt injections (`security/extractor.py`), and only
  the reply model sees it. That model has no tools.
- Momo can only contact allowlisted hosts. Web search reads public HTTPS pages only: no local network, no forms,
  no logins.
- Every tool argument is checked against a schema. Every security event is logged to the database.

---

## 💻 Laptop this runs on

| Part | Spec |
|---|---|
| Laptop | ASUS TUF Gaming A16 (FA607NUG) |
| CPU | AMD Ryzen 7 7445HS, 6 cores / 12 threads (+ Radeon 740M integrated graphics) |
| GPU | NVIDIA GeForce RTX 4050 Laptop, **6 GB VRAM** (driver 621.14) |
| RAM | 16 GB |
| Storage | 1 TB NVMe SSD (WD SN5000S) |
| OS | Windows 11 Home (build 26200) |
| Software | Python 3.10.11 (`.venv`), Ollama 0.17.1, mpv (winget), Git 2.52 |

**How the hardware is shared:** only the LLM uses the GPU. llama3.1 8B (~6 GB with a 6k context) doesn't fully
fit in 6 GB, so it runs ~85% on the GPU and the rest on the CPU. That makes it 2-3x slower than `qwen3:4b-instruct`,
which fits entirely on the GPU. The voice, Whisper and the wake word all run on the CPU. PyTorch / CUDA are not needed.

**Minimum to run it elsewhere:** Windows 10/11, 16 GB RAM, a microphone, and ideally an NVIDIA GPU with at least
4 GB of VRAM (use `OLLAMA_MODEL=qwen3:4b-instruct` on smaller GPUs). It runs without a GPU, just slowly.

---

## 🚀 First-time setup (new laptop)

Run these in **PowerShell**.

```powershell
# 1. Get the code
git clone https://github.com/kannu74/MOMO_AI.git
cd MOMO_AI
git checkout voice-assistant-ollama        # the current working branch

# 2. Python 3.10 virtual environment + packages
py -3.10 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

# 3. External apps
winget install Ollama.Ollama
winget install mpv-player.mpv-CI.MSVC
ollama pull llama3.1                       # default LLM (or: ollama pull qwen3:4b-instruct)

# 4. Voice model files (~205 MB) into tts\models\
mkdir tts\models -Force
Invoke-WebRequest https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.fp16.onnx -OutFile tts\models\kokoro-v1.0.fp16.onnx
Invoke-WebRequest https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin -OutFile tts\models\voices-v1.0.bin

# 5. Settings
copy .env.example .env                     # then open .env and fill it in
```

**`.env`** holds every setting, and anything in `config.py` can be overridden there. Settings you will usually want
to change:

| Setting | What it does |
|---|---|
| `OLLAMA_MODEL` | `llama3.1:latest` (default) or `qwen3:4b-instruct` (faster, fits on the GPU) |
| `MIC_NAME` | Part of your microphone's name (default `USB Condenser`) |
| `USER_TITLE` | What Momo calls you (default `Master`) |
| `MOMO_VOICE` | Kokoro voice (default `af_heart`). Run `scripts\voice_samples.py` to hear all of them |
| `HOME_NAME`, `HOME_LAT`, `HOME_LON` | City used for weather (default Bengaluru) |
| `EMAIL_CONTACTS`, `SMTP_*` | Who Momo may email, and your Gmail **App Password** |
| `CALENDAR_ICS_URL` | Google Calendar → Settings → "Secret address in iCal format" |
| `NEWS_TOPICS`, `NEWS_REGION` | News topics and region Momo refreshes in the background |
| `GOOGLE_IT` | `1` = web search on, `0` = off |
| `LANGUAGE` | `en` or `hi` at start-up (Momo remembers the last choice you made) |

`.env`, `data/`, `audio/` and `tts/models/` are in `.gitignore`. They stay on your laptop and are never pushed.

---

## ▶️ Booting Momo up (every day)

> **Note:** the commands below use the folder on the main dev laptop
> (`C:\Users\Akshar\Desktop\momo again\MOMO_AI`). On another machine, `cd` into wherever you cloned `MOMO_AI`.
>
> **Note:** `MIC_NAME` defaults to `USB Condenser` (the mic on the dev laptop). If you use a different microphone,
> set `MIC_NAME` in `.env` to part of its name, or Momo won't hear you.

```powershell
cd "C:\Users\Akshar\Desktop\momo again\MOMO_AI"

ollama list                                 # check Ollama is running (start the Ollama app if this fails)
.\.venv\Scripts\python.exe main_ui.py       # start Momo: window + voice loop
```

Wait for the window to show that she's listening, then say **"Hey Momo"**. The first reply after start-up takes
~7 s while the model loads. After that, replies take a few seconds.

Other useful commands:

```powershell
.\.venv\Scripts\python.exe main_ui.py --demo            # preview the window only (no models, no mic)
.\.venv\Scripts\python.exe main.py                      # voice loop in the terminal, no window
.\.venv\Scripts\python.exe scripts\show_convos.py last  # read the latest conversation
.\.venv\Scripts\python.exe scripts\voice_samples.py     # hear every Kokoro voice
.\.venv\Scripts\python.exe scripts\test_google_it.py    # security / web-search tests (offline; add --live for one real search)
.\.venv\Scripts\python.exe scripts\eval_models.py security   # prompt-injection eval (no network)
```

Logs are written to `data\momo.log`.

### Things to try saying
> "Hey Momo, play some Arijit Singh" · "add this to my chill playlist" · "volume max"
> "set a timer for 10 minutes" · "remind me on friday at 6 pm to call mom" · "wake me up at 7"
> "what's the weather tomorrow" · "what's in the news" · "tell me more about the second one"
> "who won the last F1 race" · "add milk and eggs to my shopping list" · "what's 15% of 2400"
> "open Netflix in Brave" · "good morning" · "remember that my favourite colour is blue"
> "switch to Hindi" · "Momo, shut down"

### If something doesn't work
| Problem | Fix |
|---|---|
| She never hears "Hey Momo" | Check `MIC_NAME` in `.env` matches your mic. Speak closer, or lower `WAKEWORD_THRESHOLD` |
| "Can't reach the model" / no reply | Start the Ollama app, then check with `ollama list` |
| Music won't play | Check mpv is installed (`winget install mpv-player.mpv-CI.MSVC`), or set `MPV_PATH` |
| Very slow replies | Use `OLLAMA_MODEL=qwen3:4b-instruct` and close other apps that use the GPU |
| "Can't search right now" | DuckDuckGo blocked the IP after too many searches. Wait a few hours |
| No voice / crash at start | Check that both Kokoro files are in `tts\models\` |

---

## ⬆️ Pushing changes to GitHub

Repo: <https://github.com/kannu74/MOMO_AI>. Day-to-day work happens on **`voice-assistant-ollama`**. `main` is the
stable branch.

```powershell
cd "C:\Users\Akshar\Desktop\momo again\MOMO_AI"

git status                                  # see what changed
git pull                                    # get teammates' changes first
git add -A                                  # stage everything (.env, data/, models are ignored automatically)
git status                                  # double-check that .env is NOT in the list
git commit -m "Short description of what you changed"
git push                                    # push to origin/voice-assistant-ollama
```

Working on a new feature in its own branch:

```powershell
git checkout -b feature/my-feature          # create the branch and switch to it
# ...make changes, then add + commit as above...
git push -u origin feature/my-feature       # first push of the new branch
# Open a pull request on GitHub (or: gh pr create --base main)
```

Other useful commands:

```powershell
git branch -a                               # list local + remote branches
git checkout voice-assistant-ollama         # switch back to the working branch
git log --oneline -10                       # recent commits
git restore <file>                          # throw away uncommitted changes to one file
```

⚠️ **Never commit `.env`.** It holds your email password and private calendar link. It is in `.gitignore`. If
`git status` ever lists it, run `git rm --cached .env` before you commit.

---

## 📁 Project structure

```
MOMO_AI/
├── main_ui.py          # ▶️ Start here: Tk window (avatar, chat, timers) + runs main.py's loop in a thread
├── main.py             # Voice loop: wake word → record → STT → agent → speak; scheduler for timers/alarms
├── config.py           # Every setting (each one can be overridden in .env)
├── requirements.txt    # Python packages (+ model download links in the header)
├── .env.example        # Copy to .env
├── backend/
│   ├── core.py         # Agent: normalise → fast paths / router LLM → tools → reply
│   ├── persona.py      # Momo's character + router prompt
│   ├── database.py     # SQLite memory (data/memory.db) + migrations
│   ├── language.py     # English / Hindi mode
│   └── hindi.py        # Hindi reply templates
├── tools/              # Everything Momo can do (registry in __init__.py)
│   ├── music.py  weather.py  clock.py  dates.py  calendar_tool.py  lists.py
│   ├── calc.py   system.py   routines.py  info.py  search.py  entertainment.py  lyrics.py
├── security/           # egress allowlist, injection extractor, email outbox/approval, audit log
├── stt/listen.py       # faster-whisper speech-to-text (CPU)
├── tts/speak.py        # Kokoro voice (CPU); models in tts/models/ (not in git)
├── wakeword/           # openWakeWord detector + hey_momo.onnx
├── gui/avatar.py       # Avatar helper
├── assets/             # Avatar GIFs
└── scripts/            # Evals, tests, voice samples, conversation viewer
```

## 🛠 Tech stack
Python 3.10 · Ollama (llama3.1 8B / qwen3:4b) via LangChain · faster-whisper · openWakeWord · Kokoro-82M (ONNX) ·
yt-dlp + mpv · SQLite · Tkinter · Open-Meteo · Wikipedia · Google News · DuckDuckGo
