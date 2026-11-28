"""Lyrics of the song that's playing, for the window only (main_ui "♪ Lyrics").

Source: LRCLIB (lrclib.net, free, no account), fetched through security/egress.safe_get. Only the cleaned song
title leaves the PC. Lyrics are web text: they are shown on screen and NEVER put into an LLM prompt or history.
Synced lyrics ([mm:ss.xx] lines) let the window highlight the line being sung.
"""
import re

from security import egress

API = "https://lrclib.net/api/search"
_cache = {}
_NOISE = re.compile(r"\((?:[^)]*(?:official|video|audio|lyric|lyrics|visuali[sz]er|hd|4k|full|song|remaster)[^)]*)\)|"
                    r"\[(?:[^\]]*)\]|\b(?:official\s+(?:music\s+)?video|official\s+audio|lyrics?\s+video|lyrical|"
                    r"full\s+song|full\s+video|video\s+song|audio\s+song|hd|4k)\b|\|.*$|#\S+", re.I)
_LRC = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)$")


def clean_title(title: str) -> str:
    t = _NOISE.sub(" ", title or "")
    t = re.sub(r"\b(?:ft|feat)\.?\s.*$", " ", t, flags=re.I)
    t = re.sub(r"[\"“”]|\s+-\s+topic\b", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", re.sub(r"\s*[-–—:]\s*", " - ", t)).strip(" -")


def _parse(item: dict) -> dict:
    synced = []
    for line in (item.get("syncedLyrics") or "").splitlines():
        m = _LRC.match(line.strip())
        if m:
            synced.append((int(m[1]) * 60 + float(m[2]), m[3]))
    plain = (item.get("plainLyrics") or "").strip() or "\n".join(t for _, t in synced)
    return {"title": f"{item.get('artistName', '')} - {item.get('trackName', '')}".strip(" -"),
            "synced": synced, "plain": plain}


def find(title: str) -> dict | None:
    """{'title', 'synced': [(seconds, line)], 'plain'} for a YouTube title, or None if no lyrics were found."""
    q = clean_title(title)
    if not q:
        return None
    if q in _cache:
        return _cache[q]
    result = None
    try:
        items = egress.safe_get(API, params={"q": q}, timeout=8).json()
        items = [i for i in items if isinstance(i, dict) and not i.get("instrumental")
                 and (i.get("plainLyrics") or i.get("syncedLyrics"))]
        if items:
            items.sort(key=lambda i: not i.get("syncedLyrics"))       # prefer synced lyrics
            result = _parse(items[0])
    except Exception as e:
        print(f"[lyrics] {q!r}: {e}")
        return None                                                    # not cached: may work next time
    _cache[q] = result
    return result
