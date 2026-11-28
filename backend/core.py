# backend/core.py
"""Momo's brain: a two-step LangChain agent on a local Ollama model.

  0. Clean-up   - strip the wake word / STT slips ("lay me X" -> "play me X"), repeated sentences.
  1. Route      - unambiguous commands go through regex fast paths; everything else through the
                  router LLM (tools bound) with the recent conversation, including what Momo DID each turn.
  2. Tools      - validated, time-limited, allowlisted execution (tools/__init__.py), plus guards
                  (music is only ever stopped/paused when the user actually said so).
  3. Reply      - command results are confirmed with a short template (exact, instant);
                  chat, weather and anything open-ended goes to the responder LLM.
  4. Memory     - user message + tool calls/results + reply are stored per turn (data/memory.db), so
                  "add it to chill", "play another one", "which playlist?" -> "chill" work next turn.

Web data (get_info / google_it / get_news, see security/): the router never sees it. get_info's and google_it's
facts reach only the responder (no tools bound), inside an escaped <external_data trust="untrusted"> block, with security rules in the
system prompt. What is stored in history is a summary, never the web text, and replies built from web data are
hidden from the router. Emails are only drafted here; the window's Approve button sends them.
"""
import difflib
import json
import random
import re
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

import config
from security import outbox
from security.extractor import EXTERNAL_BLOCK, suspicious
from tools import CONTEXT, EXTERNAL_TOOLS, TOOLS, run_tool
from tools.clock import parse_duration, words_to_numbers
from tools.music import player, playlist_names
from . import hindi as hindi_words
from .database import add_message, get_facts, get_recent_messages
from .persona import EXTERNAL_RULES, ROUTER_PROMPT, build_system_prompt

T = config.USER_TITLE

_common = dict(model=config.OLLAMA_MODEL, base_url=config.OLLAMA_URL, num_ctx=config.OLLAMA_NUM_CTX, keep_alive="30m")
router = ChatOllama(temperature=0, **_common).bind_tools(TOOLS)
responder = ChatOllama(temperature=0.7, num_predict=120, **_common)
translator = ChatOllama(temperature=0, num_predict=400, **_common)      # Devanagari needs many tokens
responder_hi = ChatOllama(temperature=0.7, num_predict=320, **_common)
LANG = {"code": "en"}           # "en" (English + Hinglish) or "hi" (pure Hindi); set by backend/language.py


def warm_up(wait_sec: float = 180):
    """Load the LLM onto the GPU before the first request. Started at login, Ollama may still be starting: wait."""
    deadline = time.time() + wait_sec
    while True:
        try:
            responder.invoke("hi")
            return
        except Exception as e:
            if time.time() > deadline:
                raise
            print(f"[boot] waiting for Ollama ({type(e).__name__})...", flush=True)
            time.sleep(5)


def set_llm(model: str) -> None:
    """Use another Ollama model (per-language setting) and unload the old one, so only one sits in VRAM."""
    global router, responder, translator, responder_hi
    old = _common["model"]
    if not model or model == old:
        return
    _common["model"] = model
    router = ChatOllama(temperature=0, **_common).bind_tools(TOOLS)
    responder = ChatOllama(temperature=0.7, num_predict=120, **_common)
    translator = ChatOllama(temperature=0, num_predict=400, **_common)
    responder_hi = ChatOllama(temperature=0.7, num_predict=320, **_common)
    try:
        import requests
        requests.post(f"{config.OLLAMA_URL}/api/generate", json={"model": old, "keep_alive": 0}, timeout=15)
    except Exception as e:
        print(f"[llm] could not unload {old}: {e}")
    print(f"[llm] {old} -> {model}")
    warm_up()


# ---------------------------------------------------------------- 0. input clean-up
_WAKE = re.compile(r"^\s*(?:(?:hey|hi|hello|okay|ok|oi|yo)[\s,]+)?(?:momo|mo mo|moe moe|mumu|momma)\b[\s,.!?]*", re.I)
_PLAY_SLIPS = re.compile(r"^(?:lay|lea|layer|clay|blay|plate)\b(?=\s+(?:me|a|an|some|any|the|my|"
                         r"music|song|another|other|that|this)\b)", re.I)


def normalize(text: str) -> str:
    t = text.strip()
    while True:                                       # "Hey Momo. Hey Momo, play..." -> "play..."
        s = _WAKE.sub("", t, count=1)
        if s == t:
            break
        t = s
    t = _PLAY_SLIPS.sub("play", t)
    # Whisper loops on noise/music: "May the Lord bless you. May the Lord bless you." -> once
    sents, out = re.split(r"(?<=[.!?])\s+", t), []
    for s in sents:
        if not out or s.strip(" .!?").lower() != out[-1].strip(" .!?").lower():
            out.append(s)
    t = " ".join(out).strip()
    return t[:1].upper() + t[1:] if t else ""


# ---------------------------------------------------------------- 0b. Hinglish commands -> English (Hindi mode)
# In Hindi mode Whisper writes Hindi/Hinglish in Latin letters: "Arijit Singh ka gaana bajao". These exact rules turn
# common commands into English before the LLM translator is asked (respond() -> Hindi mode). Not used in English mode.
_HI_END = r"\s*(?:na|please|jaldi|zara|momo)?[.!?]*$"
_HI_VERB_PLAY = r"(?:baja(?:o|a?o)|baja\s+do|chala(?:o)|chala\s+do|laga(?:o)|laga\s+do|suna(?:o)|suna\s+do|play\s+kar(?:o|\s+do))"
_HI_VERB_MUSIC = r"(?:baja(?:o|a?o)|baja\s+do|suna(?:o)|suna\s+do|play\s+kar(?:o|\s+do))"
_HI_SONG = r"(?:gaana|gana|gaane|gane|geet|song|songs|music)"
_HI_WORDS = [(r"\bnaya\b|\bnaye\b|\bnayi\b", "new"), (r"\bpurana\b|\bpurane\b", "old"), (r"\bsad\s+wala\b", "sad"),
             (r"\b(?:koi|kuch|ek|sa|wala|wale|vala)\b", ""), (r"\b(?:ka|ki|ke)\b", "")]
