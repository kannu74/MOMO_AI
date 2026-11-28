"""Music playback: yt-dlp finds the song, mpv plays the audio in the background.

Momo talks to mpv over its JSON IPC named pipe, so it can pause, skip, change volume and
duck the music while it is listening or speaking.

Safety: song titles come from the internet. They are stored in the DB for your reference
but are never passed to the LLM; every message returned from here is built locally.
"""
import json
import os
import random
import re
import subprocess
import sys
import threading
import time

import yt_dlp
from rapidfuzz import fuzz, process

import config
from backend.database import connect, now

PIPE = r"\\.\pipe\momo-mpv"
YTDL_PATH = os.path.join(os.path.dirname(sys.executable), "yt-dlp.exe")


def _player_exe(path: str) -> str:
    """mpv.com is only a console launcher that starts mpv.exe as a separate process: killing it left the music
    playing after Momo closed. Start mpv.exe itself."""
    if path.lower().endswith(".com") and os.path.exists(path[:-4] + ".exe"):
        return path[:-4] + ".exe"
    return path


def _quit_pipe():
    """Tell whatever mpv owns Momo's pipe to quit (also one orphaned by an earlier crash)."""
    for _ in range(15):                     # busy for a moment after any other client (even os.path.exists) used it
        try:
            with open(PIPE, "r+b", buffering=0) as pipe:
                pipe.write(json.dumps({"command": ["quit"]}).encode() + b"\n")
            break
        except OSError:
            if not os.path.exists(PIPE):
                return
            time.sleep(0.1)
    else:
        return
    for _ in range(15):
        if not os.path.exists(PIPE):
            return
        time.sleep(0.1)


_job = None


