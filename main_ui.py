"""Momo's window: avatar animation, status and chat log. Start Momo with `python main_ui.py`.

Avatar GIFs live in `assets/`:
  idle.gif, listening.gif, thinking.gif, speaking.gif   - one per activity (required: idle.gif)
  dance_*.gif                                           - shown (rotating) while music plays and Momo is idle;
                                                          fitted, not cropped, so the party colours show around it
Any size works; frames are scaled/cropped to fill the avatar box and play at the GIF's own frame timing.

Email approval: this window is the ONLY place an email can be sent from. When Momo drafts one, a dialog shows
To / Subject / Body; it is sent only when you click "Approve & send" with the mouse (keyboard and voice can't
press it; optional PIN via EMAIL_APPROVAL_PIN). See security/outbox.py.
"""
import colorsys
import glob
import os
import re
import time
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext

from PIL import Image, ImageTk

import config
from security import outbox

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "assets")

AVATAR_W, AVATAR_H, BORDER = 340, 290, 3
BG, PANEL, TEXT, MUTED = "#16131c", "#211d29", "#ece8f1", "#9a93a8"
USER_COLOR, MOMO_COLOR = "#8ecae6", "#ff8fab"
FONT = "Segoe UI"
WARN = "#ffb703"
APPROVE_DELAY_MS = 2000    # the Approve button wakes up after 2 s, so a stray click can't send
ACCENT = "#ff8fab"         # avatar frame colour
ACTIVITIES = ("idle", "listening", "thinking", "speaking")
DANCE_SECONDS = 9          # switch to the next dance GIF after about this long
PARTY_STEP_MS = 60         # background colour cycle speed
PARTY_HUE_STEP = 0.006


def load_frames(path, fit="cover"):
    """GIF -> list of (PhotoImage, duration_ms). fit="cover" fills the avatar box (cropping),
    fit="contain" scales the whole picture inside it (the canvas colour shows around it)."""
    gif, frames = Image.open(path), []
    for i in range(getattr(gif, "n_frames", 1)):
        gif.seek(i)
        fr = gif.convert("RGB")
        pick = max if fit == "cover" else min
        s = pick(AVATAR_W / fr.width, AVATAR_H / fr.height)
        if s != 1:
            fr = fr.resize((round(fr.width * s), round(fr.height * s)), Image.LANCZOS)
        if fit == "cover":
            left, top = (fr.width - AVATAR_W) // 2, int((fr.height - AVATAR_H) * 0.3)  # keep faces in view
            fr = fr.crop((left, top, left + AVATAR_W, top + AVATAR_H))
        frames.append((ImageTk.PhotoImage(fr), max(20, gif.info.get("duration", 100) or 100)))
    return frames


def hsv_hex(h, s, v):
    return "#%02x%02x%02x" % tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h % 1, s, v))


