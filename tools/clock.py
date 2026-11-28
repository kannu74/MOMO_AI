"""Time, timers, alarms and reminders (Tier 0: local only).

Everything is stored in the `reminders` table (UTC timestamps), so pending items survive a restart.
`main.py` runs a scheduler thread that calls `pop_due()` and announces what fired.
Durations and clock times are parsed here, locally ("five minutes", "an hour and a half", "7:30 pm", "seven thirty").
"""
import re
from datetime import datetime, time as dtime, timedelta, timezone

from backend.database import connect, now
from .dates import parse_day, say_day

# ---------------------------------------------------------------- number words
_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                     "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_NUM_WORD = "|".join(sorted([*_UNITS, *_TENS, "a", "an", "couple", "few"], key=len, reverse=True))


def words_to_numbers(text: str) -> str:
    """'twenty five minutes' -> '25 minutes', 'a minute' -> '1 minute' (small numbers only, enough for speech)."""
    t = text.lower()
    t = re.sub(r"\b(" + "|".join(_TENS) + r")[\s-]+(" + "|".join(list(_UNITS)[1:10]) + r")\b",
               lambda m: str(_TENS[m[1]] + _UNITS[m[2]]), t)
    t = re.sub(r"\b(" + "|".join(_TENS) + r")\b", lambda m: str(_TENS[m[1]]), t)
    t = re.sub(r"\b(" + "|".join(_UNITS) + r")\b", lambda m: str(_UNITS[m[1]]), t)
    t = re.sub(r"\b(a couple of|a couple|couple of)\b", "2", t)
    t = re.sub(r"\ba few\b", "3", t)
    t = re.sub(r"\b(a|an)\s+(?=(hour|minute|min|second|sec)s?\b)", "1 ", t)
    return t