_HINGLISH = [
    # next / another song
    (re.compile(rf"^(?:agla|agli|next)\s+{_HI_SONG}(?:\s+{_HI_VERB_PLAY})?{_HI_END}", re.I), lambda m: "next song"),
    (re.compile(rf"^(?:doosra|dusra|dusri|koi\s+aur|aur\s+koi)\s+{_HI_SONG}(?:\s+{_HI_VERB_PLAY})?{_HI_END}", re.I),
     lambda m: "play something else, not this one"),
    # stop / pause / resume
    (re.compile(rf"^(?:{_HI_SONG}\s+)?(?:band|bandh)\s+kar(?:o|\s+do|do|iye)?{_HI_END}", re.I), lambda m: "stop the music"),
    (re.compile(rf"^(?:{_HI_SONG}\s+)?(?:ruko|roko|rok\s+do|pause\s+kar(?:o|\s+do)){_HI_END}", re.I), lambda m: "pause"),
    (re.compile(rf"^(?:{_HI_SONG}\s+)?(?:phir\s+se|wapas|dobara)\s+(?:chalao|chala\s+do|bajao|shuru\s+karo){_HI_END}", re.I),
     lambda m: "resume"),
    # volume
    (re.compile(rf"^(?:{_HI_SONG}\s+(?:ki\s+)?)?(?:awaaz|awaz|aawaz|aavaz|avaaz|volume)\s+(?:thoda\s+|thodi\s+|zara\s+|aur\s+)*"
                rf"(?:badhao|badha\s+do|tez\s+kar(?:o|\s+do)|zyada\s+kar(?:o|\s+do)|upar\s+kar(?:o|\s+do)){_HI_END}", re.I),
     lambda m: "turn the music volume up"),
    (re.compile(rf"^(?:{_HI_SONG}\s+(?:ki\s+)?)?(?:awaaz|awaz|aawaz|aavaz|avaaz|volume)\s+(?:thoda\s+|thodi\s+|zara\s+|aur\s+)*"
                rf"(?:kam|dheere|dheema|neeche|halka|halki)\s+kar(?:o|\s+do){_HI_END}", re.I),
     lambda m: "turn the music volume down"),
    # "isko chill playlist mein daal do" -> "add this to chill playlist"
    (re.compile(rf"^(?:isko|isse|ise|ye|yeh|is)\s+(?:{_HI_SONG}\s+(?:ko\s+)?)?(?P<n>[\w\s'-]+?)\s+(?:playlist\s+)?(?:mein|me|main)\s+"
                rf"(?:daalo|daal\s+do|dalo|add\s+kar(?:o|\s+do)|save\s+kar(?:o|\s+do)){_HI_END}", re.I),
     lambda m: "add this to " + re.sub(r"\s+playlist$", "", m["n"], flags=re.I) + " playlist"),
    # "<something> ka gaana bajao" / "play badshah ka naya gaana" -> "play <something> hindi song"
    # bajao / sunao always mean music; lagao / chalao only with a song word ("timer laga do", "alarm lagao" aren't music)
    (re.compile(rf"^(?!.*\b(?:timer|alarm|reminder|list|yaad|calendar|netflix|hotstar|prime|youtube|volume|awaaz)\b)"
                rf"(?:play\s+)?(?:(?P<q>.*?)\s*{_HI_SONG}?\s+{_HI_VERB_MUSIC}|(?P<q3>.*?)\s*{_HI_SONG}\s+{_HI_VERB_PLAY}){_HI_END}"
                rf"|^play\s+(?P<q2>.*?\b(?:ka|ki|ke)\b.*?)\s+{_HI_SONG}{_HI_END}", re.I),
     lambda m: _hi_play(next(g for g in (m["q"], m["q3"], m["q2"]) if g is not None))),
]


def _hi_play(q: str) -> str:
    q = re.sub(rf"\b{_HI_SONG}\b", "", q or "", flags=re.I)
    for a, b in _HI_WORDS:
        q = re.sub(a, b, q, flags=re.I)
    q = re.sub(r"\s+", " ", q).strip(" ,.")
    if not q:
        return "play a hindi song"
    return f"play {q} " + ("song" if re.search(r"\b(hindi|punjabi|english|tamil|telugu|bollywood)\b", q, re.I) else "hindi song")


def hinglish(text: str) -> str:
    for pattern, build in _HINGLISH:
        m = pattern.match(text.strip())
        if m:
            out = build(m)
            print(f"[hinglish] {text!r} -> {out!r}")
            return out
    return text


# ---------------------------------------------------------------- 1a. fast paths (no LLM)
_POLITE = r"(?:(?:please|can you|could you|will you|would you|kindly|momo|now|and|so|okay|ok|i want you to|i|i'd like you to)[\s,]+)*"
_CUR = (r"(?:this|it|that|the|current|currently|playing|now|song|music|track|tune|one|which|is|that's|you're|"
        r"are|you|being|played|right|\s)+?")
_PL_NAME = r"(?:(?:my|the|a)\s+)?(?:playlist\s+(?:called|named)\s+|(?:new\s+)?playlist\s+)?(?P<name>[\w\s'-]+?)" \
           r"(?:\s+playlist)?"
_VOL_NUM = r"(?P<n>\d{1,3}|max(?:imum)?|full|hundred|one hundred)"


def _playlist(action, name):
    name = name.strip()
    if re.fullmatch(r"(?:(?:my|a|the|one of my)\s+)?playlists?", name, re.I):
        return "manage_playlist", {"action": action, "name": ""}      # tool asks "Which playlist?"
    # "one of my playlists and call that playlist chill" / "a new playlist named gym" -> the name at the end
    m = re.search(r"\b(?:called|named|call(?:\s+(?:that playlist|this playlist|the playlist|it as|it|that|this))?|"
                  r"name(?:\s+it)?)\s+([\w\s'-]+)$", name, re.I)
    if m:
        name = re.sub(r"\s+playlist$", "", m[1].strip(), flags=re.I)
    if re.search(r"(^|\s)(to-?do|todo|shopping|grocery|groceries)(\s|$)|\slist$", name, re.I):
        return None                                   # "add it to my shopping list" is a list, not a playlist
    if re.search(r"\b(playlists?|one of|and|which|some)\b", name, re.I) or len(name.split()) > 4:
        return None                                   # not a clean name: let the router read the sentence
    return "manage_playlist", {"action": action, "name": name}


def _playlist_remove(name, n):
    out = _playlist("remove", name)
    if out:
        out[1]["song"] = n
    return out


def _delete_playlist(name):
    name = name.strip()
    if re.search(r"\b(from|of|to|in|song|track|this|it|music)\b", name, re.I) or len(name.split()) > 4:
        return None                                   # "remove the song from chill playlist" is not "delete chill"
    return "manage_playlist", {"action": "delete", "name": name}


def _vol_level(n):
    return 100 if not n[0].isdigit() else int(n)


_SITE = (r"(?P<s>netflix|hot\s?star|disney\s+hotstar|jio\s?hotstar|prime(?:\s+video)?|amazon\s+prime(?:\s+video)?|"
         r"you\s?tube)(?:\.com)?")
_STREAM = (r"(?P<s>netflix|hot\s?star|disney\s+hotstar|jio\s?hotstar|prime(?:\s+video)?|amazon\s+prime(?:\s+video)?)"
           r"(?:\.com)?")                      # like _SITE without YouTube ("watch X on youtube" = music)
_SITE_WORDS = re.compile(r"\b(netflix|hot\s?star|prime|you\s?tube)\b", re.I)


def _open_site(m):
    from tools.entertainment import site_key
    key = site_key(m["s"])
    b = (m["b"] or "default").lower()
    return ("open_entertainment", {"website_name": key, "browser": "default" if "default" in b else b}) if key else None


def _open_site_loose(m):
    from tools.entertainment import site_key
    key = site_key(m["s"] or "")
    b = re.search(r"\b(brave|chrome|edge)\b", m.string, re.I)
    return ("open_entertainment", {"website_name": key, "browser": b[1].lower() if b else "default"}) if key else None