def _die_with_momo(proc):
    """Windows job object with KILL_ON_JOB_CLOSE: when Momo's process ends in any way (window closed, Ctrl+C,
    crash, terminal closed), Windows kills mpv and its yt-dlp helpers too."""
    global _job
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        if _job is None:
            job = k32.CreateJobObjectW(None, None)
            info = Extended()
            info.Basic.LimitFlags = 0x2000                     # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not job or not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise OSError(ctypes.get_last_error())
            _job = job                                     # kept open for Momo's lifetime on purpose
        h = k32.OpenProcess(0x0100 | 0x0001, False, proc.pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        if not h or not k32.AssignProcessToJobObject(_job, h):
            raise OSError(ctypes.get_last_error())
        k32.CloseHandle(h)
    except Exception as e:
        print(f"[music] couldn't tie mpv to Momo's lifetime: {e}")


class Player:
    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        self.req = 0
        self.saved_volume = None

    # --- mpv process + IPC ---
    def _ensure(self):
        if self.proc and self.proc.poll() is None:
            return
        if not os.path.exists(config.MPV_PATH):
            raise RuntimeError(f"mpv not found at {config.MPV_PATH}")
        if self.proc is None and os.path.exists(PIPE):
            _quit_pipe()                                 # an mpv left over from a crashed run: stop it first
        args = [_player_exe(config.MPV_PATH), "--idle=yes", "--no-video", "--force-window=no", "--no-terminal",
                f"--input-ipc-server={PIPE}", f"--volume={config.MUSIC_VOLUME}", "--ytdl-format=bestaudio/best"]
        if os.path.exists(YTDL_PATH):
            args.append(f"--script-opts=ytdl_hook-ytdl_path={YTDL_PATH}")
        self.proc = subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        _die_with_momo(self.proc)
        for _ in range(50):
            if os.path.exists(PIPE):
                return
            time.sleep(0.1)

    def _cmd(self, *command):
        """Send one command to mpv and wait for its reply."""
        with self.lock:
            self._ensure()
            self.req += 1
            rid = self.req
            for _ in range(20):
                try:
                    pipe = open(PIPE, "r+b", buffering=0)
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("could not connect to mpv")
            with pipe:
                pipe.write((json.dumps({"command": list(command), "request_id": rid}) + "\n").encode())
                buf = b""
                while True:
                    chunk = pipe.read(1)
                    if not chunk:
                        return None
                    if chunk != b"\n":
                        buf += chunk
                        continue
                    msg = json.loads(buf or b"{}"); buf = b""
                    if msg.get("request_id") == rid:
                        return msg.get("data")

    def close(self):
        """Stop the music for good (Momo is shutting down): ask mpv to quit, then make sure it's gone."""
        _quit_pipe()
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def is_playing(self) -> bool:
        return self.state() == "playing"

    def state(self) -> str:
        """'playing', 'paused' or 'stopped' (no song loaded)."""
        if not self.running():
            return "stopped"
        try:
            if self._cmd("get_property", "idle-active") is not False:
                return "stopped"
            return "paused" if self._cmd("get_property", "pause") else "playing"
        except Exception:
            return "stopped"

    # --- playback ---
    def play_ids(self, video_ids):
        for i, vid in enumerate(video_ids):
            self._cmd("loadfile", f"https://www.youtube.com/watch?v={vid}", "replace" if i == 0 else "append")
        self._cmd("set_property", "pause", False)

    def current_video_id(self):
        path = self._cmd("get_property", "path") if self.running() else None
        return path.split("v=")[-1][:11] if path and "v=" in path else None

    def _volume(self) -> float:
        # while ducked, "the volume" means the level the user set, not the temporary ducked one
        if self.saved_volume is not None:
            return float(self.saved_volume)
        return float(self._cmd("get_property", "volume") or config.MUSIC_VOLUME)

    def _set_volume(self, vol: float) -> int:
        vol = max(0, min(100, vol))
        if self.saved_volume is not None:      # ducked right now: the new level applies when Momo is done
            self.saved_volume = vol
            self._cmd("set_property", "volume", self._ducked(vol))
        else:
            self._cmd("set_property", "volume", vol)
        return int(vol)

    def control(self, action: str, level: int = -1) -> str:
        if not self.running() or self.state() == "stopped":
            return "Nothing is playing."
        if action == "pause":
            self._cmd("set_property", "pause", True); return "Paused."
        if action == "resume":
            self._cmd("set_property", "pause", False); return "Resumed."
        if action == "stop":
            self._cmd("stop"); return "Stopped the music."
        if action == "next":
            self._cmd("playlist-next", "force"); return "Skipped to the next song."
        if action == "previous":
            self._cmd("playlist-prev", "force"); return "Went back a song."
        if action in ("volume_up", "volume_down"):
            vol = self._set_volume(max(5, self._volume() + (15 if action == "volume_up" else -15)))
            return f"Volume set to {vol} percent."
        if action == "shuffle":
            self._cmd("playlist-shuffle")
            return "Shuffled the songs in the queue."
        if action == "volume_max":
            return f"Volume set to {self._set_volume(100)} percent."
        if action == "set_volume":
            if not 0 <= int(level) <= 100:
                return "What volume should I set? Say a number from 0 to 100."
            return f"Volume set to {self._set_volume(int(level))} percent."
        return "I can't do that with the music."

    # --- ducking while Momo listens / speaks: the music keeps playing, just softer ---
    @staticmethod
    def _ducked(vol):
        return min(vol, max(config.DUCK_MIN, vol * config.DUCK_RATIO))

    def duck(self) -> bool:
        if self.saved_volume is None and self.is_playing():
            self.saved_volume = float(self._cmd("get_property", "volume") or config.MUSIC_VOLUME)
            self._cmd("set_property", "volume", self._ducked(self.saved_volume))
            return True
        return False

    def unduck(self):
        if self.saved_volume is not None and self.running():
            self._cmd("set_property", "volume", self.saved_volume)
        self.saved_volume = None


player = Player()


# --- library helpers ---
MUSIC_WORDS = re.compile(r"\b(song|songs|music|ost|opening|openings|ending|theme|soundtrack|mix|playlist|album|remix|"
                         r"lo-?fi|beats|rap|track|cover|instrumental|by|lyrics|anthem|op|ed|bgm|jukebox|nonstop)\b", re.I)
LONG_OK = re.compile(r"\b(mix|playlist|album|jukebox|nonstop|compilation|top \d+|all|hour|hours|full|ost|openings|"
                     r"endings|songs)\b", re.I)


def music_query(query: str) -> str:
    """Bias YouTube towards music: 'dressing' -> 'dressing song' (it found a fashion video before)."""
    q = query.strip()
    return q if MUSIC_WORDS.search(q) else f"{q} song"


def _recent_ids(n=15) -> set:
    with connect() as conn:
        rows = conn.execute("SELECT t.video_id FROM play_history h JOIN tracks t ON t.id = h.track_id "
                            "ORDER BY h.id DESC LIMIT ?", (n,)).fetchall()
    return {r["video_id"] for r in rows}


def _search(query: str, avoid=()) -> dict:
    """Best YouTube result: a normal song length (unless a mix was asked for) and not in `avoid`.
    Titles are only used locally for ranking; they never reach the LLM."""
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch8:{music_query(query)}", download=False)
    entries = [e for e in (info.get("entries") or []) if e.get("id")]
    if not entries:
        raise LookupError("no results")
    long_ok = bool(LONG_OK.search(query))

    def penalty(i_e):
        i, e = i_e
        dur = int(e.get("duration") or 0)
        p = i                                               # YouTube's own ranking is the base
        if e["id"] in avoid:
            p += 100
        if dur and not long_ok and not 60 <= dur <= 900:    # fight clips, tutorials, 1-hour mixes when a song was asked
            p += 20
        return p

    e = min(enumerate(entries), key=penalty)[1]
    return {"video_id": e["id"], "title": e.get("title"), "duration": int(e.get("duration") or 0)}


def _save_track(t: dict, query: str) -> int:
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO tracks (video_id, title, duration, query, added_at) VALUES (?,?,?,?,?)",
                     (t["video_id"], t.get("title"), t.get("duration"), query, now()))
        return conn.execute("SELECT id FROM tracks WHERE video_id = ?", (t["video_id"],)).fetchone()["id"]


