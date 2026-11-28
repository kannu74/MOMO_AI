"""General knowledge (Wikipedia) and news (Google News RSS), behind the security layers in security/.

get_info(topic, question)  -> an <external_data trust="untrusted"> block with at most INFO_MAX_FACTS sentences that
                              answer the question; only the responder LLM (no tools) reads it.
get_news(topic)            -> headlines read out by a template: no LLM ever sees them.
refresh_news()             -> background fetch for your news domains (DB table news_domains) (the only thing Momo does online by herself).
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import config
from backend.database import connect, now
from security import extractor
from security.egress import EgressBlocked, clean_query, safe_get

T = config.USER_TITLE
WIKI = "https://en.wikipedia.org/w/api.php"


# ---------------------------------------------------------------- knowledge
def get_info(topic: str, question: str = "") -> str:
    q = clean_query(topic)
    if not q:
        return f"What should I look up, {T}?"
    try:
        hits = safe_get(WIKI, {"action": "query", "list": "search", "srsearch": q, "srlimit": 3, "srprop": "",
                               "format": "json", "formatversion": 2}).json()["query"]["search"]
        if not hits:
            return f"I couldn't find anything about {q}, {T}."
        title = hits[0]["title"]
        params = {"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1, "titles": title,
                  "format": "json", "formatversion": 2}
        # the intro is fast (~0.5 s); the full article (slow for big pages) only if the intro lacks the answer
        text = safe_get(WIKI, dict(params, exintro=1)).json()["query"]["pages"][0].get("extract") or ""
        extra = extractor._terms(question) - extractor._terms(q)
        if extra and not extra & extractor._terms(text):
            try:
                text = safe_get(WIKI, params, timeout=12).json()["query"]["pages"][0].get("extract") or text
            except Exception as e:
                print(f"[info] full article failed, using the intro: {type(e).__name__}")
    except EgressBlocked as e:
        return f"I can't look that up right now, {T}: {e}."
    except Exception as e:
        print(f"[info] wikipedia failed: {type(e).__name__}: {e}")
        return f"I couldn't reach the encyclopedia just now, {T}."
    # cut reference sections; they're lists of links, not facts
    text = re.split(r"\n==\s*(References|External links|See also|Notes|Further reading|Bibliography)\s*==", text)[0]
    facts, dropped = extractor.minimise(text, f"{q} {question}")
    if not facts:
        return f"I couldn't find a clear answer about {q}, {T}."
    title = title if not extractor.suspicious(title) else q
    return extractor.wrap(extractor.record("en.wikipedia.org", title, "encyclopedia", facts, dropped))


# ---------------------------------------------------------------- news
def _rss_url(topic: str, lang: str = "en") -> str:
    r = config.NEWS_REGION.upper()
    hl = "hi" if lang == "hi" else f"en-{r}"
    return (f"https://news.google.com/rss/search?q={quote_plus(topic + ' when:2d')}"
            f"&hl={hl}&gl={r}&ceid={r}:{'hi' if lang == 'hi' else 'en'}")


def fetch_headlines(topic: str, limit: int = 6, lang: str = "en") -> list[dict]:
    raw = safe_get(_rss_url(topic, lang)).content
    if re.search(rb"<!DOCTYPE|<!ENTITY", raw[:4000], re.I):      # no entity tricks in our XML parser
        raise ValueError("unexpected DTD in feed")
    out, seen = [], set()
    for item in ET.fromstring(raw).iter("item"):
        title, source = item.findtext("title") or "", item.findtext("source") or ""
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3]
        h, src = extractor.headline(title), extractor.headline(source, 40) or ""
        if not h or h.lower() in seen or " | " in h or len(h.split()) < 5:      # site pages, not stories
            continue
        seen.add(h.lower())
        try:
            pub = parsedate_to_datetime(item.findtext("pubDate")).astimezone(timezone.utc).isoformat(timespec="seconds")
        except Exception:
            pub = ""
        out.append({"title": h, "source": src, "published": pub})
        if len(out) >= 12:
            break
    return sorted(out, key=lambda i: i["published"], reverse=True)[:limit]       # newest first


def _store(topic, items):
    with connect() as conn:
        conn.execute("DELETE FROM news_items WHERE topic = ?", (topic,))
        conn.executemany("INSERT OR IGNORE INTO news_items (topic, title, source, published, fetched_at) "
                         "VALUES (?, ?, ?, ?, ?)", [(topic, i["title"], i["source"], i["published"], now()) for i in items])


def _cached(topic, max_age_min):
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max_age_min)).isoformat(timespec="seconds")
    with connect() as conn:
        rows = conn.execute("SELECT title, source, published FROM news_items WHERE topic = ? AND fetched_at >= ? "
                            "ORDER BY published DESC", (topic, cutoff)).fetchall()
    return [dict(r) for r in rows]


def domains() -> list[str]:
    """The news domains you follow: DB table news_domains (falls back to config.NEWS_TOPICS if it's empty)."""
    try:
        from backend.database import news_domains
        return news_domains() or config.NEWS_TOPICS
    except Exception:
        return config.NEWS_TOPICS


def refresh_news() -> int:
    """Background job: fetch headlines for your liked topics. Never does anything else (no email, no tools)."""
    n = 0
    for topic in domains():
        try:
            items = fetch_headlines(topic)
            _store(topic.lower(), items)
            n += len(items)
        except Exception as e:
            print(f"[news] {topic}: {type(e).__name__}: {e}")
    return n


def headlines_for(topic: str, limit: int, lang: str = "en") -> list[dict]:
    topic = clean_query(topic).lower()
    key = topic if lang == "en" else f"{lang}:{topic}"            # Hindi headlines are cached separately
    items = _cached(key, max(config.NEWS_REFRESH_MIN, 30))
    if not items:
        items = fetch_headlines(topic, lang=lang)
        _store(key, items)
    return items[:limit]


def _say(items, lang="en") -> str:
    via = "स्रोत" if lang == "hi" else "from"
    end = "।" if lang == "hi" else "."
    return " ".join(f"{i['title'].rstrip('.।')}{f', {via} ' + i['source'] if i['source'] else ''}{end}" for i in items)


_HI_TOPIC = {"ai": "एआई", "gaming": "गेमिंग", "tech": "टेक", "marvel": "मार्वल",
             "anime and pop culture": "एनीमे और पॉप कल्चर", "technology": "टेक्नोलॉजी", "india": "भारत", "anime": "एनीमे", "cricket": "क्रिकेट", "sports": "खेल",
             "business": "बिज़नेस", "world": "दुनिया", "entertainment": "मनोरंजन", "science": "विज्ञान"}


LAST_HEADLINES: list[str] = []      # what Momo just read aloud, in order: "tell me more about the second one"


def _offer(hi: bool) -> str:
    """With web search on, offer the full story (ends in "?" so Momo keeps listening for "the first one")."""
    return " Shall I tell you more about one of them?" if config.SEARCH_ENABLED and not hi else ""


def get_news(topic: str = "", lang: str = "en") -> str:
    """Headlines read by a template. In Hindi mode they come from the Hindi edition, with Hindi wording."""
    topic = clean_query(topic)
    hi = lang == "hi"
    TH = config.USER_TITLE_HI
    try:
        if topic and topic.lower() not in ("news", "today", "latest", "headlines", "the news", "top"):
            items = headlines_for(topic, 4, lang)
            name = _HI_TOPIC.get(topic.lower(), topic) if hi else topic
            if not items:
                return f"{TH}, {name} की कोई ताज़ा खबर नहीं मिली।" if hi else f"I found no recent news about {topic}, {T}."
            LAST_HEADLINES[:] = [i["title"] for i in items]
            return (f"{TH}, {name} की ताज़ा खबरें: {_say(items, lang)}" if hi
                    else f"Here's the latest on {topic}: {_say(items)}{_offer(hi)}")
        parts, read = [], []
        topics = domains() or ["top stories"]
        for t in topics:
            items = headlines_for(t, 2 if len(topics) <= 3 else 1, lang)
            if items:
                read += [i["title"] for i in items]
                parts.append(f"{_HI_TOPIC.get(t.lower(), t)}: {_say(items, lang)}" if hi
                             else f"In {t if t.isupper() else t.title()}: {_say(items)}")
        if not parts:
            return f"{TH}, अभी खबरें नहीं मिल पाईं।" if hi else f"I couldn't get any news just now, {T}."
        LAST_HEADLINES[:] = read
        return (f"{TH}, आज की मुख्य खबरें। " if hi else "Here are today's headlines. ") + " ".join(parts) + _offer(hi)
    except EgressBlocked as e:
        return f"I can't fetch news right now, {T}: {e}."
    except Exception as e:
        print(f"[news] failed: {type(e).__name__}: {e}")
        return f"I couldn't reach the news just now, {T}."


def news_digest(limit_per_topic: int = 3) -> str:
    """Plain-text headlines for an email body ("email me today's news")."""
    lines = []
    for t in domains() or ["top stories"]:
        try:
            items = headlines_for(t, limit_per_topic)
        except Exception:
            items = []
        if items:
            lines.append(t.capitalize() + ":")
            lines += [f"  - {i['title']}" + (f" ({i['source']})" if i["source"] else "") for i in items]
    return "\n".join(lines)