# ---------------------------------------------------------------- 1. instant replies (no LLM, no tokens)
SMALL_TALK = [
    (re.compile(r"^(?:hi|hello|hey|hii+|hey there|hello there|yo)(?:\s+(?:momo|there|master))?[.!?]*$", re.I),
     [f"Hello, {T}. How can I help?", f"Hello, {T}. I'm here.", f"Hi, {T}. What can I do for you?"]),
    (re.compile(r"^(?:ok(?:ay)?\s+)?(?:thank you|thanks|thank u|thanks a lot|thank you so much|thanks momo|thank you momo"
                r")(?:\s+(?:momo|so much|very much|a lot))?[.!?]*$", re.I),
     [f"You're welcome, {T}.", f"Always a pleasure, {T}.", f"Happy to help, {T}.", f"Anytime, {T}."]),
    (re.compile(r"^(?:who are you|what are you|what(?:'s| is) your name|tell me your name|introduce yourself|"
                r"who r u)[.!?]*$", re.I),
     [f"I'm Momo, {T}, your personal assistant. I live on this computer and I'm here to serve you."]),
    (re.compile(r"^(?:how are you|how are you doing|how's it going|how are things)"
                r"(?:\s+(?:momo|today))?[.!?]*$", re.I),
     [f"I'm well, {T}, thank you. How can I help you?", f"Very well, {T}, and ready to help. How are you?"]),
    (re.compile(r"^(?:good job|well done|nice work|great job|good girl|perfect|awesome|great|nice one|"
                r"you're the best|you are the best|shabash)(?:\s+(?:momo|thanks))?[.!?]*$", re.I),
     [f"Thank you, {T}. I'm glad I could help.", f"Thank you, {T}. That means a lot."]),
    (re.compile(r"^(?:what can you do|what are your features|what all can you do|help|what do you do)[.!?]*$", re.I),
     [f"I can play music and manage playlists, tell the weather, time and news, look things up, set timers, alarms "
      f"and reminders, keep your lists, do maths, open Netflix, Hotstar, Prime Video or YouTube, and write emails "
      f"for you to approve, {T}."]),
    (re.compile(r"^(?:sorry|i'm sorry|my bad|i am sorry)[.!?]*$", re.I), [f"No need to apologise, {T}."]),
]


_OTHER_SITE = re.compile(r"^(?:please\s+)?(?:open|launch|go to|visit)\s+(?:the\s+)?(?:website\s+)?"
                         r"(?P<x>[\w-]+\.(?:com|in|org|net|io|co|tv|app)\b\S*|.+?\s+(?:website|site|dot com))"
                         r"(?:\s+(?:on|in)\s+\w+(?:\s+browser)?)?[.!?]*$", re.I)


def small_talk(text: str):
    t = text.strip()
    m = _OTHER_SITE.match(t)
    if m and not _SITE_WORDS.search(m["x"]):
        return f"I'm sorry, {T}. I'm only allowed to open Netflix, Hotstar, Prime Video and YouTube."
    for pattern, replies in SMALL_TALK:
        if pattern.match(t):
            return random.choice(replies)
    return None


_NOT_TOPIC = re.compile(r"\d|%|\b(you|your|yourself|me|my|mine|i|we|time|date|day|today|tomorrow|weather|news|"
                        r"song|music|playing|this|that|it|playlist|timer|alarm|reminder|list|calendar|schedule|"
                        r"volume|plan|up|going on|happening)\b", re.I)


_RECENT = re.compile(r"\b(current|currently|latest|newest|recent|recently|now|upcoming|this year|"
                     r"these days|right now|so far)\b", re.I)


def _lookup(m):
    topic = m["t"].strip(" ?.!,")
    if _NOT_TOPIC.search(topic) or not 2 <= len(topic) <= 60:
        return None
    if config.SEARCH_ENABLED and _RECENT.search(topic):           # "who is the current pope": the web, not Wikipedia
        return "google_it", {"topic": topic, "question": m.string}
    return "get_info", {"topic": topic, "question": m.string}


_NOT_NEWS_TOPIC = re.compile(r"\b(i|have|has|had|got|some|good|bad|great|sad|big|any|the|my|your|me|more|this|that|"
                             r"you|we|our|no)\b", re.I)          # "I have some good news" is not a request


def _web(topic: str, question: str):
    """Fast path to google_it (only when web search is on). The topic is the user's own words."""
    year = time.localtime().tm_year
    topic = re.sub(r"\bthis year\b", str(year), re.sub(r"\blast year\b", str(year - 1), topic, flags=re.I), flags=re.I)
    topic = re.sub(r"\s+", " ", topic).strip(" ?.!,")
    if not config.SEARCH_ENABLED or not 2 <= len(topic) <= 80:
        return None
    return "google_it", {"topic": topic, "question": question}


_WEB_FAST = [
    # "google the best biryani recipe", "search the web for gta 6 news"
    (re.compile(r"^(?:please\s+)?(?:google|search\s+(?:on\s+)?(?:the\s+web|online|the\s+internet|google)(?:\s+for)?|"
                r"look\s+(?:it\s+)?up\s+online(?:\s+for)?|search\s+online\s+for)\s+(?P<t>.+?)[?.!]*$", re.I),
     lambda m: _web(m["t"], m.string)),
    # "who won the IPL this year", "which team won the world cup" (the routers often answered from memory)
    (re.compile(r"^(?:and\s+)?(?:who|which\s+(?:team|country|player|driver|film|movie))\s+(?P<v>won|wins|is\s+winning|"
                r"leads|is\s+leading)\s+(?P<t>.+?)[?.!]*$", re.I),
     lambda m: _web(f"{m['t']} winner", m.string)),
    # "when is GTA 6 coming out", "when does the IPL start"
    (re.compile(r"^when\s+(?:is|does|will|are|do)\s+(?P<t>.+?)\s+(?P<v>coming\s+out|come\s+out|releasing|release|"
                r"launching|launch|out|starting|start|begin|happening|happen)\b[^?]*[?.!]*$", re.I),
     lambda m: _web(f"{m['t']} " + ("start date" if re.match(r"start|begin", m["v"], re.I) else
                                    "date" if m["v"].lower().startswith("happen") else "release date"), m.string)),
    # "what's the price of bitcoin today", "what is the score of the india match"
    (re.compile(r"^(?:what(?:'s|s| is)|tell me)\s+(?:the\s+)?(?:current\s+|latest\s+|live\s+)?(?P<k>price|cost|score|"
                r"result|results|stock\s+price|exchange\s+rate)\s+(?:of|for|in)\s+(?P<t>.+?)[?.!]*$", re.I),
     lambda m: _web(f"{m['t']} {m['k']}", m.string)),
]

# after the headlines: "tell me more about the first one", "what happened in the second story", "yes"
_MORE_NEWS = re.compile(r"\b(?:tell me more|more about|more on|details?|full story|what happened|explain|elaborate|"
                        r"read (?:me )?(?:the )?(?:first|second|third|last))\b|^(?:the\s+)?(?:first|second|third|fourth|"
                        r"last)(?:\s+(?:one|story|headline))?[.!?]*$|^(?:yes|yeah|yep|sure|ok(?:ay)?|please)(?:[\s,]+"
                        r"(?:please|momo|master|tell me|go on|do it))*[.!?]*$", re.I)
_ORDINAL = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "last": -1}


def _news_followup(text: str, last_user: str):
    """Momo just read headlines and offered more: search the story the user picked (by number or by its words)."""
    from tools.info import LAST_HEADLINES
    if not config.SEARCH_ENABLED or "- get_news(" not in last_user or not LAST_HEADLINES or not _MORE_NEWS.search(text):
        return None
    m = re.search(r"\b(first|1st|second|2nd|third|3rd|fourth|4th|last)\b", text, re.I)
    if m:
        i = _ORDINAL[m[1].lower()]
        if i >= len(LAST_HEADLINES):
            return None
        pick = LAST_HEADLINES[i]
    else:
        words = {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2} - _FILLER - set(
            "tell more about story news the what happened happen one that this details detail full explain elaborate "
            "headline give know".split())
        overlap = lambda h: len(words & set(re.findall(r"[a-z0-9]+", h.lower())))
        pick = max(LAST_HEADLINES, key=overlap)
        if words and not overlap(pick):
            return None                               # they named something else: let the router decide
    return "google_it", {"topic": pick, "question": pick}


