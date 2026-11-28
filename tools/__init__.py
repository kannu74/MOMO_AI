"""Tools the agent may call.

Every tool:
  * has a strict schema (Literal enums) so the LLM can't invent arguments,
  * runs with a timeout,
  * returns a short, locally built result. The exceptions are get_info and google_it: their web text comes back
    only as an escaped <external_data trust="untrusted"> block made by security/extractor.py, which core.py hands to the
    responder (no tools) and never to the router or the stored history.
Only names in TOOLS can ever be executed.
"""
import json
import concurrent.futures as cf
from typing import Literal

from langchain_core.tools import tool

import config

from backend.database import add_fact, last_assistant_message, remove_fact
from security import outbox
from . import calc, calendar_tool, clock, entertainment, info, lists, music, routines, search, system, weather

TIMEOUT_SEC = 20
CONTEXT = {"session_id": None, "lang": "en"}   # set by backend.core before tools run
EXTERNAL_TOOLS = {"get_info", "google_it"}        # results contain untrusted web data


# ---------------------------------------------------------------- Phase 1
@tool
def get_weather(when: Literal["now", "today", "tomorrow"] = "now") -> str:
    """Get the weather in the user's city. Use for any weather, rain, temperature or umbrella question."""
    return str(weather.get_weather(when))


@tool
def play_music(query: str = "", playlist: str = "", shuffle: bool = False, different: bool = False) -> str:
    """Start music. `query` = song, artist, anime, mood or genre to find on YouTube, in the user's words.
    `playlist` ONLY for one of the user's saved playlists. `different`=true when they want another/different song
    than the one playing ("play another naruto song", "not this one")."""
    return music.play_music(query=query, playlist=playlist, shuffle=shuffle, different=different)


@tool
def music_control(action: Literal["pause", "resume", "stop", "next", "previous", "volume_up", "volume_down",
                                  "volume_max", "set_volume", "shuffle"], level: int = -1) -> str:
    """Control Momo's music that is already playing. set_volume needs `level` 0-100 ("volume to 70%").
    shuffle = mix the order of the songs queued now."""
    return music.music_control(action, level)


@tool
def manage_playlist(action: Literal["create", "add", "remove", "list", "songs", "shuffle", "delete"], name: str = "",
                    song: str = "") -> str:
    """Manage the user's saved playlists. Leave `song` EMPTY for the song playing right now ("add this to chill",
    "add this music to anime"). Only fill `song` when the user says an actual song name, or a number from the
    songs list ("remove song 3" -> song="3"). list = the playlists; songs = the songs inside playlist `name`;
    shuffle = play playlist `name` in a random order."""
    return music.manage_playlist(action=action, name=name, song=song)


@tool
def remember(fact: str) -> str:
    """Save a lasting fact about the user (name, people in their life, likes, birthday, job...). Short, third person,
    e.g. "The user's girlfriend is called Ashmi"."""
    add_fact(fact)
    return "Saved to memory."


@tool
def forget(fact: str) -> str:
    """Delete a saved fact about the user when they ask you to forget it. `fact` = a key word or two from it."""
    return "Forgot it." if remove_fact(fact) else "I had nothing saved about that."


# ---------------------------------------------------------------- Phase 2
@tool
def get_time(what: Literal["time", "date", "day"] = "time") -> str:
    """Current time, today's date or the day of the week."""
    return clock.get_time(what)


@tool
def set_timer(duration: str, label: str = "") -> str:
    """Start a countdown timer. `duration` in the user's words, e.g. "5 minutes", "an hour and a half"."""
    return clock.set_timer(duration=duration, label=label)


@tool
def set_alarm(time: str, day: str = "", label: str = "") -> str:
    """Set an alarm at a clock time, e.g. time="7:30 am". `day` in the user's words if they name one
    ("tomorrow", "friday", "5 december"); empty = the next time that clock time comes."""
    return clock.set_alarm(time=time, day=day, label=label)


@tool
def set_reminder(text: str, in_time: str = "", at: str = "", day: str = "") -> str:
    """Remind the user of something later. `text` = what to remind ("call mom"). Give EITHER `in_time`
    ("20 minutes") OR `at` (a clock time like "6 pm")."""
    return clock.set_reminder(text=text, in_time=in_time, at=at, day=day)


@tool
def manage_reminders(action: Literal["list", "cancel", "cancel_all"] = "list",
                     kind: Literal["any", "timer", "alarm", "reminder"] = "any") -> str:
    """List or cancel timers, alarms and reminders. cancel = the most recent one of that kind."""
    return clock.manage_reminders(action=action, kind=kind)


@tool
def manage_list(action: Literal["add", "remove", "show", "clear"], list_name: str = "to-do", item: str = "") -> str:
    """The user's lists: "to-do", "shopping" or any other name. `item` may hold several ("milk and eggs")."""
    return lists.manage_list(action=action, list_name=list_name, item=item)


