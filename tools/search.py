"""google_it(topic): search the web and answer from the pages, behind the same security layers as get_info.

    topic (from the user's own words, checked in core._guard)
      -> clean_query()                    only the topic leaves the PC (no emails / numbers / links)
      -> DuckDuckGo lite (allowlisted)    Google's own results page needs JavaScript, so it can't be read
      -> top SEARCH_FETCH_PAGES pages     security.egress.safe_get_page: public https hosts only, size cap,
                                          rate limit; the URLs come from the search engine, never from the LLM
      -> plain-text extraction (here)     scripts, menus, headers, footers and forms dropped
      -> security/extractor.py            sanitise, drop instruction-like sentences, keep the few sentences that
                                          answer the question (context minimisation)
      -> <external_data trust="untrusted">   read only by the responder (no tools); never stored or routed.
"""
import concurrent.futures as cf
import re
import time
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import config
from security import extractor
from security.egress import EgressBlocked, clean_query, page_allowed, safe_get, safe_get_page

T = config.USER_TITLE
_pages = cf.ThreadPoolExecutor(max_workers=4)


# ---------------------------------------------------------------- search engine
_RESULT = re.compile(r"<a[^>]+href=\"([^\"]+)\"[^>]*class='result-link'[^>]*>(.*?)</a>", re.S)
_SNIPPET = re.compile(r"<td class='result-snippet'>(.*?)</td>", re.S)


def _real_url(href: str) -> str:
    """DuckDuckGo wraps links: //duckduckgo.com/l/?uddg=<the real url>. Ads go to /y.js: dropped."""
    href = href.replace("&amp;", "&")
    if href.startswith("//"):
        href = "https:" + href
    u = urlparse(href)
    if u.hostname and u.hostname.endswith("duckduckgo.com"):
        if u.path.startswith("/y.js") or "ad_domain" in u.query:
            return ""
        return unquote(parse_qs(u.query).get("uddg", [""])[0])
    return href


class SearchBusy(Exception):
    """DuckDuckGo answered with its "are you a bot?" page (too many searches from this IP for a while)."""


_cache: dict[str, tuple[float, list]] = {}
CACHE_SEC = 30 * 60


def search(query: str, limit: int | None = None) -> list[dict]:
    """Web results [{title, url, site, snippet}] for a cleaned query (nothing else is sent). Cached 30 min."""
    limit = limit or config.SEARCH_RESULTS
    key = f"{query.lower()}|{limit}"
    if key in _cache and time.time() - _cache[key][0] < CACHE_SEC:
        return _cache[key][1]
    for attempt in range(2):
        r = safe_get(config.SEARCH_URL, {"q": query, "kl": "wt-wt"})
        html_text = r.text
        if r.status_code == 200 and "bots use DuckDuckGo" not in html_text:
            break
        if attempt == 0:
            time.sleep(1.5)                                   # one polite retry
    else:
        raise SearchBusy("the search engine wants me to slow down")
    out = _parse(html_text, limit)
    _cache[key] = (time.time(), out)
    return out


def _parse(html_text: str, limit: int) -> list[dict]:
    links = list(_RESULT.finditer(html_text))
    out, seen = [], set()
    for i, m in enumerate(links):
        url = _real_url(m[1])
        if not url.startswith("https://"):
            continue
        site = (urlparse(url).hostname or "").lower().removeprefix("www.")
        end = links[i + 1].start() if i + 1 < len(links) else len(html_text)
        sn = _SNIPPET.search(html_text, m.end(), end)
        title = extractor.headline(re.sub(r"<[^>]+>", "", m[2]), 160)
        snippet = extractor.headline(re.sub(r"<[^>]+>", "", sn[1]), 400) if sn else None
        if url in seen or not (title or snippet):
            continue
        seen.add(url)
        out.append({"title": title or site, "url": url, "site": site, "snippet": snippet or ""})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- page -> plain text