FAST_PATHS = [
    *_WEB_FAST,
    # knowledge: "who is X", "what do you think about X", "tell me about X", "do you know X"
    (re.compile(r"^(?:momo[\s,]+)?(?:what do you think (?:about|of)|what do you know about|do you know(?: about)?|"
                r"tell me (?:something |a bit |more )?about|who (?:is|was|are|were)|what (?:is|are|was) (?:a |an )?)"
                r"\s*(?P<t>[^?]+?)[?.!]*$", re.I), _lookup),
    # streaming sites: "open netflix", "open youtube on brave"
    (re.compile(rf"^{_POLITE}(?:open|launch|start|go to|put on)\s+(?:the\s+)?(?:website\s+)?{_SITE}(?:\s+(?:website|app|site))?"
                rf"(?:\s+(?:on|in|with|using)\s+(?P<b>brave|chrome|edge|(?:my\s+|the\s+)?default)(?:\s+browser)?)?[.!?]*$", re.I),
     _open_site),
    # "I want to watch something on netflix using brave", "put on prime video for me", "netflix chalao"
    (re.compile(rf"^(?!.*\b(?:song|music|gaana|playlist)\b).*?\b(?:open|watch|put on|launch|start)\b.*?\b"
                rf"{_STREAM}\b.*$", re.I), _open_site_loose),
    # "add this (music) to (my) (playlist called) anime (playlist)"
    (re.compile(rf"^{_POLITE}(?:add|put|save)\s+{_CUR}\s*(?:to|in|into|on|onto)\s+{_PL_NAME}[.!?]*$", re.I),
     lambda m: _playlist("add", m["name"])),
    (re.compile(rf"^{_POLITE}(?:remove|delete|take)\s+{_CUR}\s*(?:out\s+)?(?:from|of)\s+{_PL_NAME}[.!?]*$", re.I),
     lambda m: _playlist("remove", m["name"])),
    # music volume: "volume max", "set (the) volume to 70 (percent)", "volume at 100%"
    (re.compile(rf"^{_POLITE}(?:set|turn|put|make|change)?\s*(?:the\s+)?(?:music\s+)?volume\s*(?:to|at|on)?\s*{_VOL_NUM}"
                rf"\s*(?:%|percent)?[.!?]*$", re.I),
     lambda m: ("music_control", {"action": "set_volume", "level": _vol_level(m["n"])})),
    (re.compile(rf"^{_POLITE}(?:max(?:imum)?|full)\s+volume[.!?]*$", re.I),
     lambda m: ("music_control", {"action": "volume_max"})),
    # bare transport commands
    (re.compile(rf"^{_POLITE}(?:stop|stop the music|stop the song|stop playing|stop music)[.!?]*$", re.I),
     lambda m: ("music_control", {"action": "stop"})),
    (re.compile(rf"^{_POLITE}(?:pause|pause the music|pause the song|pause it)[.!?]*$", re.I),
     lambda m: ("music_control", {"action": "pause"})),
    (re.compile(rf"^{_POLITE}(?:resume|unpause|continue|resume the music|play it again|(?:keep|continue|carry on|go on)\s+(?:on\s+)?playing(?:\s+(?:the\s+)?(?:music|song|it))?)[.!?]*$", re.I),
     lambda m: ("music_control", {"action": "resume"})),
    (re.compile(rf"^{_POLITE}(?:skip|next|next song|skip this|skip it|skip this song|skip the song)[.!?]*$", re.I),
     lambda m: ("music_control", {"action": "next"})),
    # playlists: delete / list
    (re.compile(rf"^{_POLITE}(?:delete|remove|get rid of)\s+(?:the\s+|my\s+)?playlist\s+(?:called\s+|named\s+)?(?P<name>[\w\s'-]+?)[.!?]*$", re.I),
     lambda m: _delete_playlist(m["name"])),
    (re.compile(rf"^{_POLITE}(?:delete|remove|get rid of)\s+(?:the\s+|my\s+)(?P<name>[\w\s'-]+?)\s+playlist[.!?]*$", re.I),
     lambda m: _delete_playlist(m["name"])),
    (re.compile(rf"^{_POLITE}(?:what|which|how many)\s+playlists\s+(?:do\s+)?i\s+have[.!?]*$|^{_POLITE}(?:list|show)\s+(?:me\s+)?my\s+playlists[.!?]*$", re.I),
     lambda m: ("manage_playlist", {"action": "list"})),
    # playlists: songs inside / remove by number / shuffle
    (re.compile(rf"^{_POLITE}(?:what(?:'s| is| are)?|which songs are|list|show(?: me)?|read(?: out)?|tell me)\s+"
                rf"(?:all\s+)?(?:the\s+)?(?:songs\s+)?(?:(?:is|are)\s+)?(?:in|on|inside|of)?\s*(?:my|the)\s+"
                rf"(?P<name>[\w\s'-]+?)\s+playlist(?:\s+songs)?[.!?]*$", re.I),
     lambda m: _playlist("songs", m["name"])),
    (re.compile(rf"^{_POLITE}(?:remove|delete|take out)\s+(?:the\s+)?(?:song\s+|number\s+|track\s+)?"
                rf"(?P<n>\d+|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last)"
                rf"(?:st|nd|rd|th)?(?:\s+(?:song|track|one))?\s+(?:from|in|of)\s+(?:my\s+|the\s+)?"
                rf"(?P<name>[\w\s'-]+?)(?:\s+playlist)?[.!?]*$", re.I),
     lambda m: _playlist_remove(m["name"], m["n"])),
    (re.compile(rf"^{_POLITE}(?:shuffle|mix)\s+(?:up\s+)?(?:my\s+|the\s+)?(?P<name>[\w\s'-]+?)\s+playlist[.!?]*$|"
                rf"^{_POLITE}play\s+(?:my\s+|the\s+)?(?P<name2>[\w\s'-]+?)\s+playlist\s+(?:on\s+|in\s+)?"
                rf"(?:shuffle|shuffled|random(?:\s+order)?|mixed)[.!?]*$|"
                rf"^{_POLITE}play\s+(?:my\s+|the\s+)?(?P<name3>[\w\s'-]+?)\s+(?:on\s+|in\s+)shuffle[.!?]*$", re.I),
     lambda m: _playlist("shuffle", m["name"] or m["name2"] or m["name3"])),
    (re.compile(rf"^{_POLITE}(?:shuffle|shuffle it|shuffle the (?:music|songs|queue)|mix (?:it|them|the songs) up|"
                rf"mix up the songs|shuffle mode|turn on shuffle)[.!?]*$", re.I),
     lambda m: ("music_control", {"action": "shuffle"})),
    # timers / alarms / reminders: list
    (re.compile(rf"^{_POLITE}(?:what|which|how many|do i have any)\s+(?P<k>timers?|alarms?|reminders?)\s*(?:do\s+i\s+have|are\s+(?:set|there|running))?(?:\s+set)?[.!?]*$", re.I),
     lambda m: ("manage_reminders", {"action": "list", "kind": m["k"].lower().rstrip("s")})),
    # time / date
    (re.compile(rf"^{_POLITE}(?:what(?:'s| is)?\s+(?:the\s+)?time(?:\s+(?:is it|now|right now))?|what time is it(?:\s+now)?)[.!?]*$", re.I),
     lambda m: ("get_time", {"what": "time"})),
    (re.compile(rf"^{_POLITE}(?:what(?:'s| is)?\s+(?:the|today's)\s+date(?:\s+today)?|what day is (?:it|today)(?:\s+today)?)[.!?]*$", re.I),
     lambda m: ("get_time", {"what": "date"})),
    # news (headlines are read out by a template; no LLM sees them)
    (re.compile(rf"^{_POLITE}(?:what's|what is|tell me|give me|read me|read|any)?\s*(?:the\s+)?(?:latest\s+|today's\s+|top\s+)?"
                rf"(?:news|headlines)(?:\s+today)?[.!?]*$", re.I),
     lambda m: ("get_news", {"topic": ""})),
    (re.compile(rf"^{_POLITE}(?:what's|what is|tell me|give me|read me|any)?\s*(?:about\s+)?(?:the\s+)?(?:latest\s+)?"
                rf"(?:news|headlines)\s+(?:about|on|in|from)\s+(?P<t>[\w\s'&-]{{2,40}}?)[.!?]*$", re.I),
     lambda m: ("get_news", {"topic": m["t"]})),
    # "what's the latest AI news", "any cricket news today" (then "tell me more about the first one" -> google_it)
    (re.compile(rf"^{_POLITE}(?:what's|what is|tell me|give me|read me|any)?\s*(?:about\s+)?(?:the\s+)?"
                rf"(?:latest\s+|today's\s+|recent\s+|top\s+)?(?P<t>(?!the\b|any\b|some\b|more\b)[\w'&-]+(?:\s+[\w'&-]+){{0,3}}?)\s+"
                rf"(?:news|headlines)(?:\s+today)?[.!?]*$", re.I),
     lambda m: None if _NOT_NEWS_TOPIC.search(m["t"]) else ("get_news", {"topic": m["t"]})),
    # routines
    (re.compile(r"^(?:good morning|morning)(?:\s+(?:momo|master))?[.!?]*$", re.I),
     lambda m: ("run_routine", {"name": "good_morning"})),
    (re.compile(r"^(?:good ?night)(?:\s+(?:momo|master))?[.!?]*$", re.I),
     lambda m: ("run_routine", {"name": "good_night"})),
    # memory
    (re.compile(rf"^{_POLITE}remember[\s,]+(?:that[\s,]+)?(?P<fact>.{{4,}}?)[.!?]*$", re.I),
     lambda m: ("remember", {"fact": _third_person(m["fact"])})),
]
_TIMER = re.compile(rf"^{_POLITE}(?:set|start|put)?\s*(?:a|an|the)?\s*(?:timer\s+(?:for|of)\s+(?P<a>.+?)|"
                    rf"(?P<b>.+?)\s+timer)[.!?]*$", re.I)