# ---------------------------------------------------------------- durations
_UNIT_SEC = {"h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
             "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
             "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1}
_DUR = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b(\s+and\s+a\s+half)?")


def parse_duration(text: str) -> int:
    """Seconds in phrases like '5 minutes', 'an hour and a half', '1 hour 20 minutes', 'half an hour'. 0 if none."""
    t, total = text.lower(), 0.0
    for phrase, sec in ((r"\bhalf an? hour\b", 1800), (r"\b(a )?quarter (of an? )?hour\b", 900),
                        (r"\bhalf a minute\b", 30)):
        if re.search(phrase, t):
            total += sec
            t = re.sub(phrase, " ", t)
    t = words_to_numbers(t)
    for num, unit, half in _DUR.findall(t):
        sec = _UNIT_SEC[unit]
        total += (float(num) + (0.5 if half else 0)) * sec
    return int(round(total))


def say_duration(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    parts = [f"{v} {name}{'s' if v != 1 else ''}" for v, name in ((h, "hour"), (m, "minute"), (s, "second")) if v]
    return " and ".join(parts) if parts else "0 seconds"


# ---------------------------------------------------------------- clock times
_CLOCK = re.compile(r"\b(\d{1,2})(?:[:.\s](\d{2}))?\s*(a\.?m\.?|p\.?m\.?|in the morning|in the evening|at night|"
                    r"in the afternoon|tonight)?\b")


def parse_clock(text: str, day: str = "", prefer_morning: bool = False) -> datetime | None:
    """Next local datetime for '7', '7:30', '7:30 pm', '19:00', 'seven thirty am', 'noon', 'midnight'.
    `day` (or the text itself) may name a day: "tomorrow", "friday", "5 december"..."""
    t = words_to_numbers(text.lower()).replace("o'clock", "").replace("oclock", "")
    on = parse_day(day) if day else None
    on = on or parse_day(t)
    t = re.sub(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b|"
               r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}(?:st|nd|rd|th)?\b|"
               r"\bin \d+ days?\b|\bthe \d{1,2}(?:st|nd|rd|th)\b|\b\d{1,2}[/-]\d{1,2}\b", " ", t)   # dates aren't times
    t = re.sub(r"\bhalf past (\d{1,2})\b", r"\1:30", t)
    t = re.sub(r"\bquarter past (\d{1,2})\b", r"\1:15", t)
    t = re.sub(r"\b(\d{1,2}) (\d{2})\b", r"\1:\2", t)           # "7 30" (from "seven thirty")
    if "noon" in t:
        hh, mm, mer = 12, 0, "noon"
    elif "midnight" in t:
        hh, mm, mer = 0, 0, "midnight"
    else:
        m = _CLOCK.search(t)
        if not m:
            return None
        hh, mm, mer = int(m[1]), int(m[2] or 0), (m[3] or "").replace(".", "")
        if hh > 23 or mm > 59:
            return None
        if mer.startswith("p") or mer in ("in the evening", "at night", "in the afternoon", "tonight"):
            hh = hh % 12 + 12
        elif mer.startswith("a") or mer == "in the morning":
            hh = hh % 12
        elif hh <= 12 and not m[0].startswith("0"):
            # no am/pm: pick the next time this clock reading happens
            cand = [hh % 12, hh % 12 + 12]
            current = datetime.now()
            hh = min(cand, key=lambda h: (current.replace(hour=h, minute=mm, second=0, microsecond=0) - current)
                     % timedelta(days=1))
    current = datetime.now()
    if on and on > current.date():
        if not mer and "noon" not in t and "midnight" not in t and prefer_morning and int(m[1]) <= 12:
            hh = int(m[1]) % 12                        # an alarm "friday at 6:30" = 6:30 am
        elif not mer and "noon" not in t and "midnight" not in t and 1 <= int(m[1]) <= 6:
            hh = int(m[1]) + 12                        # "friday at 5" = 5 pm
        elif not mer and "noon" not in t and "midnight" not in t and 7 <= int(m[1]) <= 12:
            hh = int(m[1]) % 12 + (12 if int(m[1]) == 12 else 0)
        return datetime.combine(on, dtime(hh, mm))
    when = current.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if when <= current:
        if on == current.date():
            # the user said TODAY: a minute just started -> now; otherwise keep the past time (callers say so)
            return current + timedelta(seconds=3) if current - when < timedelta(minutes=2) else when
        when += timedelta(days=1)
    return when


def _passed(when) -> str:
    return (f"{say_clock(when).replace(' today', '')} has already passed today. "
            "Should I set it for tomorrow instead?") if when and when < datetime.now() else ""


def say_clock(dt: datetime) -> str:
    s = dt.strftime("%I:%M %p").lstrip("0").replace(":00", "")
    today = datetime.now().date()
    if dt.date() == today:
        return f"{s} today"
    return f"{s} {say_day(dt.date(), today)}"


def _to_utc(local: datetime) -> str:
    return local.astimezone().astimezone(timezone.utc).isoformat(timespec="seconds")


def _to_local(utc_iso: str) -> datetime:
    return datetime.fromisoformat(utc_iso).astimezone().replace(tzinfo=None)


# ---------------------------------------------------------------- tools
def get_time(what: str = "time") -> str:
    n = datetime.now()
    if what == "date":
        return f"Today is {n.strftime('%A')}, {n.day} {n.strftime('%B %Y')}."
    if what == "day":
        return f"Today is {n.strftime('%A')}."
    return f"It's {n.strftime('%I:%M %p').lstrip('0')}."


def _add(kind: str, label: str, due: datetime) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO reminders (kind, label, due_at, created_at) VALUES (?,?,?,?)",
                     (kind, (label or "").strip()[:120] or None, _to_utc(due), now()))


def set_timer(duration: str = "", minutes: float = 0, seconds: int = 0, label: str = "") -> str:
    total = parse_duration(duration) if duration else 0
    total = total or int(round(float(minutes or 0) * 60 + int(seconds or 0)))
    if total <= 0:
        return "How long should the timer be?"
    if total > 24 * 3600:
        return "Timers can be at most 24 hours. Use an alarm for that."
    _add("timer", label or re.sub(r"(hour|minute|second)s\b", r"\1", say_duration(total)),   # "a 5 minute timer"
         datetime.now() + timedelta(seconds=total))
    return f"Timer set for {say_duration(total)}."


def set_alarm(time: str, day: str = "", label: str = "") -> str:
    when = parse_clock(time, day, prefer_morning=True)
    if _passed(when):
        return _passed(when)
    if not when:
        return "What time should the alarm be?"
    _add("alarm", label, when)
    return f"Alarm set for {say_clock(when)}."