class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "button", "select",
            "template", "iframe", "figure", "menu", "dialog"}
    BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "tr", "div", "br", "section", "article",
             "blockquote", "dd", "dt", "table", "ul", "ol", "main"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip, self.chunks, self.cur = 0, [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self._flush()

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self._flush()

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if not self.skip:
            self.cur.append(data)

    def _flush(self):
        t = re.sub(r"\s+", " ", "".join(self.cur)).strip()
        self.cur = []
        if t and t[-1] in ".!?":
            self.chunks.append(t)
        elif len(t.split()) >= 8:                       # an unpunctuated line long enough to be a sentence
            self.chunks.append(t + ".")
        # short lines without a full stop are headings, menu items, buttons: not facts

    def text(self) -> str:
        self._flush()
        return " ".join(self.chunks)


def page_text(html_text: str) -> str:
    p = _Text()
    try:
        p.feed(html_text[:600_000])
        p.close()
    except Exception:
        pass
    return p.text()


_NEWSY = re.compile(r"\b(news|headlines?|latest stories|what'?s happening)\b", re.I)
_NEWS_WORDS = re.compile(r"\b(news|headlines?|latest|today'?s?|recent|top|stories|the|any|what'?s happening( in| with)?)\b",
                         re.I)


def _story_results(q: str) -> list[dict]:
    """"cricket news" -> the real stories: today's headlines (Google News, already filtered), each one looked up by
    its title so its article can be read. A plain web search for "X news" only finds news landing pages."""
    from tools.info import headlines_for
    topic = re.sub(r"\s+", " ", _NEWS_WORDS.sub(" ", q)).strip() or "top stories"
    out = []
    for i, h in enumerate(headlines_for(topic, 3)):
        found = []
        try:
            if i:
                time.sleep(0.4)                       # one search at a time: bursts trip DuckDuckGo's bot check
            found = search(clean_query(h["title"]), limit=2)
        except SearchBusy:
            pass
        if found:
            out.append(dict(found[0], headline=h["title"]))
        else:                                       # no article found: at least the headline itself
            out.append({"title": h["title"], "url": "", "site": h["source"] or "news", "snippet": "", "headline": h["title"]})
    return out


def _same(a: str, b: str) -> bool:
    """Near-duplicate sentences (a page title repeated in its breadcrumb, the same fact on two sites)."""
    ta, tb = extractor._terms(a), extractor._terms(b)
    return bool(ta and tb) and len(ta & tb) / min(len(ta), len(tb)) >= 0.7


def _read(result: dict) -> tuple[dict, str]:
    if not result["url"] or not page_allowed(result["url"]) or re.search(r"\.(pdf|docx?|xlsx?|pptx?|zip)(\?|$)", result["url"], re.I):
        return result, ""
    _, body = safe_get_page(result["url"])
    return result, page_text(body)


# ---------------------------------------------------------------- the tool
def google_it(topic: str, question: str = "") -> str:
    q = clean_query(topic)
    if not q:
        return f"What should I search for, {T}?"
    t0 = time.perf_counter()
    try:
        results = []
        if _NEWSY.search(q):
            try:
                results = _story_results(q)
            except Exception as e:
                print(f"[google_it] news stories failed, plain search instead: {type(e).__name__}: {e}")
        results = results or search(q)
    except SearchBusy as e:
        print(f"[google_it] {e}")
        return f"I can't search the web right now, {T}: the search engine wants me to slow down. Please ask again in a minute."
    except EgressBlocked as e:
        return f"I can't search the web right now, {T}: {e}."
    except Exception as e:
        print(f"[google_it] search failed: {type(e).__name__}: {e}")
        return f"I couldn't reach the search engine just now, {T}."
    if not results:
        return f"I couldn't find anything online about {q}, {T}."

    asked = f"{q} {question}"
    want = extractor._terms(asked)
    texts = {}
    futures = [_pages.submit(_read, r) for r in results[:config.SEARCH_FETCH_PAGES]]
    try:
        for f in cf.as_completed(futures, timeout=9):
            try:
                r, text = f.result()
                texts[r["url"]] = text
            except Exception as e:
                print(f"[google_it] page skipped: {type(e).__name__}: {str(e)[:80]}")
    except cf.TimeoutError:
        print("[google_it] slow pages skipped")

    facts, dropped, used = [], 0, 0
    per_page = max(2, config.SEARCH_MAX_FACTS // max(1, min(len(results), config.SEARCH_FETCH_PAGES)))
    for r in results:                                         # search-engine order = relevance
        own = f"{asked} {r.get('headline', '')}"              # a news story is judged against its own headline
        need = want | extractor._terms(r.get("headline", ""))
        picked = []
        if r.get("headline"):
            picked.append(r["headline"])                      # the story's headline, then what its article says
        elif len(r["title"].split()) >= 5 and len(need & extractor._terms(r["title"])) >= 2 and \
                not r["title"].rstrip().endswith("?"):
            picked.append(r["title"])                         # "GTA VI is now set to launch November 19, 2026"
        if texts.get(r["url"]):
            sents, n = extractor.minimise(texts[r["url"]], own, max_facts=per_page + 3, max_chars=1200, lead=0)
            dropped += n
            # nothing off-topic (menus, cookie notices) and no questions ("When is GTA 6 Online coming out?")
            sents = [s for s in sents if need & extractor._terms(s) and not s.rstrip().endswith("?")]
            sents = [s for s in sents if not any(_same(s, p) for p in picked)]   # breadcrumbs / title repeats
            picked += sents[:per_page]
        if len(picked) <= 1 and r["snippet"] and need & extractor._terms(r["snippet"] + " " + r["title"]):
            picked.append(r["snippet"])                       # the page couldn't be read: its search snippet
        for s in picked:
            if len(facts) >= config.SEARCH_MAX_FACTS or used + len(s) > config.SEARCH_MAX_CHARS:
                break
            if any(_same(s, f["text"]) for f in facts):
                continue
            facts.append({"from": r["site"], "text": s})
            used += len(s)
    print(f"[google_it] {q!r}: {len(results)} results, {sum(1 for t in texts.values() if t)} pages read, "
          f"{len(facts)} facts, {dropped} suspicious sentences dropped ({time.perf_counter() - t0:.1f}s)")
    if not facts:
        return f"I couldn't find a clear answer about {q} online, {T}."
    rec = extractor.record("web search", q, "web search results", facts, dropped)
    rec["sources"] = sorted({f["from"] for f in facts})
    return extractor.wrap(rec)