@tool
def calculate(expression: str) -> str:
    """Do arithmetic, e.g. "15% of 240", "(12+8)*3", "sqrt(144)"."""
    return calc.calculate(expression)


@tool
def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    """Convert units: length, weight, volume, temperature, speed, time, data, area. e.g. 5, "miles", "km"."""
    return calc.convert_units(value, from_unit, to_unit)


@tool
def system_control(action: Literal["volume_up", "volume_down", "mute", "set_volume", "media_play_pause",
                                   "media_next", "media_previous"], level: int = -1) -> str:
    """The COMPUTER's own volume and media keys (other apps like Spotify or a video), NOT Momo's music.
    Use only when the user says computer/PC/laptop/system volume, mute, or the video/Spotify."""
    return system.system_control(action, level)


@tool
def run_routine(name: Literal["good_morning", "good_night"]) -> str:
    """Morning briefing (time, weather, today's reminders) or the good-night routine (stops music, tomorrow's alarms)."""
    return routines.run_routine(name)


# ---------------------------------------------------------------- Phase 3 (web + email, see security/)
@tool
def get_info(topic: str, question: str = "") -> str:
    """Look up facts on Wikipedia: people, places, films, games, science, history, how things work, anything
    the user asks about that you may not know. `topic` = the thing to look up, in the user's words."""
    return info.get_info(topic=topic, question=question)


@tool
def google_it(topic: str, question: str = "") -> str:
    """Search the web and read the top pages. For anything recent or changing: current events and what happened
    with something, the full story behind news, latest releases, prices, scores, results, who holds a position NOW,
    dates of upcoming things, or a fact the encyclopedia doesn't have. `topic` = a short search query in the user's
    words ("ipl 2026 final result", "gta 6 release date")."""
    return search.google_it(topic=topic, question=question)


@tool
def get_news(topic: str = "") -> str:
    """Latest news headlines. `topic` = what the news is about ("cricket", "AI"), or empty for the user's usual topics."""
    return info.get_news(topic, lang=CONTEXT.get("lang", "en"))


@tool
def draft_email(to: str, subject: str = "", body: str = "", include: Literal["", "last_reply", "news"] = "") -> str:
    """Write an email for the user to approve on screen (it is NEVER sent automatically). `to` = the contact name
    the user said ("mom", "me"). `body` = what they want to say. include="last_reply" when they say "email me
    that/this"; include="news" for "email me the news"."""
    tainted = False
    extra = ""
    if include == "last_reply":
        last = last_assistant_message(CONTEXT["session_id"]) if CONTEXT["session_id"] else None
        if last:
            extra = last["content"]
            tainted = bool(last.get("tools") and json.loads(last["tools"]).get("external"))
    elif include == "news":
        extra, tainted = info.news_digest(), True
    body = "\n\n".join(p for p in (body.strip(), extra.strip()) if p)
    return outbox.create_draft(to=to, subject=subject, body=body, tainted=tainted)


@tool
def manage_calendar(action: Literal["show", "add", "cancel"] = "show", title: str = "", day: str = "",
                    time: str = "") -> str:
    """The user's calendar (their events, plus Google Calendar). show: what's on a day ("today", "tomorrow",
    "friday", "week"). add: an event with `title`, `day` and optional `time`. cancel: remove an event by `title`."""
    return calendar_tool.manage_calendar(action=action, title=title, day=day, time=time)


@tool
def open_entertainment(website_name: Literal["netflix", "hotstar", "primevideo", "youtube"],
                       browser: Literal["default", "brave", "chrome", "edge"] = "default") -> str:
    """Open Netflix, Hotstar, Prime Video or the YouTube website in a browser (only opens it; can't search,
    click or play anything there). browser="brave" etc. only when the user names one. For playing a SONG use
    play_music instead."""
    return entertainment.open_entertainment(website_name, browser)


TOOLS = [get_weather, play_music, music_control, manage_playlist, remember, forget, get_time, set_timer, set_alarm,
         set_reminder, manage_reminders, manage_list, calculate, convert_units, system_control, run_routine,
         get_info, get_news, draft_email, open_entertainment, manage_calendar]
if config.SEARCH_ENABLED:                     # GOOGLE_IT=0 in .env removes web search entirely
    TOOLS.append(google_it)
_BY_NAME = {t.name: t for t in TOOLS}
_pool = cf.ThreadPoolExecutor(max_workers=2)


def run_tool(name: str, args: dict) -> str:
    """Validate and execute one tool call. Errors become short messages for the LLM."""
    t = _BY_NAME.get(name)
    if t is None:
        return f"error: unknown tool {name}"
    try:
        return _pool.submit(t.invoke, args).result(timeout=TIMEOUT_SEC)
    except cf.TimeoutError:
        return "error: the tool took too long"
    except Exception as e:  # validation or runtime error
        print(f"[tool] {name}({args}) failed: {e}")
        return f"error: {type(e).__name__}"