class ApprovalDialog:
    """One email draft waiting for the human. Sends only on a mouse click on Approve."""

    def __init__(self, app, draft):
        self.app, self.d = app, dict(draft)
        self.hash = outbox.content_hash(self.d)          # exactly what is displayed below
        w = self.win = tk.Toplevel(app.root, bg=BG, padx=16, pady=14)
        w.title("Momo - approve this email?")
        w.attributes("-topmost", True)
        w.protocol("WM_DELETE_WINDOW", lambda: None)       # decide with a button, not by closing
        w.geometry("520x520")

        tk.Label(w, text="Momo wrote this email. It is sent ONLY if you approve it.", fg=TEXT, bg=BG,
                 font=(FONT, 11, "bold")).pack(anchor="w")
        meta = tk.Frame(w, bg=BG)
        meta.pack(fill=tk.X, pady=(10, 6))
        for row, (k, v) in enumerate((("To", f"{self.d['to_name']}  <{self.d['to_addr']}>"),
                                      ("Subject", self.d["subject"]))):
            tk.Label(meta, text=k, fg=MUTED, bg=BG, font=(FONT, 10)).grid(row=row, column=0, sticky="nw", padx=(0, 10))
            tk.Label(meta, text=v, fg=TEXT, bg=BG, font=(FONT, 10, "bold"), wraplength=420, justify=tk.LEFT
                     ).grid(row=row, column=1, sticky="w")
        body = scrolledtext.ScrolledText(w, wrap=tk.WORD, height=12, bg=PANEL, fg=TEXT, relief=tk.FLAT,
                                         font=(FONT, 10), padx=8, pady=6)
        body.insert(tk.END, self.d["body"])
        body.config(state=tk.DISABLED)
        body.pack(fill=tk.BOTH, expand=True)

        warnings = []
        if self.d.get("tainted"):
            warnings.append("Contains text taken from the web. Read it before sending.")
        links = re.findall(r"https?://[^\s/]+|www\.[^\s/]+|[\w.+-]+@[\w-]+\.[\w.]+", self.d["body"])
        if links:
            warnings.append("Contains links or addresses: " + ", ".join(sorted(set(links)))[:200])
        for text in warnings:
            tk.Label(w, text="!  " + text, fg=WARN, bg=BG, font=(FONT, 9, "bold"), wraplength=480,
                     justify=tk.LEFT).pack(anchor="w", pady=(6, 0))

        self.pin = None
        if config.EMAIL_APPROVAL_PIN:
            row = tk.Frame(w, bg=BG)
            row.pack(anchor="w", pady=(8, 0))
            tk.Label(row, text="PIN", fg=MUTED, bg=BG, font=(FONT, 10)).pack(side=tk.LEFT, padx=(0, 8))
            self.pin = tk.Entry(row, show="*", width=12, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT)
            self.pin.pack(side=tk.LEFT)

        self.status = tk.Label(w, text="", fg=MUTED, bg=BG, font=(FONT, 9, "italic"))
        self.status.pack(anchor="w", pady=(8, 0))
        buttons = tk.Frame(w, bg=BG)
        buttons.pack(fill=tk.X, pady=(8, 0))
        # Mouse-only buttons: takefocus=0 + a click binding instead of `command`, so Enter/Space can't press them.
        self.approve_btn = tk.Button(buttons, text="Approve & send", state=tk.DISABLED, takefocus=0,
                                     bg="#2a9d8f", fg="white", relief=tk.FLAT, padx=14, pady=6, font=(FONT, 10, "bold"))
        self.approve_btn.pack(side=tk.RIGHT)
        self.reject_btn = tk.Button(buttons, text="Reject", takefocus=0, bg=PANEL, fg=TEXT, relief=tk.FLAT,
                                    padx=14, pady=6, font=(FONT, 10))
        self.reject_btn.pack(side=tk.RIGHT, padx=(0, 8))
        self.reject_btn.bind("<ButtonRelease-1>", lambda e: self.reject())
        w.after(APPROVE_DELAY_MS, self.arm)
        w.after(1000, self.watch)
        w.bell()

    def arm(self):
        if self.win.winfo_exists():
            self.approve_btn.config(state=tk.NORMAL)
            self.approve_btn.bind("<ButtonRelease-1>", lambda e: self.approve())

    def approve(self):
        self.approve_btn.unbind("<ButtonRelease-1>")
        self.approve_btn.config(state=tk.DISABLED)
        self.reject_btn.config(state=tk.DISABLED)
        self.status.config(text="Sending...")
        pin = self.pin.get() if self.pin else ""

        def work():
            ok, msg = outbox.approve(self.d["id"], self.app.approver, self.hash, pin)
            self.app.root.after(0, lambda: self.finish(ok, msg))
        threading.Thread(target=work, daemon=True).start()

    def finish(self, ok, msg):
        self.app.add_chat("Momo", msg)
        if ok or outbox.status(self.d["id"]) != "pending":
            self.close()
        else:                                                   # e.g. wrong PIN / SMTP not set up: try again
            self.status.config(text=msg, fg=WARN)
            self.reject_btn.config(state=tk.NORMAL)
            self.arm()

    def reject(self):
        self.app.add_chat("Momo", outbox.reject(self.d["id"], self.app.approver))
        self.close()

    def watch(self):
        """Close if the draft was cancelled by voice or expired."""
        if not self.win.winfo_exists():
            return
        st = outbox.status(self.d["id"])
        if st in ("rejected", "expired", "gone"):
            self.app.add_chat("Momo", f"Email to {self.d['to_name']} {'expired' if st == 'expired' else 'discarded'}.")
            self.close()
        else:
            self.win.after(1000, self.watch)

    def close(self):
        if self.win.winfo_exists():
            self.win.destroy()