def set_reminder(text: str, in_time: str = "", at: str = "", day: str = "") -> str:
    text = re.sub(r"^(to|that|i (need|have) to)\s+", "", (text or "").strip(), flags=re.I).rstrip(".")
    for a, b in ((r"\bmy\b", "your"), (r"\bme\b", "you"), (r"\bi'm\b", "you're"), (r"\bi\b", "you"),
                 (r"\bmine\b", "yours")):
        text = re.sub(a, b, text, flags=re.I)          # "take my pills" -> "take your pills"
    if not text:
        return "What should I remind you about?"
    if in_time:
        secs = parse_duration(in_time)
        if not secs:
            return "When should I remind you?"
        when = datetime.now() + timedelta(seconds=secs)
    elif at:
        when = parse_clock(at, day)
        if not when:
            return "What time should I remind you?"
        if _passed(when):
            return _passed(when)
    else:
        return "When should I remind you?"
    _add("reminder", text, when)
    return f"I'll remind you to {text} at {say_clock(when)}." if at else \
        f"I'll remind you to {text} in {say_duration(int((when - datetime.now()).total_seconds() + 0.5))}."


def _pending(kind: str = "any"):
    q, args = "SELECT * FROM reminders WHERE status = 'pending'", []
    if kind != "any":
        q += " AND kind = ?"; args.append(kind)
    with connect() as conn:
        return conn.execute(q + " ORDER BY due_at", args).fetchall()


def _describe(r) -> str:
    due = _to_local(r["due_at"])
    if r["kind"] == "timer":
        left = int((due - datetime.now()).total_seconds())
        return f"a {r['label']} timer with {say_duration(max(left, 0))} left"
    if r["kind"] == "alarm":
        return f"an alarm at {say_clock(due)}"
    if (r["label"] or "").startswith("for "):                     # heads-up for a calendar event
        return f"a reminder {r['label']}"
    return f"a reminder to {r['label']} at {say_clock(due)}"


def manage_reminders(action: str = "list", kind: str = "any") -> str:
    rows = _pending(kind)
    noun = {"any": "timers, alarms or reminders", "timer": "timers", "alarm": "alarms", "reminder": "reminders"}[kind]
    if not rows:
        return f"You have no {noun} set."
    if action == "list":
        items = [_describe(r) for r in rows[:5]]
        more = f", and {len(rows) - 5} more" if len(rows) > 5 else ""
        return "You have " + ", ".join(items) + more + "."
    ids = [r["id"] for r in rows] if action == "cancel_all" else [rows[-1]["id"] if kind == "any" else rows[0]["id"]]
    with connect() as conn:
        conn.executemany("UPDATE reminders SET status = 'cancelled' WHERE id = ?", [(i,) for i in ids])
    if action == "cancel_all":
        return f"Cancelled all {len(ids)} of your {noun}."
    return f"Cancelled {_describe([r for r in rows if r['id'] == ids[0]][0])}."


def pop_due() -> list[dict]:
    """Items whose time has come; marks them done. Called by the scheduler thread."""
    cutoff = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as conn:
        rows = conn.execute("SELECT * FROM reminders WHERE status = 'pending' AND due_at <= ? ORDER BY due_at",
                            (cutoff,)).fetchall()
        conn.executemany("UPDATE reminders SET status = 'done' WHERE id = ?", [(r["id"],) for r in rows])
    out = []
    for r in rows:
        late = (datetime.now() - _to_local(r["due_at"])).total_seconds() > 300
        out.append({"kind": r["kind"], "label": r["label"], "late": late, "due": _to_local(r["due_at"])})
    return out


def upcoming_today() -> list[str]:
    """Spoken descriptions of alarms/reminders due before the end of today (for routines)."""
    end = datetime.now().replace(hour=23, minute=59, second=59)
    return [_describe(r) for r in _pending() if r["kind"] != "timer" and _to_local(r["due_at"]) <= end]


def upcoming_tomorrow_morning() -> list[str]:
    start = datetime.combine(datetime.now().date() + timedelta(days=1), dtime(0, 0))    # not the rest of today
    end = start.replace(hour=12)
    return [_describe(r) for r in _pending() if r["kind"] != "timer" and start <= _to_local(r["due_at"]) <= end]


def pending_items(limit: int = 6) -> list[dict]:
    """For the window: what's running, soonest first."""
    return [{"id": r["id"], "kind": r["kind"], "label": r["label"] or "", "due": _to_local(r["due_at"])}
            for r in _pending()[:limit]]


def cancel_id(item_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'", (item_id,))
