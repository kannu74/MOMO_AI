"""Momo's voice loop.

    "hey momo" -> "Yes, Master?" -> you talk -> Momo answers -> (follow-up window: keep talking, no wake word)
                                                              -> silence for FOLLOWUP_SEC -> back to "hey momo"
                                                              -> music command / music playing -> back to "hey momo"

Music never stops because you said "hey momo": it keeps playing, just softer (config.DUCK_RATIO), while Momo
listens and talks, then returns to your volume.

A scheduler thread fires timers, alarms and reminders (tools/clock.py); Momo announces them between turns.

Run via main_ui.py, which owns the window. This loop runs in a background thread and sends UI updates
through `ui_queue`. Everything important is also logged to the terminal.
"""
import queue
import random
import re
import threading
import time

import numpy as np
import sounddevice as sd

import config
from backend import language
from backend.core import respond, warm_up as warm_up_llm
from backend.database import initialize_session
from stt.listen import transcribe_audio_chunk
from tools.clock import pop_due, say_clock
from tools.info import domains as info_domains, refresh_news
from tools.music import player
from tts import speak as voice
from wakeword.detector import WAKEWORD_MODEL_NAME, WAKEWORD_THRESHOLD, owwModel

T = config.USER_TITLE
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1280                      # 80 ms, openWakeWord's native frame size
CHUNK_SEC = CHUNK_SAMPLES / SAMPLE_RATE
TH = config.USER_TITLE_HI
WAKE_REPLIES = [f"Yes, {T}?", f"I'm here, {T}.", f"How can I help, {T}?", f"I'm listening, {T}."]
WAKE_REPLIES_HI = [f"जी, {TH}?", f"बोलिए, {TH}।", f"मैं सुन रही हूँ, {TH}।"]


def L(en: str, hi: str) -> str:
    """The phrase for the current language mode."""
    return hi if language.current() == "hi" else en


def wake_replies():
    return WAKE_REPLIES_HI if language.current() == "hi" else WAKE_REPLIES
MUSIC_TOOLS = {"play_music", "music_control", "manage_playlist"}
# "shut down", "turn yourself off", "close Momo", "band ho jao" (not "shut down the computer" / "turn off the music")
SHUTDOWN_HI = re.compile(r"(?:मोमो\s+)?(?:बंद\s+हो\s+जाओ|शट\s*डाउन|खुद\s+को\s+बंद\s+करो|प्रोग्राम\s+बंद\s+करो)")
END_CONVERSATION_HI = re.compile(r"^(?:बस|बस इतना ही|बाय|अलविदा|कुछ नहीं|ठीक है बस|बस करो|bas|bas itna hi|alvida|"
                                 r"kuch nahi|theek hai bas|bas karo)[।.!]*$", re.I)
SHUTDOWN = re.compile(r"\b(?:shut\s*(?:yourself\s+)?down(?!\s+(?:the\s+|my\s+)?(?:computer|pc|laptop|system|music|song))|"
                      r"turn\s+(?:yourself|momo)\s+off|power\s+(?:yourself\s+)?off|"
                      r"(?:close|quit|exit)\s+(?:yourself|momo|the\s+(?:app|program|application))|"
                      r"band\s+ho\s+jao)\b", re.I)
END_CONVERSATION = re.compile(r"\b(that'?s all|that is all|bye|goodbye|nothing|never ?mind|stop listening|"
                              r"thanks,? that'?s it|that'?s it)\b", re.I)


def log(tag, msg):
    print(f"{time.strftime('%H:%M:%S')} [{tag:<5}] {msg}", flush=True)


def rms(chunk):
    return float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))


def find_mic():
    """Index of the first input device whose name contains config.MIC_NAME."""
    if not config.MIC_NAME:
        return None
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and config.MIC_NAME.lower() in d["name"].lower():
            return i
    log("mic", f"'{config.MIC_NAME}' not found, using the Windows default input")
    return None


