"""Local date parsing for spoken phrases: "today", "tomorrow", "day after tomorrow", "friday", "next monday",
"in 3 days", "5 december", "december 5th", "the 12th", "5/12", "next week", and Hinglish "kal", "parso", "aaj".
Always resolves to a date in the future (or today)."""
import re
from datetime import date, datetime, timedelta

_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]
_MON = {m[:3]: i + 1 for i, m in enumerate(_MONTHS)}


def _month(word):
    return _MON.get(word[:3].lower())


def parse_day(text: str, base: date | None = None) -> date | None:
    """The date a phrase refers to, or None if it names no day."""
    from tools.clock import words_to_numbers
    base = base or datetime.now().date()
    t = words_to_numbers((text or "").lower())
    if re.search(r"\b(day after tomorrow|parso|parson)\b", t):
        return base + timedelta(days=2)
    if re.search(r"\b(tomorrow|tmrw|kal)\b", t):
        return base + timedelta(days=1)
    if re.search(r"\b(today|tonight|aaj|this (morning|evening|afternoon))\b", t):
        return base
    m = re.search(r"\bin (\d+) days?\b", t)
    if m:
        return base + timedelta(days=int(m[1]))
    if re.search(r"\bnext week\b", t):
        return base + timedelta(days=7 - base.weekday())                  # next Monday
    m = re.search(r"\b(next|this|coming)?\s*(" + "|".join(_DAYS) + r")\b", t)
    if m:
        ahead = (_DAYS.index(m[2]) - base.weekday()) % 7
        if m[1] == "next" and ahead == 0:
            ahead = 7
        return base + timedelta(days=ahead)
    mon = "|".join(m[:3] + r"\w*" for m in _MONTHS)
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({mon})\b", t) or \
        re.search(rf"\b({mon})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", t)
    if m:
        d, mo = (int(m[1]), _month(m[2])) if m[1].isdigit() else (int(m[2]), _month(m[1]))
        return _future(base, mo, d)
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", t)                         # 5/12 = 5 December (day first)
    if m and 1 <= int(m[2]) <= 12:
        return _future(base, int(m[2]), int(m[1]))
    m = re.search(r"\bthe (\d{1,2})(?:st|nd|rd|th)\b", t)
    if m:
        d = int(m[1])
        mo, y = (base.month, base.year) if d >= base.day else ((base.month % 12) + 1, base.year + (base.month == 12))
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def _future(base, month, day):
    for y in (base.year, base.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            return None
        if d >= base:
            return d
    return None


def say_day(d: date, base: date | None = None) -> str:
    base = base or datetime.now().date()
    if d == base:
        return "today"
    if d == base + timedelta(days=1):
        return "tomorrow"
    if 0 < (d - base).days < 7:
        return f"on {d.strftime('%A')}"
    return f"on {d.strftime('%A')}, {d.day} {d.strftime('%B')}"