def _third_person(fact: str) -> str:
    f = " " + fact.strip().rstrip(".") + " "
    for a, b in ((" my ", " the user's "), (" I am ", " the user is "), (" I'm ", " the user is "),
                 (" I ", " the user "), (" me ", " the user "), (" mine ", " the user's ")):
        f = re.sub(a, b, f, flags=re.I)
    f = f.strip()
    return f[:1].upper() + f[1:]


def fast_path(text: str):
    t = text.strip()
    for pattern, build in FAST_PATHS:
        m = pattern.match(t)
        if m and (found := build(m)):
            return found
    m = _TIMER.match(t)
    if m:
        dur = m["a"] or m["b"]
        if parse_duration(dur):
            return "set_timer", {"duration": words_to_numbers(dur)}
    return None


# ---------------------------------------------------------------- 1b. router helpers
ACTION_RE = re.compile(r"\b(play|add|remove|delete|create|stop|pause|resume|skip|next|previous|louder|quieter|"
                       r"volume|mute|shuffle|weather|rain|umbrella|temperature|forecast|timer|alarm|remind|reminder|"
                       r"list|calculate|convert|remember|forget|wake me|email|e-mail|mail|news|look up|search|open|launch|watch|calendar|event|appointment|meeting|schedule)\b", re.I)
RETRY_NUDGE = "The user's last message is a command. Call the single tool that performs it."
_STOP_WORDS = re.compile(r"\b(stop|pause|shut|off|quiet|silence|enough|kill|end|halt|hold|mute|turn it off|no more)\b", re.I)
_PLAY_FALLBACK = re.compile(rf"^{_POLITE}(?:play|put on)\s+(?:me\s+)?(?:some\s+)?(?P<q>.+?)[.!?]*$", re.I)
_DIFFERENT = re.compile(r"\b(another|different|something else|other|not this one|not this|else)\b", re.I)


def _state_line() -> str:
    music_state = {"playing": "a song is playing", "paused": "a song is paused", "stopped": "no music is playing"}
    names = playlist_names()
    return (f"CURRENT STATE: Momo's music: {music_state[player.state()]}. "
            f"Saved playlists: {', '.join(names) if names else 'none'}.")


_EMAIL_WORDS = re.compile(r"\b(e-?mail|mail|send|write)\b", re.I)
_APPROVE_WORDS = re.compile(r"^(?:yes|yeah|yep|sure|ok(?:ay)?|send(?: it)?(?: now)?|approve(?:d)?|i approve|go ahead|"
                            r"confirm(?:ed)?|do it)(?:[\s,]+(?:momo|master|please|send it|it|now))*[.!?]*$", re.I)
_CANCEL_EMAIL = re.compile(r"\b(?:cancel|discard|delete|don'?t send|do not send|scrap)\b.*\b(?:e-?mail|mail|it|that)\b", re.I)


def _grounded(phrase: str, texts: list) -> bool:
    """Data minimisation: what goes out in a web query must come from the user's own recent words,
    not from Momo's memory of them (facts, names) or from anything the model made up."""
    words = [w for w in re.findall(r"[a-z0-9]+", phrase.lower()) if len(w) > 2]
    pool = set(re.findall(r"[a-z0-9]+", " ".join(texts).lower()))
    if not words:
        return True
    hit = sum(1 for w in words if w in pool or difflib.get_close_matches(w, pool, n=1, cutoff=0.75))
    return hit / len(words) >= 0.5


_FILLER = set("yes yeah yep sure ok okay please do that it go ahead look up search find out momo master a the and for "
              "me can you haan ha ji".split())
# "I had a good day at work" / "tell me a joke" are conversation: never a lookup, whatever the router says
_CHAT_ONLY = re.compile(r"^(?:i|i'm|im|i am|i've|i was|i had|i feel|i think|my|we|today was|it was)\b|"
                        r"\b(?:tell|say|make)\s+(?:me\s+|us\s+)?(?:a|another|some|one more)\s+"
                        r"(?:joke|poem|riddle|story|pun|shayari)s?\b", re.I)
_ASKS = re.compile(r"\?|\b(?:who|what|when|where|which|why|how|look (?:it )?up|search|google|find out|tell me about|"
                   r"know about|wonder|news)\b", re.I)


def _content_words(text: str) -> int:
    """Meaningful words: "Yes, do that." -> 0, "who created naruto" -> 2."""
    return len([w for w in re.findall(r"[a-z]+", text.lower()) if w not in _FILLER])