def calibrate(device, seconds=2.0):
    """Measure background noise; speech threshold = well above it (adapts to your mic and room)."""
    rec = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16", device=device)
    sd.wait()
    background = rms(rec)
    threshold = max(100.0, background * 2.2)
    status = "silent?! check the mic" if background < 5 else "ok"
    log("mic", f"background {background:.0f} RMS -> speech threshold {threshold:.0f} ({status})")
    return threshold


def announcement(item) -> str:
    if language.current() == "hi":
        return announcement_hi(item)
    return announcement_en(item)


def announcement_hi(item) -> str:
    if item["kind"] == "timer":
        return f"{TH}, आपका {item['label']} का टाइमर पूरा हो गया।"
    if item["kind"] == "alarm":
        return f"{TH}, {item['due'].strftime('%I:%M').lstrip('0')} बज गए हैं। यह आपका अलार्म है।"
    label = item["label"][4:] if (item["label"] or "").startswith("for ") else item["label"]
    if item["late"]:
        return f"{TH}, मेरे बंद रहते आपका एक रिमाइंडर था: {label}।"
    return f"{TH}, आपका रिमाइंडर: {label}।"


def announcement_en(item) -> str:
    if item["kind"] == "timer":
        return f"{T}, your {item['label']} timer is done."
    if item["kind"] == "alarm":
        extra = f" {item['label']}." if item["label"] else ""
        return f"{T}, it's {say_clock(item['due']).replace(' today', '')}. This is your alarm.{extra}"
    if item["late"]:
        return f"{T}, while I was away you had a reminder: {item['label']}."
    if (item["label"] or "").startswith("for "):                  # calendar heads-up
        return f"{T}, a reminder: your {item['label'][4:]}."
    return f"{T}, here's your reminder: {item['label']}."