def _log_play(track_ids, source):
    with connect() as conn:
        conn.executemany("INSERT INTO play_history (track_id, source, played_at) VALUES (?,?,?)",
                         [(tid, source, now()) for tid in track_ids])


def _clean_name(name: str) -> str:
    name = (name or "").strip().lower()
    for w in ("my ", "the "):
        if name.startswith(w):
            name = name[len(w):]
    return name.removesuffix(" playlist").strip()


def _find_playlist(name: str):
    with connect() as conn:
        rows = conn.execute("SELECT id, name FROM playlists").fetchall()
    if not rows:
        return None
    names = {r["name"]: r["id"] for r in rows}
    match = process.extractOne(_clean_name(name), list(names), scorer=fuzz.WRatio)
    return (names[match[0]], match[0]) if match and match[1] >= 75 else None


# --- tool implementations (return short, locally built messages) ---
def playlist_names() -> list[str]:
    """Names the user gave their playlists (user text, safe to show the LLM)."""
    with connect() as conn:
        return [r["name"] for r in conn.execute("SELECT name FROM playlists ORDER BY name")]


def play_music(query: str = "", playlist: str = "", shuffle: bool = False, different: bool = False) -> str:
    if playlist:
        found = _find_playlist(playlist)
        if not found:
            return f"There's no playlist called {playlist}."
        pid, pname = found
        with connect() as conn:
            rows = conn.execute("SELECT t.id, t.video_id FROM playlist_tracks pt JOIN tracks t ON t.id = pt.track_id "
                                "WHERE pt.playlist_id = ? ORDER BY pt.position", (pid,)).fetchall()
        if not rows:
            return f"The {pname} playlist is empty."
        rows = list(rows)
        if shuffle:
            random.shuffle(rows)
        player.play_ids([r["video_id"] for r in rows])
        _log_play([r["id"] for r in rows[:1]], f"playlist:{pname}")
        return f"Playing the {pname} playlist, {len(rows)} songs{' shuffled' if shuffle else ''}."
    if not query.strip():
        if different and player.state() != "stopped":     # "play something else"
            return player.control("next")
        if player.state() == "paused":                    # "keep playing"
            return player.control("resume")
        return "What should I play?"
    current = player.current_video_id()
    avoid = (_recent_ids() if different else set()) | ({current} if current else set())
    t = _search(query, avoid)
    tid = _save_track(t, query)
    player.play_ids([t["video_id"]])
    _log_play([tid], "request")
    return f"Playing {'another ' if different else ''}{query}."