def _guard(calls: list, text: str, blocked: list, recent_user=(), heard=()) -> list:
    """Drop tool calls that can't be what the user meant (they're reported in `blocked`, so the reply is honest).
    `heard` = headlines Momo just read aloud: "tell me more about that story" may search for their words."""
    out = []
    for c in calls:
        a = c.get("args") or {}
        for k in [k for k, v in a.items() if isinstance(v, str) and v.strip().lower() in ("none", "null", "n/a")]:
            a[k] = ""                                 # the router writes "none" for empty arguments
        if c["name"] in ("get_info", "get_news", "google_it") and a.get("topic") and \
                not _grounded(a["topic"], [text, *recent_user, *(heard if c["name"] == "google_it" else ())]):
            print(f"[guard] ignored {c['name']}({a}): topic not from the user's words")
            blocked.append({"name": c["name"], "args": a, "result": "NOT done; nothing was looked up."})
            continue
        if c["name"] == "set_reminder" and a.get("text") and \
                not _grounded(a["text"], [text, CONTEXT.get("followup_of", "")]):
            print(f"[guard] set_reminder: {a['text']!r} isn't in the user's words; asking instead")
            a["text"] = ""                            # -> "What should I remind you about?"
        if c["name"] in ("get_info", "google_it") and _CHAT_ONLY.search(text) and not _ASKS.search(text):
            print(f"[guard] ignored {c['name']}({a}): this is conversation, not a question")   # llama3.1 does this
            continue                                  # not "blocked": Momo just chats
        if c["name"] in ("get_info", "google_it"):
            # relevance ranking uses the user's words; "yes" / "do that" (after "shall I look it up?") -> the topic
            a["question"] = text if _content_words(text) >= 2 else f"tell me about {a.get('topic', '')}"
        if c["name"] == "open_entertainment" and not _SITE_WORDS.search(text):
            print(f"[guard] ignored open_entertainment({a}): the user didn't name the site")
            blocked.append({"name": c["name"], "args": a, "result": "NOT done; no website was opened."})
            continue
        if c["name"] == "open_entertainment" and not re.search(r"\b(brave|chrome|edge)\b", text, re.I):
            a["browser"] = "default"
        if c["name"] == "draft_email":
            to = (a.get("to") or "").strip().lower()
            said = text.lower()
            ok_to = (re.search(r"\b(me|myself|my)\b", said) if to in ("me", "myself") else to and to in said)
            if not _EMAIL_WORDS.search(text) or not ok_to:
                print(f"[guard] ignored draft_email({a}): the user didn't ask to email {to or 'anyone'}")
                blocked.append({"name": "draft_email", "args": {"to": a.get("to", "")},
                                "result": "NOT done; no email was written. Ask who it is for and what it should say."})
                continue
        if c["name"] == "music_control" and a.get("action") in ("stop", "pause") and not _STOP_WORDS.search(text):
            print(f"[guard] ignored {c['name']}({a}): the user never asked to stop the music")
            blocked.append({"name": c["name"], "args": a, "result": "NOT done (unclear request); the music is still playing."})
            continue
        if c["name"] == "forget" and not re.search(r"\b(forget|erase|delete .*(memory|fact)|don'?t remember)\b", text, re.I):
            print(f"[guard] ignored forget({a}): the user never asked to forget anything")
            blocked.append({"name": "forget", "args": a, "result": "NOT done; nothing was forgotten."})
            continue
        if c["name"] == "play_music" and a.get("playlist") and \
                not re.search(r"\b" + re.escape(a["playlist"].lower().replace(" playlist", "")) + r"\b", text.lower()):
            print(f"[guard] play_music: the user never named playlist {a['playlist']!r}")
            a["query"], a["playlist"] = a.get("query") or a["playlist"], ""
            if not re.search(r"\bplaylist\b", text, re.I):
                a["query"] = _PLAY_FALLBACK.match(text)["q"] if _PLAY_FALLBACK.match(text) else a["query"]
        if c["name"] == "play_music":
            # the small router likes to invent these flags; decide them from the user's words
            a["different"] = bool(_DIFFERENT.search(text))
            a["shuffle"] = bool(a.get("playlist")) and bool(re.search(r"\b(shuffle|random|mix it)\b", text, re.I))
        out.append(c)
    return out


def _fallback(text: str):
    """The router skipped an obvious 'play X'."""
    m = _PLAY_FALLBACK.match(text)
    if not m:
        return []
    q = re.sub(r"\b(another|a different|some other|other)\s+", "", m["q"], flags=re.I).strip()
    q = re.sub(r"[,.]?\s*(not|except)\s+this( one)?$", "", q, flags=re.I).strip()
    if re.fullmatch(r"(it|that|music|a song|something|anything|something else|one|that again|it again)", q, re.I):
        return [{"name": "play_music", "args": {"different": bool(_DIFFERENT.search(text))}}]
    return [{"name": "play_music", "args": {"query": q, "different": bool(_DIFFERENT.search(text))}}]


# ---------------------------------------------------------------- 3a. templated confirmations
ACKS = [f"Yes, {T}.", f"Right away, {T}.", f"Of course, {T}.", f"As you wish, {T}.", f"Done, {T}.", f"Certainly, {T}."]
INFO_TOOLS = {"get_time", "calculate", "convert_units", "get_news"}
CALENDAR_SHOW = lambda name, args: name == "manage_calendar" and args.get("action", "show") == "show"
NEEDS_LLM = {"get_weather"}
_FAIL = re.compile(r"^(error|there's no|nothing is|i couldn't|i can't|you can't|timers can|that song is already|"
                   r"the .+ playlist is empty|i had nothing|.+ already on your)", re.I)


def _is_info(name, args):
    return name in INFO_TOOLS or (args.get("action", "show") in ("list", "show", "songs") and name in
                                  ("manage_playlist", "manage_list", "manage_reminders", "manage_calendar"))


def template_reply(name: str, args: dict, result: str) -> str:
    r = result.strip()
    if r.startswith(config.USER_TITLE_HI):                     # already a Hindi sentence (Hindi news)
        return r
    if r.startswith("error"):
        return f"I'm sorry, {T}, that didn't work. Could you say it again?"
    if r.endswith("?"):                                       # the tool needs more info: ask
        return f"{r[:-1]}, {T}?"
    if _FAIL.match(r):
        return f"I'm sorry, {T}. {r}" if T not in r else f"I'm sorry. {r}"
    if name == "draft_email":
        return r                                               # already a full sentence that says "Master"
    if name == "remember":
        return random.choice([f"I'll remember that, {T}.", f"Noted, {T}. I won't forget.", f"Understood, {T}. I'll keep that in mind."])
    if name == "run_routine":
        if args.get("name") == "good_morning":
            return f"Good morning, {T}. {r}"
        return f"Good night, {T}. {r} Sleep well."
    if _is_info(name, args):
        r = r if r.endswith((".", "!")) else r + "."
        return f"{T}, {r[:1].lower()}{r[1:]}" if not r.startswith(("I", "Your")) else f"{r.rstrip('.!')}, {T}."
    return f"{random.choice(ACKS)} {r}"


# ---------------------------------------------------------------- 3b. responder
_EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿⬀-⯿️]")