def main(ui_queue):
    audio_queue = queue.Queue()
    due_queue = queue.Queue()
    session_id = initialize_session()

    def ui(kind, data):
        ui_queue.put({"type": kind, "data": data})

    def flush_audio():
        with audio_queue.mutex:
            audio_queue.queue.clear()

    def say(text):
        log("momo", text)
        ui("anim", "speaking")
        t = time.perf_counter()
        voice.speak(text)
        log("voice", f"spoke in {time.perf_counter() - t:.1f}s")
        ui("anim", "idle")
        time.sleep(0.25)          # let the speaker's echo die out
        flush_audio()             # never treat Momo's own voice as the user

    def watch_music():
        """Tell the UI when music starts/stops (it shows Marin dancing while a song plays)."""
        last = None
        while True:
            playing = player.is_playing()
            if playing != last:
                ui("music", playing)
                last = playing
            time.sleep(1.5)

    def scheduler():
        """Move due timers/alarms/reminders into due_queue; the voice loop announces them.
        Also refreshes the headlines for config.NEWS_TOPICS: the only thing Momo does online on her own
        (read-only, allowlisted hosts; it never sends anything)."""
        next_news = time.time() + 20
        while True:
            if config.NEWS_REFRESH_MIN and time.time() >= next_news:
                next_news = time.time() + config.NEWS_REFRESH_MIN * 60
                try:
                    log("news", f"refreshed {refresh_news()} headlines for {', '.join(info_domains())}")
                except Exception as e:
                    log("error", f"news: {e}")
            try:
                for item in pop_due():
                    log("clock", f"due: {item['kind']} {item['label']!r}")
                    due_queue.put(item)
            except Exception as e:
                log("error", f"scheduler: {e}")
            time.sleep(1)

    def announce_due():
        """Speak everything that fired. Returns True if anything was announced."""
        items = []
        while not due_queue.empty():
            items.append(due_queue.get())
        if not items:
            return False
        ducked = player.duck()
        for item in items:
            text = announcement(item)
            ui("momo_chat", text)
            ui("status", f"{item['kind'].capitalize()}!")
            ui("anim", "speaking")
            voice.beep(3 if item["kind"] == "alarm" else 2)
            say(text)
        if ducked:
            player.unduck()
        flush_audio()
        owwModel.reset()
        return True

    threading.Thread(target=watch_music, daemon=True).start()

    def threshold_now():
        """Speech threshold for this conversation. With music playing (softly) in the room, measure it again
        so the song isn't mistaken for you talking (that kept the mic open for 25 s before)."""
        if not player.is_playing():
            return base_threshold
        time.sleep(0.15)
        flush_audio()
        noise = [rms(audio_queue.get()) for _ in range(5)]          # 0.4 s
        level = max(base_threshold, float(np.median(noise)) * 2.0)
        log("mic", f"music playing: speech threshold {base_threshold:.0f} -> {level:.0f}")
        return level

    def record(start_timeout, threshold, max_sec):
        """Wait up to `start_timeout` s for speech, then record until END_SILENCE_SEC of quiet.
        Returns the audio, or None if nobody spoke."""
        recorded, silent, spoken, waited = [], 0, False, 0
        end_chunks = int(config.END_SILENCE_SEC / CHUNK_SEC)
        start_chunks = int(start_timeout / CHUNK_SEC)
        max_chunks = int(max_sec / CHUNK_SEC)
        while True:
            chunk = audio_queue.get()
            waited += 1
            loud = rms(chunk) > threshold
            if not spoken:
                if loud:
                    spoken = True
                    recorded.append(chunk)
                elif waited >= start_chunks:
                    return None
                continue
            recorded.append(chunk)
            silent = 0 if loud else silent + 1
            if silent >= end_chunks or len(recorded) >= max_chunks:
                return np.concatenate(recorded)

    def handle(text):
        """Answer one request. Returns False when the conversation should end (back to the wake word)."""
        want = language.requested(text)
        if want:
            ui("user_chat", text)
            if want == language.current():
                say(L(f"I'm already speaking English, {T}.", f"मैं पहले से हिंदी में बात कर रही हूँ, {TH}।"))
                return True
            say(L(f"One moment, {T}, switching to Hindi.", f"एक पल, {TH}, इंग्लिश पर जा रही हूँ।"))
            ui("status", "Switching language...")
            language.set_language(want)
            say(L(f"Done, {T}. I'm in English mode now.", f"ठीक है, {TH}। अब मैं हिंदी में बात करूँगी।"))
            return True
        if SHUTDOWN.search(text) or SHUTDOWN_HI.search(text):
            ui("user_chat", text)
            ui("shutdown", "voice")            # the window asks you to confirm; only "Yes" there closes Momo
            say(L(f"Shall I shut down, {T}? Please confirm on my screen.",
                  f"क्या मैं बंद हो जाऊँ, {TH}? कृपया स्क्रीन पर पुष्टि करें।"))
            return False
        if END_CONVERSATION_HI.match(text.strip()):
            ui("user_chat", text)
            say(random.choice([f"ठीक है, {TH}। ज़रूरत हो तो बुला लीजिए।", f"जी, {TH}। मैं यहीं हूँ।"]))
            return False
        if END_CONVERSATION.search(text) and len(text.split()) <= 5:
            ui("user_chat", text)
            say(random.choice([f"Of course, {T}. Call me whenever you need me.", f"Very well, {T}. I'll be right here.",
                               f"Alright, {T}. Just say hey Momo."]))
            return False
        ui("user_chat", text)
        ui("status", "Thinking...")
        ui("anim", "thinking")
        out = respond(text, session_id)
        log("agent", f"heard={out['text']!r} tools={out['tools'] or '-'}")
        ui("momo_chat", out["reply"])
        say(out["reply"])
        if out["reply"].rstrip().endswith("?"):
            return True                       # Momo asked something: keep listening for the answer
        if "run_routine" in out["tools"] and "night" in out["text"].lower():
            return False
        if MUSIC_TOOLS & set(out["tools"]) or player.is_playing():
            # Music command done / music playing: don't keep the mic open (it would hear the song),
            # go straight back to waiting for "hey momo".
            log("listen", "music -> back to waiting for the wake word")
            return False
        return True

    ui("status", "Waking up...")
    log("boot", f"LLM {config.OLLAMA_MODEL} | wake word '{WAKEWORD_MODEL_NAME}' threshold {WAKEWORD_THRESHOLD}")
    log("boot", f"pause to finish: {config.END_SILENCE_SEC}s | time to start: {config.START_TIMEOUT_SEC}s | "
                f"follow-up window: {config.FOLLOWUP_SEC}s | voice {config.VOICE_NAME} (CPU)")
    language.on_change(lambda phase, lang: ui("language", {"phase": phase, "lang": lang}))
    language.set_language(language.saved())          # loads that language's speech model + voice
    language.on_change(lambda phase, lang: phase == "done" and threading.Thread(
        target=voice.warm_up, args=(wake_replies(),), daemon=True).start())
    log("boot", f"language: {language.NAMES[language.current()]}")
    warm_up_llm()
    voice.warm_up(wake_replies())
    threading.Thread(target=scheduler, daemon=True).start()

    device = find_mic()
    log("mic", f"using: {sd.query_devices(device if device is not None else sd.default.device[0])['name']}")
    base_threshold = calibrate(device)

    def audio_callback(indata, frames, time_info, status):
        audio_queue.put(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", device=device,
                        blocksize=CHUNK_SAMPLES, callback=audio_callback):
        ui("status", "Say \"hey Momo\"...")
        log("ready", "Say \"hey Momo\"  (close the window to quit)")
        best, best_t = 0.0, 0.0
        while True:
            # --- 0. timers / alarms / reminders that fired ---
            if not due_queue.empty() and announce_due():
                ui("anim", "idle")
                ui("status", "Say \"hey Momo\"...")

            # --- 1. wait for the wake word ---
            chunk = audio_queue.get()
            score = float(owwModel.predict(chunk.flatten()).get(WAKEWORD_MODEL_NAME, 0))
            if score <= WAKEWORD_THRESHOLD:
                if score >= config.WAKE_LOG_MIN and score > best:
                    best, best_t = score, time.time()
                elif best and time.time() - best_t > 1.0:
                    log("wake", f"near miss: peak score {best:.3f} (needs > {WAKEWORD_THRESHOLD})")
                    best = 0.0
                continue

            log("wake", f"DETECTED 'hey momo' (score {score:.3f})")
            best = 0.0
            owwModel.reset()
            music_on = player.duck()          # keeps playing, softer
            threshold = threshold_now()
            say(random.choice(wake_replies()))

            # --- 2. conversation: keep going while the user keeps talking ---
            timeout, turn = config.START_TIMEOUT_SEC, 0
            while True:
                announce_due()
                ui("status", "Listening..." if turn == 0 else "Still listening... (just talk)")
                ui("anim", "listening")
                log("listen", f"listening (up to {timeout:.0f}s to start)...")
                audio = record(timeout, threshold, 12 if music_on else config.MAX_UTTERANCE_SEC)
                if audio is None:
                    log("listen", "no speech -> back to waiting for the wake word")
                    break
                log("listen", f"got {len(audio) / SAMPLE_RATE:.1f}s of speech")
                try:
                    t = time.perf_counter()
                    text = transcribe_audio_chunk(audio)
                    log("stt", f"\"{text}\" ({time.perf_counter() - t:.1f}s)")
                    if not text:
                        say(L(f"Sorry, {T}, I didn't catch that. Could you say it again?",
                              f"माफ़ कीजिए, {TH}, मैं समझ नहीं पाई। फिर से कहिए?"))
                    elif not handle(text):
                        break
                except Exception as e:
                    log("error", f"{type(e).__name__}: {e}")
                    say(L(f"I'm sorry, {T}, something went wrong. Please try again.",
                          f"माफ़ कीजिए, {TH}, कुछ गड़बड़ हो गई। फिर से कोशिश कीजिए।"))
                timeout, turn = config.FOLLOWUP_SEC, turn + 1
                if player.duck():             # a song started during this turn: soften it while we keep talking
                    music_on = True
                    threshold = threshold_now()

            player.unduck()
            flush_audio()
            owwModel.reset()
            ui("anim", "idle")
            ui("status", "Say \"hey Momo\"...")
            log("ready", "Say \"hey Momo\"")


if __name__ == "__main__":
    print("Run main_ui.py to start Momo.")