def music_control(action: str, level: int = -1) -> str:
    return player.control(action, level)


# "this", "this music", "the song that's playing", "it" ... all mean the song playing right now.
# (Before, "add this music to anime" searched YouTube for "this music" and added a random video.)
_DEICTIC_WORDS = {"this", "that", "it", "the", "current", "currently", "song", "music", "track", "tune", "one",
                  "playing", "now", "right", "here", "which", "is", "that's", "thats", "you", "are", "you're",
                  "being", "played", "title", "video", "a", "same", "present"}


def refers_to_current(song: str) -> bool:
    words = re.findall(r"[a-z']+", (song or "").lower())
    return not words or all(w in _DEICTIC_WORDS for w in words)


def manage_playlist(action: str, name: str = "", song: str = "") -> str:
    clean = _clean_name(name)
    if refers_to_current(song):
        song = ""
    if action == "list" and not clean:
        with connect() as conn:
            rows = conn.execute("SELECT p.name, COUNT(pt.track_id) n FROM playlists p LEFT JOIN playlist_tracks pt "
                                "ON pt.playlist_id = p.id GROUP BY p.id ORDER BY p.name").fetchall()
        return ("Your playlists: " + ", ".join(f"{r['name']} with {r['n']} song{'s' if r['n'] != 1 else ''}" for r in rows)) if rows else "You have no playlists yet."
    if not clean:
        return "Which playlist?"
    if action == "create":
        with connect() as conn:
            conn.execute("INSERT OR IGNORE INTO playlists (name, created_at) VALUES (?, ?)", (clean, now()))
        return f"Created the {clean} playlist."

    found = _find_playlist(clean)
    if action == "add" and not found:            # adding to a new name creates it
        manage_playlist("create", clean)
        found = _find_playlist(clean)
    if not found:
        return f"There's no playlist called {clean}."
    pid, pname = found

    if action == "delete":
        with connect() as conn:
            conn.execute("DELETE FROM playlists WHERE id = ?", (pid,))
        return f"Deleted the {pname} playlist."

    if action in ("songs", "list"):                    # "what's in my chill playlist"
        rows = _playlist_rows(pid)
        if not rows:
            return f"The {pname} playlist is empty."
        shown = rows[:SONGS_SPOKEN]
        more = f" And {len(rows) - len(shown)} more." if len(rows) > len(shown) else ""
        return (f"The {pname} playlist has {len(rows)} song{'s' if len(rows) != 1 else ''}: "
                + " ".join(f"{i}, {_label(r)}." for i, r in enumerate(shown, 1)) + more)

    if action == "shuffle":                            # "shuffle my chill playlist"
        return play_music(playlist=pname, shuffle=True)

    if action == "add":
        if song.strip():
            t = _search(song); tid = _save_track(t, song)
        else:
            vid = player.current_video_id()
            if not vid:
                return "Nothing is playing, so tell me which song to add."
            with connect() as conn:
                row = conn.execute("SELECT id FROM tracks WHERE video_id = ?", (vid,)).fetchone()
            tid = row["id"] if row else _save_track({"video_id": vid}, "")
        with connect() as conn:
            pos = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM playlist_tracks WHERE playlist_id = ?", (pid,)).fetchone()[0]
            cur = conn.execute("INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id, position) VALUES (?,?,?)", (pid, tid, pos))
        return f"Added it to {pname}." if cur.rowcount else f"That song is already in {pname}."

    if action == "remove":
        vid = None
        rows = _playlist_rows(pid)
        n = _song_number(song, len(rows))
        if n:                                          # "remove song 3 from chill" (numbers from the songs list)
            r = rows[n - 1]
            with connect() as conn:
                conn.execute("DELETE FROM playlist_tracks WHERE playlist_id = ? AND track_id = ?", (pid, r["id"]))
            return f"Removed song {n}, {_label(r)}, from {pname}."
        if song.strip() and re.fullmatch(r"(?:song\s+|number\s+|track\s+)?\d+", song.strip(), re.I):
            return f"{pname} only has {len(rows)} song{'s' if len(rows) != 1 else ''}."
        if song.strip():
            with connect() as conn:
                rows = conn.execute("SELECT t.id, t.query, t.title FROM playlist_tracks pt JOIN tracks t ON t.id = pt.track_id "
                                    "WHERE pt.playlist_id = ?", (pid,)).fetchall()
            choices = {r["id"]: f"{r['query'] or ''} {r['title'] or ''}" for r in rows}
            m = process.extractOne(song, choices, scorer=fuzz.WRatio)
            tid = m[2] if m and m[1] >= 60 else None
        else:
            vid = player.current_video_id()
            with connect() as conn:
                row = conn.execute("SELECT id FROM tracks WHERE video_id = ?", (vid,)).fetchone() if vid else None
            tid = row["id"] if row else None
        if not tid:
            return f"I couldn't find that song in {pname}."
        with connect() as conn:
            conn.execute("DELETE FROM playlist_tracks WHERE playlist_id = ? AND track_id = ?", (pid, tid))
        return f"Removed it from {pname}."
    return "I can't do that with playlists."