class LyricsWindow:
    """Lyrics of the playing song (tools/lyrics.py, LRCLIB). Follows song changes; synced lyrics highlight and
    scroll to the line being sung. Display only: lyrics never reach the LLM."""

    def __init__(self, root):
        self.win = tk.Toplevel(root, bg=BG)
        self.win.title("Lyrics")
        self.win.geometry(f"420x560+{root.winfo_rootx() + root.winfo_width() + 8}+{root.winfo_rooty()}")
        self.head = tk.Label(self.win, text="Looking for the song...", fg=TEXT, bg=BG, font=(FONT, 12, "bold"),
                             wraplength=390, justify=tk.LEFT, anchor="w")
        self.head.pack(fill=tk.X, padx=14, pady=(12, 6))
        self.text = scrolledtext.ScrolledText(self.win, wrap=tk.WORD, bg=PANEL, fg=MUTED, relief=tk.FLAT,
                                              borderwidth=0, padx=12, pady=10, font=(FONT, 11))
        self.text.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
        self.text.tag_config("now", foreground=ACCENT, font=(FONT, 12, "bold"))
        self.text.tag_config("line", spacing3=4)
        self.text.configure(state=tk.DISABLED)
        self.state = {"title": None, "pos": 0.0, "lyrics": None, "shown": None, "searching": False}
        self.line = -1
        self.alive = True
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self._poll, daemon=True).start()
        self._tick()

    def close(self):
        self.alive = False
        self.win.destroy()

    def _poll(self):                                    # background: ask mpv + LRCLIB without freezing the window
        from tools import lyrics, music
        while self.alive:
            title, pos = music.now_playing()
            self.state["pos"] = pos
            if title != self.state["title"]:
                self.state.update(title=title, lyrics=None, searching=bool(title))
                if title:
                    found = lyrics.find(title)
                    if self.state["title"] == title:
                        self.state.update(lyrics=found, searching=False)
            time.sleep(0.4)

    def _set_text(self, lines):
        self.text.configure(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        for ln in lines:
            self.text.insert(tk.END, (ln or " ") + "\n", "line")
        self.text.configure(state=tk.DISABLED)

    def _tick(self):
        if not self.alive or not self.win.winfo_exists():
            return
        s = self.state
        key = (s["title"], s["searching"], id(s["lyrics"]))
        if key != s["shown"]:
            s["shown"], self.line = key, -1
            if not s["title"]:
                self.head.config(text="Nothing is playing")
                self._set_text(["Play a song and its lyrics show up here."])
            elif s["searching"]:
                self.head.config(text=s["title"])
                self._set_text(["Looking for lyrics..."])
            elif not s["lyrics"]:
                self.head.config(text=s["title"])
                self._set_text(["No lyrics found for this song."])
            else:
                lyr = s["lyrics"]
                self.head.config(text=lyr["title"] or s["title"])
                self._set_text([t for _, t in lyr["synced"]] if lyr["synced"] else lyr["plain"].splitlines())
        lyr = s["lyrics"]
        if lyr and lyr["synced"] and not s["searching"]:
            idx = max((i for i, (t, _) in enumerate(lyr["synced"]) if t <= s["pos"] + 0.3), default=-1)
            if idx != self.line:
                self.line = idx
                self.text.tag_remove("now", "1.0", tk.END)
                if idx >= 0:
                    self.text.tag_add("now", f"{idx + 1}.0", f"{idx + 1}.end")
                    self.text.see(f"{min(idx + 5, len(lyr['synced']))}.0")
                    self.text.see(f"{max(idx - 3, 1)}.0")
        self.win.after(250, self._tick)


class MomoApp:
    def __init__(self, root, ui_queue):
        self.root, self.ui_queue = root, ui_queue
        root.title("Momo")
        root.geometry(f"{AVATAR_W + 60}x660")
        root.minsize(AVATAR_W + 40, 560)
        root.configure(bg=BG)

        # --- header ---
        self.header = tk.Frame(root, bg=BG)
        self.header.pack(fill=tk.X, padx=20, pady=(14, 6))
        self.title_label = tk.Label(self.header, text="Momo", fg=TEXT, bg=BG, font=(FONT, 18, "bold"))
        self.title_label.pack(side=tk.LEFT)
        self.power_btn = tk.Button(self.header, text="⏻  Shut down", command=self.ask_shutdown, bg=PANEL, fg=TEXT,
                                   activebackground="#e63946", activeforeground="white", relief=tk.FLAT, padx=10,
                                   pady=2, font=(FONT, 9), cursor="hand2")
        self.power_btn.pack(side=tk.RIGHT)
        self.lyrics_btn = tk.Button(self.header, text="♪ Lyrics", command=self.show_lyrics, bg=PANEL, fg=TEXT,
                                    activebackground=ACCENT, relief=tk.FLAT, padx=8, pady=2, font=(FONT, 9),
                                    cursor="hand2")
        self.lyrics_btn.pack(side=tk.RIGHT, padx=(0, 8))
        self.lyrics_win = None

        # --- language switch: EN (English only) | हिंदी (Hindi + Hinglish) ---
        self.lang_box = tk.Frame(self.header, bg=BG)
        self.lang_box.pack(side=tk.RIGHT, padx=(0, 10))
        self.lang_btns = {}
        for code, label in (("en", "EN"), ("hi", "हिंदी")):
            b = tk.Button(self.lang_box, text=label, bg=PANEL, fg=MUTED, relief=tk.FLAT, padx=8, pady=2,
                          font=(FONT, 9, "bold"), cursor="hand2", command=lambda c=code: self.pick_language(c))
            b.pack(side=tk.LEFT, padx=1)
            self.lang_btns[code] = b
        self.lang = None
        root.protocol("WM_DELETE_WINDOW", self.shutdown)        # closing the window shuts Momo down cleanly
        self.asking = False

        # --- avatar ---
        self.frame_box = tk.Frame(root, bg=ACCENT, padx=BORDER, pady=BORDER)
        self.frame_box.pack(pady=(4, 8))
        self.canvas = tk.Canvas(self.frame_box, width=AVATAR_W, height=AVATAR_H, bg=PANEL, highlightthickness=0)
        self.canvas.pack()

        self.status_label = tk.Label(root, text="Starting...", fg=MUTED, bg=BG, font=(FONT, 10, "italic"))
        self.status_label.pack()

        # --- running timers / alarms / reminders (live countdown, x to cancel) ---
        self.timer_box = tk.Frame(root, bg=BG)
        self.timer_box.pack(fill=tk.X, padx=16, pady=(6, 0))
        self.timer_rows = {}

        # --- chat log ---
        self.chat_log = scrolledtext.ScrolledText(
            root, wrap=tk.WORD, height=8, state=tk.DISABLED, bg=PANEL, fg=TEXT, insertbackground=TEXT,
            relief=tk.FLAT, borderwidth=0, padx=10, pady=8, font=(FONT, 10))
        self.chat_log.pack(padx=16, pady=(8, 16), fill=tk.BOTH, expand=True)
        self.chat_log.tag_config("user_name", foreground=USER_COLOR, font=(FONT, 10, "bold"))
        self.chat_log.tag_config("momo_name", foreground=MOMO_COLOR, font=(FONT, 10, "bold"))
        self.chat_log.tag_config("msg", spacing3=6)

        # --- animations ---
        self.animations = {}
        for name in ACTIVITIES:
            path = os.path.join(ASSETS, f"{name}.gif")
            if os.path.exists(path):
                try:
                    self.animations[name] = load_frames(path)
                except Exception as e:  # a broken GIF shouldn't stop Momo
                    print(f"[ui] could not load {name}.gif: {e}")
        if "idle" not in self.animations:
            raise FileNotFoundError(f"missing {os.path.join(ASSETS, 'idle.gif')}")
        self.dances = []
        for path in sorted(glob.glob(os.path.join(ASSETS, "dance_*.gif"))):
            try:
                self.dances.append(load_frames(path, fit="contain"))
            except Exception as e:
                print(f"[ui] could not load {os.path.basename(path)}: {e}")

        self.current, self.frame = "idle", 0
        self.playing = None
        self.music, self.dance_idx, self.dance_since, self.hue = False, 0, 0.0, 0.0
        self.image = self.canvas.create_image(AVATAR_W // 2, AVATAR_H // 2, anchor=tk.CENTER,
                                              image=self.animations["idle"][0][0])

        # the window is the only email approver (security/outbox.py)
        self.approver = outbox.register_approver(lambda d: ui_queue.put({"type": "approval", "data": d}))

        self.tick()
        self.root.after(50, self.process_queue)
        self.root.after(500, self.refresh_timers)

    def dancing(self):
        return self.music and self.current == "idle" and bool(self.dances)

    def frames(self):
        """Which animation to show: dance while music plays and Momo is idle, otherwise the activity
        (falls back to idle)."""
        if self.dancing():
            return self.dances[self.dance_idx % len(self.dances)]
        return self.animations.get(self.current, self.animations["idle"])

    def tick(self):
        frames = self.frames()
        if frames is not self.playing:          # animation changed -> restart it from the first frame
            self.playing, self.frame = frames, 0
            self.dance_since = time.monotonic()
        else:
            self.frame = (self.frame + 1) % len(frames)
            # rotate to the next dance at the end of a loop once this one has played long enough
            if (self.frame == 0 and self.dancing() and len(self.dances) > 1
                    and time.monotonic() - self.dance_since >= DANCE_SECONDS):
                self.dance_idx += 1
                self.playing, self.dance_since = self.dances[self.dance_idx % len(self.dances)], time.monotonic()
                frames = self.playing
        photo, duration = frames[self.frame]
        self.canvas.itemconfig(self.image, image=photo)
        self.root.after(duration, self.tick)

    # --- party mode: colours cycle while music plays ---
    def set_music(self, on):
        if on == self.music:
            return
        self.music = on
        if on:
            self.dance_idx += 1                 # a different dance each time a song starts
            self.party()
        else:
            self.paint(BG, PANEL, ACCENT)

    def party(self):
        if not self.music:
            return
        self.hue = (self.hue + PARTY_HUE_STEP) % 1
        self.paint(hsv_hex(self.hue, 0.75, 0.30),           # window: dark so text stays readable
                   hsv_hex(self.hue + 0.5, 0.65, 0.55),     # behind the dancer: complementary colour
                   hsv_hex(self.hue + 0.25, 0.9, 1.0))      # neon border
        self.root.after(PARTY_STEP_MS, self.party)

    def paint(self, bg, stage, border):
        for w in (self.root, self.header, self.title_label, self.status_label):
            w.config(bg=bg)
        self.canvas.config(bg=stage)
        self.frame_box.config(bg=border)

    # --- language ---
    def pick_language(self, code):
        if code == self.lang:
            return
        from backend import language
        self.status_label.config(text="Switching language...")
        threading.Thread(target=language.set_language, args=(code,), daemon=True).start()

    def show_language(self, phase, code):
        if phase == "switching":
            self.status_label.config(text=f"Loading {'Hindi' if code == 'hi' else 'English'} model...")
            return
        self.lang = code
        for c, b in self.lang_btns.items():
            b.config(bg=ACCENT if c == code else PANEL, fg=BG if c == code else MUTED)
        self.status_label.config(text="Say \"hey Momo\"...")
        self.add_chat("Momo", "Language: हिंदी" if code == "hi" else "Language: English")

    # --- timers panel ---
    def refresh_timers(self):
        try:
            from tools.clock import pending_items
            items = pending_items(5)
        except Exception:
            items = []
        now = time.time()
        seen = set()
        for it in items:
            seen.add(it["id"])
            row = self.timer_rows.get(it["id"])
            if row is None:
                row = tk.Frame(self.timer_box, bg=PANEL, padx=8, pady=3)
                row.pack(fill=tk.X, pady=1)
                icon = {"timer": "⏱", "alarm": "⏰", "reminder": "🔔"}[it["kind"]]
                name = it["label"] if it["kind"] != "alarm" else (it["label"] or "Alarm")
                if it["kind"] == "timer":
                    name = f"{name} timer"
                tk.Label(row, text=f"{icon}  {name[:34]}", fg=TEXT, bg=PANEL, font=(FONT, 9)).pack(side=tk.LEFT)
                x = tk.Label(row, text="✕", fg=MUTED, bg=PANEL, font=(FONT, 9), cursor="hand2")
                x.pack(side=tk.RIGHT, padx=(8, 0))
                x.bind("<Button-1>", lambda e, i=it["id"]: self.cancel_timer(i))
                row.value = tk.Label(row, text="", fg=MOMO_COLOR, bg=PANEL, font=("Consolas", 10, "bold"))
                row.value.pack(side=tk.RIGHT)
                self.timer_rows[it["id"]] = row
            left = it["due"].timestamp() - now
            if it["kind"] == "timer" or 0 <= left < 3600:
                h, rem = divmod(max(0, int(left)), 3600)
                m, sec = divmod(rem, 60)
                row.value.config(text=f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}")
            else:
                d = it["due"]
                day = "" if d.date() == datetime.now().date() else (
                    "tomorrow " if (d.date() - datetime.now().date()).days == 1 else d.strftime("%a %d %b "))
                row.value.config(text=day + d.strftime("%I:%M %p").lstrip("0"))
        for i in [i for i in self.timer_rows if i not in seen]:
            self.timer_rows.pop(i).destroy()
        self.root.after(1000, self.refresh_timers)

    def cancel_timer(self, item_id):
        from tools.clock import cancel_id
        cancel_id(item_id)
        self.refresh_timers_now = True

    # --- shut down (button, window close, or "Momo, shut down" -> confirm here) ---
    def show_lyrics(self):
        if self.lyrics_win and self.lyrics_win.alive and self.lyrics_win.win.winfo_exists():
            self.lyrics_win.win.lift()
        else:
            self.lyrics_win = LyricsWindow(self.root)

    def ask_shutdown(self):
        if self.asking:
            return
        self.asking = True
        self.root.attributes("-topmost", True)
        yes = messagebox.askyesno("Shut down Momo?", "Shut down Momo completely?\n\nMusic stops and the program closes.",
                                  parent=self.root, icon="warning", default="no")
        self.root.attributes("-topmost", False)
        self.asking = False
        if yes:
            self.shutdown()
        else:
            self.add_chat("Momo", "Alright, I'll stay.")

    def shutdown(self):
        """Stop the music player and close every part of Momo (voice loop, scheduler, window)."""
        print("[ui] shutting down", flush=True)
        try:
            from tools.music import player
            player.close()
        except Exception as e:
            print(f"[ui] music stop failed: {e}")
        try:
            self.root.destroy()
        finally:
            os._exit(0)                       # the voice loop and scheduler are daemon threads blocked on audio

    def add_chat(self, who, text):
        tag = "user_name" if who == "You" else "momo_name"
        self.chat_log.config(state=tk.NORMAL)
        self.chat_log.insert(tk.END, f"{who}  ", tag)
        self.chat_log.insert(tk.END, text + "\n", "msg")
        self.chat_log.config(state=tk.DISABLED)
        self.chat_log.see(tk.END)

    def process_queue(self):
        try:
            while True:
                msg = self.ui_queue.get_nowait()
                kind, data = msg["type"], msg["data"]
                if kind == "status":
                    self.status_label.config(text=data)
                elif kind == "anim":
                    self.current = data
                elif kind == "music":
                    self.set_music(bool(data))
                elif kind == "user_chat":
                    self.add_chat("You", data)
                elif kind == "momo_chat":
                    self.add_chat("Momo", data)
                elif kind == "approval":
                    ApprovalDialog(self, data)
                elif kind == "shutdown":
                    self.ask_shutdown()
                elif kind == "language":
                    self.show_language(data["phase"], data["lang"])
        except queue.Empty:
            pass
        self.root.after(50, self.process_queue)


if __name__ == "__main__":
    import sys

    if sys.stdout is None:                      # started by pythonw (auto-start at login): no console, log to a file
        os.makedirs(os.path.join(config.ROOT, "data"), exist_ok=True)
        sys.stdout = sys.stderr = open(os.path.join(config.ROOT, "data", "momo.log"), "a", encoding="utf-8",
                                       buffering=1)
        print(f"\n===== Momo started {datetime.now():%Y-%m-%d %H:%M:%S} =====", flush=True)
    q = queue.Queue()
    if "--demo" in sys.argv:                    # preview the window without loading any models
        import itertools

        steps = itertools.cycle([("anim", a) for a in ACTIVITIES] +
                                [("anim", "idle")] +
                                [("music", True)] * 8 + [("anim", "speaking"), ("anim", "idle")] +
                                [("music", True)] * 4 + [("music", False)])

        def demo():
            kind, data = next(steps)
            q.put({"type": kind, "data": data})
            q.put({"type": "status", "data": f"demo: {kind} = {data}"})
            root.after(2500, demo)
    else:
        from main import main as momo_main
        threading.Thread(target=momo_main, args=(q,), daemon=True).start()

    root = tk.Tk()
    MomoApp(root, q)
    if "--demo" in sys.argv:
        q.put({"type": "user_chat", "data": "Hey Momo, what's the weather?"})
        q.put({"type": "momo_chat", "data": "It's sunny and twenty-six degrees in Bengaluru, Master."})
        root.after(500, demo)
    root.mainloop()
