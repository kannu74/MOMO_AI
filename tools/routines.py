"""Routines: one phrase -> several skills. Every sentence is built locally."""
from datetime import datetime

import config
from . import calendar_tool, clock, lists, music, weather


def _weather_line() -> str:
    try:
        w = weather.get_weather("today")
        pct = w["rain_chance_pct"]
        article = "an" if str(pct).startswith("8") or pct in (11, 18) else "a"
        rain = f", with {article} {pct} percent chance of rain" if pct >= 30 else ""
        return f"The weather in {w['location']} today: {w['condition']}, between {w['low_c']} and {w['high_c']} degrees{rain}."
    except Exception:
        return "I couldn't get the weather just now."


def good_morning() -> str:
    n = datetime.now()
    parts = [f"It's {n.strftime('%I:%M %p').lstrip('0')} on {n.strftime('%A')}, {n.day} {n.strftime('%B')}.",
             _weather_line()]
    due = clock.upcoming_today()
    try:
        cal = calendar_tool.today_summary()
    except Exception:
        cal = ""
    if cal:
        parts.append(cal)
    parts.append(("Today you have " + ", ".join(due) + ".") if due else ("" if cal else "You have nothing scheduled today."))
    parts += [f"There are {s}." for s in lists.list_summary()[:2]]
    if config.MORNING_PLAYLIST:
        parts.append(music.play_music(playlist=config.MORNING_PLAYLIST))
    return " ".join(parts)


def good_night() -> str:
    parts = []
    if music.player.state() != "stopped":
        music.player.control("stop")
        parts.append("I've stopped the music.")
    due = clock.upcoming_tomorrow_morning()
    parts.append(("Tomorrow morning you have " + ", ".join(due) + ".") if due else "No alarms are set for tomorrow morning.")
    return " ".join(parts)


def run_routine(name: str) -> str:
    return good_morning() if name == "good_morning" else good_night()