SONGS_SPOKEN = 10
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
             "ninth": 9, "tenth": 10, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10}


def _playlist_rows(pid):
    with connect() as conn:
        return conn.execute("SELECT t.id, t.video_id, t.query, t.title FROM playlist_tracks pt "
                            "JOIN tracks t ON t.id = pt.track_id WHERE pt.playlist_id = ? ORDER BY pt.position",
                            (pid,)).fetchall()


def _label(row) -> str:
    """How a saved song is spoken: your own words when you asked for it ("Loser by Tame Impala"); otherwise the
    YouTube title, cleaned by the security extractor (it's web text)."""
    q = re.sub(r"\s+hindi song$", "", (row["query"] or "").strip(), flags=re.I)
    if q and not refers_to_current(q):
        return q
    from security.extractor import headline
    return headline(row["title"] or "", 80) or "a song without a name"


def _song_number(song: str, count: int) -> int:
    """'3' / 'song 3' / 'number three' / 'the second one' / 'the last song' -> position (1-based), or 0."""
    s = (song or "").lower().strip()
    m = re.fullmatch(r"(?:the\s+)?(?:song\s+|number\s+|track\s+|no\.?\s*)?(\d+|\w+)(?:st|nd|rd|th)?"
                     r"(?:\s+(?:one|song|track))?", s)
    if not m:
        return 0
    w = m[1]
    n = count if w == "last" else int(w) if w.isdigit() else _ORDINALS.get(w, 0)
    return n if 1 <= n <= count else 0


def now_playing():
    """(title, seconds played) of the current song for the window, or (None, 0)."""
    try:
        if player.state() == "stopped":
            return None, 0.0
        return player._cmd("get_property", "media-title"), float(player._cmd("get_property", "time-pos") or 0)
    except Exception:
        return None, 0.0