def clean_reply(text: str) -> str:
    """Make LLM output safe and pleasant for the voice engine."""
    text = _EMOJI.sub("", text)
    text = re.sub(r"\*[^*]{0,80}\*", "", text)                     # *stage directions*
    text = re.sub(r"\[[^\]]*\]|\([^)]*tool[^)]*\)", "", text)       # [tags], leaked "(tool results...)"
    text = re.sub(r"^\s*momo\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"[#_`>~|]", "", text)
    text = re.sub(r"\s+", " ", text).strip().strip('"')
    sentences = re.split(r"(?<=[.!?।])\s+", text)
    text = " ".join(sentences[:4])
    return text[:1].upper() + text[1:]


def _norm(s):
    return re.sub(r"[^a-z ]", "", s.lower()).strip()


def _tool_note(tools: list) -> str:
    return "\n".join(f"- {t['name']}({', '.join(f'{k}={v!r}' for k, v in t['args'].items() if v not in ('', None, -1, False))})"
                     f" -> {t['result']}" for t in tools)


def _history(session_id, for_router=False):
    """Recent turns as chat messages. A user turn carries what Momo's tools did for it, so the model
    knows what "it", "that playlist" or "another one" refer to. Replies that were built from web data are
    hidden from the router (it has tools; web text must never steer it)."""
    out = []
    for m in get_recent_messages(session_id, config.HISTORY_LIMIT):
        if m["role"] == "user":
            tools = json.loads(m["tools"]) if m.get("tools") else []
            out.append(HumanMessage(m["content"] + (f"\n(Momo's tools did:\n{_tool_note(tools)})" if tools else "")))
        elif for_router and m.get("tools") and json.loads(m["tools"]).get("external"):
            out.append(AIMessage("(Momo answered using web data; the text is hidden from you.)"))
        else:
            out.append(AIMessage(m["content"]))
    return out


def _safe_output(reply: str) -> str:
    """Last check on replies built from web data: no links, addresses or instruction-like sentences."""
    keep = [s for s in re.split(r"(?<=[.!?])\s+", reply)
            if not re.search(r"https?://|www\.|[\w.+-]+@[\w-]+\.\w", s) and not suspicious(s)]
    return " ".join(keep)


# ---------------------------------------------------------------- Hindi mode
# Pure Hindi in, Hindi out. The Hindi words are translated to English first, so every fast path, guard, tool and
# safety rule works exactly as in English mode; then Momo answers in Hindi (the responder writes Hindi itself,
# short templated confirmations are translated).
TH = config.USER_TITLE_HI
TO_ENGLISH = ("Translate the user's Hindi (or Hinglish) voice command into simple English. Keep the names of songs, "
              "films, artists, people, apps and playlists as they sound, in Latin letters (केसरिया -> Kesariya, "
              "अरिजीत सिंह -> Arijit Singh, नेटफ्लिक्स -> Netflix). Keep numbers and times. कल with a future plan means "
              "tomorrow, परसों = day after tomorrow. Output ONLY the English sentence.")
TO_HINDI = (f"Translate this reply from Momo (a female assistant) to her master into simple, natural spoken Hindi in "
            f"Devanagari. Translate the meaning faithfully: add nothing, drop nothing. Call the user {TH}. Momo uses "
            "feminine verbs for herself (करूँगी, रही हूँ). Keep names of songs, films and people unchanged. Write "
            "numbers as digits.\nExample: \"I'm sorry, Master. I couldn't find that song.\" -> "
            f"\"माफ़ कीजिए, {TH}। मुझे वह गाना नहीं मिला।\"\nOutput ONLY the Hindi translation.")
HINDI_REPLY = (f"LANGUAGE: Reply ONLY in natural spoken Hindi, in Devanagari script (no English sentences). "
               f"Call the user {TH} instead of {T}. You are female: use feminine verb forms for yourself.")
SMALL_TALK_HI = [
    (re.compile(r"^(?:नमस्ते|नमस्कार|हेलो|हैलो|हाय|हे|namaste|namaskar|hello|hi|hey)(?:\s+(?:मोमो|momo))?[।.!?]*$", re.I),
     [f"नमस्ते, {TH}। बताइए, मैं क्या कर सकती हूँ?", f"जी, {TH}। मैं यहाँ हूँ।"]),
    (re.compile(r"^(?:बहुत\s+|bahut\s+)?(?:धन्यवाद|शुक्रिया|थैंक\s?यू|थैंक्स|dhanyavaad|dhanyawad|shukriya|thank you|thanks)"
                r"(?:\s+(?:मोमो|बहुत\s+बहुत|momo|bahut bahut))?[।.!?]*$", re.I),
     [f"आपका स्वागत है, {TH}।", f"हमेशा आपकी सेवा में, {TH}।"]),
    (re.compile(r"^(?:तुम|आप)\s+कौन\s+(?:हो|हैं)[।.!?]*$|^(?:तुम्हारा|आपका)\s+नाम\s+क्या\s+है[।.!?]*$|"
                r"^(?:tum|aap)\s+(?:kaun|kon|koun)\s+(?:ho|hain)[.!?]*$|^(?:tumhara|aapka)\s+naam\s+kya\s+hai[.!?]*$", re.I),
     [f"मैं मोमो हूँ, {TH}, आपकी निजी सहायक। मैं इसी कंप्यूटर पर रहती हूँ।"]),
    (re.compile(r"^(?:तुम|आप)\s+(?:कैसी|कैसे)\s+(?:हो|हैं)(?:\s+मोमो)?[।.!?]*$|^क्या\s+हाल\s+है[।.!?]*$|"
                r"^(?:tum|aap)\s+(?:kaisi|kaise)\s+(?:ho|hain)(?:\s+momo)?[.!?]*$|^kya\s+haal\s+hai[.!?]*$", re.I),
     [f"मैं ठीक हूँ, {TH}। आप कैसे हैं?"]),
]
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def _mostly_hindi(text: str) -> bool:
    letters = re.findall(r"[A-Za-z\u0900-\u097F]", text)
    return bool(letters) and len(_DEVANAGARI.findall(text)) / len(letters) > 0.6


def _translate(prompt: str, text: str) -> str:
    out = translator.invoke([SystemMessage(prompt), HumanMessage(text)]).content.strip().strip('"')
    return re.sub(r"\s+", " ", out.splitlines()[0] if out else "").strip()


def respond(user_input: str, session_id: str, lang: str | None = None) -> dict:
    """Return {"reply", "tools", "text"} for one user turn, in the current language mode."""
    if (lang or LANG["code"]) != "hi":
        return _respond(user_input, session_id)
    t0 = time.perf_counter()
    raw = user_input.strip()
    for pattern, replies in SMALL_TALK_HI:
        if pattern.match(raw):
            reply = random.choice(replies)
            add_message(session_id, "user", raw)
            add_message(session_id, "assistant", reply, model="template")
            return {"reply": reply, "tools": [], "text": raw}
    plain = _WAKE.sub("", raw).strip()
    rule = hinglish(plain)                         # "gaana band karo", "Kesariya bajao": exact rules first
    english = rule if rule != plain else _translate(TO_ENGLISH, raw)   # else the LLM (Devanagari or romanised)
    print(f"[hindi] {raw!r} -> {english!r} ({time.perf_counter() - t0:.1f}s)")
    out = _respond(english or raw, session_id, hindi=True)
    if not out.get("localized") and not _mostly_hindi(out["reply"]):
        t1 = time.perf_counter()
        out["reply"] = _translate(TO_HINDI, out["reply"]) or out["reply"]
        print(f"[hindi] reply translated ({time.perf_counter() - t1:.1f}s)")
    out["heard"] = raw
    return out


def _respond(user_input: str, session_id: str, hindi: bool = False) -> dict:
    """One turn in English (Hindi mode calls this with the translated text and hindi=True)."""
    t0 = time.perf_counter()
    text = normalize(user_input) or user_input
    history = _history(session_id)
    router_history = _history(session_id, for_router=True)
    recent_user = [m.content.split("\n(Momo's tools did")[0] for m in history if isinstance(m, HumanMessage)][-3:]
    last_ai = next((m.content for m in reversed(history) if isinstance(m, AIMessage)), "")
    CONTEXT["followup_of"] = recent_user[-1] if recent_user and last_ai.rstrip().endswith("?") else ""
    CONTEXT["session_id"] = session_id
    CONTEXT["lang"] = "hi" if hindi else "en"
    timings = {}

    # 0. an email is waiting: voice can never approve it, only discard it
    waiting = outbox.pending()
    if waiting and _APPROVE_WORDS.match(text):
        reply = (f"For your safety, {T}, I can only send an email when you press Approve on my screen. "
                 "It's waiting there for you.")
        add_message(session_id, "user", text)
        add_message(session_id, "assistant", reply, model="template")
        return {"reply": reply, "tools": [], "text": text}
    if waiting and _CANCEL_EMAIL.search(text):
        n = outbox.cancel_pending()
        reply = f"Done, {T}. I've discarded the email." if n == 1 else f"Done, {T}. I've discarded {n} emails."
        add_message(session_id, "user", text)
        add_message(session_id, "assistant", reply, model="template")
        return {"reply": reply, "tools": [], "text": text}

    # 0b. hello / thank you / who are you: a ready answer, no LLM call
    canned = small_talk(text)
    if canned:
        add_message(session_id, "user", text)
        add_message(session_id, "assistant", canned, model="template")
        print(f"[momo] {int((time.perf_counter() - t0) * 1000)} ms | instant reply")
        return {"reply": canned, "tools": [], "text": text}

    # 1-2. route + run tools (one round, at most 2 calls)
    done, blocked = [], []
    try:
        last_user = next((m.content for m in reversed(history) if isinstance(m, HumanMessage)), "")
        story = _news_followup(text, last_user)              # "tell me more about the first one"
        fast = story or fast_path(text)
        if fast:
            calls = [{"name": fast[0], "args": fast[1]}]
        else:
            msgs = [SystemMessage(ROUTER_PROMPT + "\n\n" + _state_line()), *router_history[-6:], HumanMessage(text)]
            decision = router.invoke(msgs)
            if not decision.tool_calls and ACTION_RE.search(text):
                # Small models sometimes skip the tool on short commands; nudge once.
                decision = router.invoke(msgs[:-1] + [SystemMessage(RETRY_NUDGE), msgs[-1]])
            heard = [last_ai] if "- get_news(" in last_user else []     # Momo just read headlines aloud
            calls = _guard(decision.tool_calls, text, blocked, recent_user, heard) or ([] if blocked else _fallback(text))
        timings["router"] = time.perf_counter() - t0
        for call in calls[:2]:
            result = run_tool(call["name"], call["args"])
            if call["name"] == "get_info" and config.SEARCH_ENABLED and not EXTERNAL_BLOCK.search(str(result)) \
                    and "can't look that up" not in result:      # the encyclopedia had nothing: search the web
                web = run_tool("google_it", call["args"])
                if EXTERNAL_BLOCK.search(str(web)):
                    print(f"[tool] get_info -> {result} ... searched the web instead")
                    call, result = {"name": "google_it", "args": call["args"]}, web
            elif call["name"] == "google_it" and not story and not EXTERNAL_BLOCK.search(str(result)) \
                    and call["args"].get("topic"):                    # (today's news isn't in the encyclopedia)
                wiki = run_tool("get_info", call["args"])             # search busy / nothing found: the encyclopedia
                if EXTERNAL_BLOCK.search(str(wiki)):
                    print(f"[tool] google_it -> {result} ... used the encyclopedia instead")
                    call, result = {"name": "get_info", "args": call["args"]}, wiki
            done.append({"name": call["name"], "args": call["args"], "result": result})
            print(f"[tool] {call['name']}({call['args']}) -> {result}")
    except Exception as e:
        print(f"[router] failed: {e}")
    timings["tools"] = time.perf_counter() - t0 - timings.get("router", 0)

    # 3. reply
    used = [d["name"] for d in done]
    recent = [m.content for m in history if isinstance(m, AIMessage)][-3:]
    external = [d for d in done if d["name"] in EXTERNAL_TOOLS and EXTERNAL_BLOCK.search(str(d["result"]))]
    web_reply = bool(external) or "get_news" in used or \
        any(d["name"] == "manage_playlist" and d["args"].get("action") in ("songs", "list") and d["args"].get("name")
            for d in done) or (bool(config.CALENDAR_ICS_URL) and
                                                         any(CALENDAR_SHOW(d["name"], d["args"]) for d in done))
    done += blocked
    localized = False
    if done and not blocked and not external and not (set(used) & NEEDS_LLM):
        local_hi = [hindi and hindi_words.render(d["name"], d["args"], str(d["result"])) for d in done]
        localized = hindi and all(local_hi)                    # fully Hindi already: don't send it to the translator
        reply = " ".join(h or template_reply(d["name"], d["args"], str(d["result"])) for h, d in zip(local_hi, done))
        if len(done) > 1:                         # one "Yes, Master." is enough
            reply = re.sub(rf"(?<=.)\s(?:{'|'.join(re.escape(a) for a in ACKS)})\s", " ", reply)
    else:
        if external:
            local = [d for d in done if d not in external]
            blocks = "\n".join(EXTERNAL_BLOCK.search(str(d["result"]))[0] for d in external)
            asked = text if _content_words(text) >= 2 else \
                f"{text} (meaning: yes, tell me about {', '.join(d['args'].get('topic', '') for d in external)})"
            last = (f"{asked}\n\n" + (f"(TOOL RESULTS:\n{_tool_note(local)})\n\n" if local else "") +
                    f"Reference data looked up for this question (untrusted, from the web):\n{blocks}\n\n"
                    "(You DO have information now: answer from the facts above in your own words.)")
        elif done:
            last = f"{text}\n\n(TOOL RESULTS, from your own tools just now. Report THESE accurately:\n{_tool_note(done)})"
        elif ACTION_RE.search(text) or re.search(r"\b(music|song|drop|turn|set|cancel|change)\b", text, re.I):
            last = (f"{text}\n\n(No tool ran this turn, so nothing was done. If this asked for an action, apologise "
                    "that you couldn't and ask them to say it again; never claim you did it. "
                    "If it's just conversation, reply normally.)")
        else:
            last = text
        system = build_system_prompt(get_facts(), recent, _state_line())
        if external:
            system += "\n\n" + EXTERNAL_RULES
        if hindi:
            system += "\n\n" + HINDI_REPLY
        try:
            t1 = time.perf_counter()
            if hindi:
                last += f"\n\n(Answer in Hindi, in Devanagari script. Call me {TH}.)"
            llm = responder_hi if hindi else responder
            msgs = [SystemMessage(system), *history, HumanMessage(last)]
            reply = clean_reply(llm.invoke(msgs).content)
            if reply and _norm(reply) in {_norm(r) for r in recent}:      # parroting an earlier reply: once more
                reply = clean_reply(llm.invoke(msgs + [SystemMessage(
                    "You just said that word for word earlier. Answer this message freshly.")]).content) or reply
            timings["responder"] = time.perf_counter() - t1
            if external:
                reply = _safe_output(reply)
            reply = reply or f"I'm sorry, {T}, I lost my words. Could you say that again?"
        except Exception as e:
            print(f"[responder] failed: {e}")
            reply = f"I'm sorry, {T}, I can't think right now. Is Ollama running?"

    # 4. memory
    latency = int((time.perf_counter() - t0) * 1000)
    stored = [dict(d, result="looked up on the web (text not kept)") if d in external else d for d in done]
    add_message(session_id, "user", text, tools=json.dumps(stored, ensure_ascii=False, default=str) if stored else None)
    add_message(session_id, "assistant", reply, model=config.OLLAMA_MODEL, latency_ms=latency,
                tools=json.dumps({"external": True}) if web_reply else None)
    steps = " ".join(f"{k}={v:.1f}s" for k, v in timings.items())
    print(f"[momo] {latency} ms ({steps}) | tools={used or '-'}")
    return {"reply": reply, "tools": used, "text": text, "localized": localized}
