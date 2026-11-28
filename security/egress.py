"""Egress control: what may leave this PC, and to where.

Web requests and emails go through here, never through the LLM. The checks don't depend on what the model
says, so even a manipulated model can't fetch from (or leak data to) a host or mailbox outside the allowlists.

  * safe_get()          https only, host in config.ALLOWED_HOSTS, no redirects to other hosts, size cap,
                        rate limit, a generic User-Agent (nothing about you).
  * clean_query()       data minimisation: what we send in a search is the topic only, with no email
                        addresses, phone or card numbers, at most 80 characters.
  * resolve_recipient() an email can only go to an address listed in config.EMAIL_CONTACTS.
  * safe_get_page()     google_it only: reads ONE page that the search engine returned (never a URL from the LLM).
                        https, port 443, public IP addresses only (no LAN / localhost / router), redirects
                        re-checked, HTML/text only, size cap, rate limit, no cookies, nothing sent but the GET.
"""
import ipaddress
import re
import socket
import threading
import time
from collections import deque
from urllib.parse import urlparse

import requests

import config

from .audit import log_event

USER_AGENT = "MomoLocalAssistant/1.0 (personal voice assistant; read-only)"
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
_SECRETS = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s-]{6,}\d|\b\d{6,}\b|https?://\S+")
_fetches, _lock = deque(), threading.Lock()


class EgressBlocked(Exception):
    """A request or email was stopped by egress control."""


def host_allowed(url: str) -> bool:
    u = urlparse(url)
    return u.scheme == "https" and (u.hostname or "").lower() in config.ALLOWED_HOSTS and not u.username


def _rate_limit():
    with _lock:
        now = time.monotonic()
        while _fetches and now - _fetches[0] > 300:
            _fetches.popleft()
        if len(_fetches) >= config.WEB_MAX_FETCHES:
            raise EgressBlocked("too many web requests in the last 5 minutes")
        _fetches.append(now)


def safe_get(url: str, params=None, timeout=8) -> requests.Response:
    if not host_allowed(url):
        log_event("egress_blocked", f"GET {urlparse(url).hostname}")
        raise EgressBlocked(f"host not allowed: {urlparse(url).hostname}")
    _rate_limit()
    r = requests.get(url, params=params, timeout=timeout, allow_redirects=False, stream=True,
                     headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    if r.is_redirect or r.is_permanent_redirect:              # follow only if the target is allowed too
        target = requests.compat.urljoin(url, r.headers.get("location", ""))
        r.close()
        if not host_allowed(target):
            log_event("egress_blocked", f"redirect to {urlparse(target).hostname}")
            raise EgressBlocked("redirect to a host that is not allowed")
        return safe_get(target, timeout=timeout)
    r.raise_for_status()
    body = r.raw.read(config.WEB_MAX_BYTES + 1, decode_content=True)
    r.close()
    if len(body) > config.WEB_MAX_BYTES:
        raise EgressBlocked("response too large")
    r._content = body                                          # so .json() / .text work
    return r


# Page reads for google_it. A generic browser User-Agent: many news sites refuse unknown bots, and it says nothing
# about you. No cookies are kept (each request is fresh) and no Referer is sent.
PAGE_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
PAGE_MAX_BYTES = 1_500_000


def public_host(host: str) -> bool:
    """True only if every address the name resolves to is a public internet address (blocks SSRF to the LAN)."""
    host = (host or "").lower().rstrip(".")
    if not host or host == "localhost" or host.endswith((".local", ".lan", ".internal", ".home", ".localhost")):
        return False
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global or ip.is_multicast:
            return False
    return bool(infos)


def page_allowed(url: str) -> bool:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    return (u.scheme == "https" and not u.username and not u.password and u.port in (None, 443)
            and host not in config.SEARCH_BLOCKED_HOSTS
            and not any(host.endswith("." + b) for b in config.SEARCH_BLOCKED_HOSTS) and public_host(host))


def safe_get_page(url: str, timeout=6, _hops=0) -> tuple[str, str]:
    """GET one search-result page -> (final_url, decoded text). Raises EgressBlocked / requests errors."""
    if not page_allowed(url):
        log_event("egress_blocked", f"page {urlparse(url).hostname}")
        raise EgressBlocked(f"page not allowed: {urlparse(url).hostname}")
    _rate_limit()
    r = requests.get(url, timeout=timeout, allow_redirects=False, stream=True,
                     headers={"User-Agent": PAGE_USER_AGENT, "Accept": "text/html,text/plain;q=0.9",
                              "Accept-Language": "en"})
    if r.is_redirect or r.is_permanent_redirect:
        target = requests.compat.urljoin(url, r.headers.get("location", ""))
        r.close()
        if _hops >= 3:
            raise EgressBlocked("too many redirects")
        return safe_get_page(target, timeout, _hops + 1)       # the target is checked like the first URL
    r.raise_for_status()
    ctype = r.headers.get("content-type", "").lower()
    if not ctype.startswith(("text/html", "text/plain", "application/xhtml")):
        r.close()
        raise EgressBlocked(f"not a web page ({ctype.split(';')[0] or 'unknown type'})")
    body = r.raw.read(PAGE_MAX_BYTES + 1, decode_content=True)
    r.close()
    if len(body) > PAGE_MAX_BYTES:
        body = body[:PAGE_MAX_BYTES]                           # a long article: the start is enough
    m = re.search(r"charset=([\w-]+)", ctype) or re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4000], re.I)
    enc = (m[1].decode() if isinstance(m[1], bytes) else m[1]) if m else "utf-8"
    try:
        return url, body.decode(enc, errors="replace")
    except LookupError:
        return url, body.decode("utf-8", errors="replace")


def clean_query(text: str) -> str:
    """Only the topic leaves the PC: drop anything that looks like personal data or a link."""
    q = _SECRETS.sub(" ", text or "")
    q = re.sub(r"[^\w\s'&.,:-]", " ", q)
    return re.sub(r"\s+", " ", q).strip()[:80]


def resolve_recipient(to: str):
    """Contact name or address -> (name, address) if it's on the allowlist, else None."""
    key = (to or "").strip().lower().removeprefix("to ").strip()
    if key in ("me", "myself", "my email", "my mail", "my inbox", "my self"):
        key = "me"
    if key in config.EMAIL_CONTACTS:
        addr = config.EMAIL_CONTACTS[key]
        return (key, addr) if _EMAIL_RE.match(addr) else None
    for name, addr in config.EMAIL_CONTACTS.items():
        if key == addr.lower() and _EMAIL_RE.match(addr):
            return name, addr
    return None


def recipient_allowed(address: str) -> bool:
    return any(address.lower() == a.lower() for a in config.EMAIL_CONTACTS.values()) and bool(_EMAIL_RE.match(address))
