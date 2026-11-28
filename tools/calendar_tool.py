"""Calendar: your own events (added by voice, stored locally) + Google Calendar, read-only.

Google: Calendar settings -> your calendar -> "Secret address in iCal format" -> CALENDAR_ICS_URL in .env.
Momo only READS that feed (no login, no write access). Event titles from it are outside text (anyone can send you
an invite), so they go through the extractor's sanitiser/injection filter and are read out by a template: no LLM
sees them, and replies that contain them are hidden from the router like other web data.
"""
import re
import threading
import time
from datetime import date, datetime, time as dtime, timedelta, timezone

import config
from backend.database import connect, now
from security import extractor
from security.egress import safe_get

from .clock import _add as add_reminder, parse_clock
from .dates import parse_day, say_day

_cache = {"at": 0.0, "cal": None}
_lock = threading.Lock()


def _utc(local: datetime) -> str:
    return local.astimezone().astimezone(timezone.utc).isoformat(timespec="seconds")


def _local(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone().replace(tzinfo=None)


def _clean_title(title: str) -> str:
    title = re.sub(r"^(?:a|an|the|my)\s+", "", (title or "").strip(), flags=re.I).strip(" .")
    title = re.sub(r"\s+(?:to|in|on)\s+(?:my\s+)?calendar$", "", title, flags=re.I)
    return title[:100]


# ---------------------------------------------------------------- local events
def add_event(title: str, day: str = "", time: str = "") -> str:
    title = _clean_title(title)
    if not title:
        return "What should I call the event?"
    d = parse_day(day) or parse_day(time)
    if not d:
        return f"Which day is the {title}?"
    when, all_day = None, 1
    if time and re.search(r"\d|noon|midnight|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve", time, re.I):
        when = parse_clock(time, d.isoformat() if d != datetime.now().date() else "today")
        if when and when.date() != d:
            when = datetime.combine(d, when.time())
        all_day = 0 if when else 1
    start = when or datetime.combine(d, dtime(0, 0))
    with connect() as conn:
        conn.execute("INSERT INTO events (title, start_at, all_day, created_at) VALUES (?,?,?,?)",
                     (title, _utc(start), all_day, now()))
    if when and config.CALENDAR_REMIND_MIN and when - timedelta(minutes=config.CALENDAR_REMIND_MIN) > datetime.now():
        add_reminder("reminder", f"for {title} at {when.strftime('%I:%M %p').lstrip('0').replace(':00', '')}",
                     when - timedelta(minutes=config.CALENDAR_REMIND_MIN))
    at = f" at {when.strftime('%I:%M %p').lstrip('0').replace(':00', '')}" if when else ""
    return f"Added {title} to your calendar {say_day(d)}{at}."


def cancel_event(title: str) -> str:
    key = _clean_title(title).lower()
    with connect() as conn:
        rows = conn.execute("SELECT id, title, start_at FROM events WHERE status='active' AND start_at >= ? "
                            "ORDER BY start_at", (_utc(datetime.combine(datetime.now().date(), dtime(0, 0))),)).fetchall()
        hit = next((r for r in rows if key and (key in r["title"].lower() or r["title"].lower() in key)), None)
        if not hit:
            return f"I couldn't find {title or 'that event'} in your calendar."
        conn.execute("UPDATE events SET status='cancelled' WHERE id=?", (hit["id"],))
        conn.execute("UPDATE reminders SET status='cancelled' WHERE status='pending' AND label LIKE ?",
                     (f"for {hit['title']} at %",))           # its heads-up reminder too
    return f"Removed {hit['title']} {say_day(_local(hit['start_at']).date())} from your calendar."


def _local_events(start: date, end: date) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT title, start_at, all_day FROM events WHERE status='active' AND start_at >= ? "
                            "AND start_at < ? ORDER BY start_at",
                            (_utc(datetime.combine(start, dtime(0, 0))), _utc(datetime.combine(end, dtime(0, 0))))).fetchall()
    return [{"title": r["title"], "start": _local(r["start_at"]), "all_day": bool(r["all_day"]), "google": False}
            for r in rows]


# ---------------------------------------------------------------- Google Calendar (read-only iCal feed)
def _google_events(start: date, end: date) -> list[dict]:
    if not config.CALENDAR_ICS_URL:
        return []
    import icalendar
    import recurring_ical_events
    with _lock:
        if _cache["cal"] is None or time.time() - _cache["at"] > 600:
            raw = safe_get(config.CALENDAR_ICS_URL, timeout=10).content
            _cache["cal"], _cache["at"] = icalendar.Calendar.from_ical(raw), time.time()
        cal = _cache["cal"]
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        title = extractor.headline(str(ev.get("SUMMARY", "")), 80) or "an event"
        s = ev.get("DTSTART").dt
        all_day = not isinstance(s, datetime)
        s = datetime.combine(s, dtime(0, 0)) if all_day else (s.astimezone().replace(tzinfo=None) if s.tzinfo else s)
        out.append({"title": title, "start": s, "all_day": all_day, "google": True})
    return out


def events_between(start: date, end: date) -> list[dict]:
    items = _local_events(start, end)
    try:
        items += _google_events(start, end)
    except Exception as e:
        print(f"[calendar] google feed failed: {type(e).__name__}: {e}")
    return sorted(items, key=lambda e: (e["start"].date(), not e["all_day"], e["start"]))


def _say(e) -> str:
    return e["title"] + ("" if e["all_day"] else f" at {e['start'].strftime('%I:%M %p').lstrip('0').replace(':00', '')}")


def get_events(day: str = "today") -> str:
    today = datetime.now().date()
    if re.search(r"\b(week|next 7 days|coming days)\b", day or "", re.I):
        start, end, label = today, today + timedelta(days=7), "in the next 7 days"
    else:
        start = parse_day(day or "today") or today
        end, label = start + timedelta(days=1), say_day(start)
    evs = events_between(start, end)
    if not evs:
        return f"Your calendar is clear {label}."
    if end - start > timedelta(days=1):
        parts = [f"{_say(e)} {say_day(e['start'].date())}" for e in evs[:8]]
    else:
        parts = [_say(e) for e in evs[:8]]
    return f"{label[:1].upper() + label[1:]} you have " + ", ".join(parts) + "."


def manage_calendar(action: str = "show", title: str = "", day: str = "", time: str = "") -> str:
    if action == "add":
        return add_event(title, day, time)
    if action == "cancel":
        return cancel_event(title)
    return get_events(day or "today")


def today_summary() -> str:
    evs = events_between(datetime.now().date(), datetime.now().date() + timedelta(days=1))
    return ("On your calendar today: " + ", ".join(_say(e) for e in evs[:5]) + ".") if evs else ""
