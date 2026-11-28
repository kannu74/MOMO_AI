"""Hindi wording for command confirmations, built locally (no LLM: exact, instant, and the 4B model's Hindi
translations of short sentences were often wrong). Anything not covered here falls back to the translator.

render(tool_name, args, english_result) -> Hindi sentence or None
"""
import re

import config

TH = config.USER_TITLE_HI
DAYS = {"monday": "सोमवार", "tuesday": "मंगलवार", "wednesday": "बुधवार", "thursday": "गुरुवार", "friday": "शुक्रवार",
        "saturday": "शनिवार", "sunday": "रविवार"}
MONTHS = {"january": "जनवरी", "february": "फ़रवरी", "march": "मार्च", "april": "अप्रैल", "may": "मई", "june": "जून",
          "july": "जुलाई", "august": "अगस्त", "september": "सितंबर", "october": "अक्टूबर", "november": "नवंबर",
          "december": "दिसंबर"}
LISTS = {"shopping": "शॉपिंग", "to-do": "टू-डू", "todo": "टू-डू", "grocery": "किराने की"}


def duration(text: str) -> str:
    t = re.sub(r"\bhours?\b", "घंटे", text)
    t = re.sub(r"\bminutes?\b", "मिनट", t)
    t = re.sub(r"\bseconds?\b", "सेकंड", t)
    return t.replace(" and ", " और ")


def clock(text: str) -> str:
    """'7:30 AM tomorrow' -> 'कल सुबह 7:30 बजे', '5 PM on Saturday, 5 December' -> 'शनिवार, 5 दिसंबर को शाम 5 बजे'."""
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)", text, re.I)
    when = ""
    if m:
        h = int(m[1]) % 12 + (12 if m[3].upper() == "PM" else 0)
        part = "सुबह" if 4 <= h < 12 else "दोपहर" if 12 <= h < 16 else "शाम" if 16 <= h < 20 else "रात"
        when = f"{part} {m[1]}{':' + m[2] if m[2] else ''} बजे"
    day = ""
    low = text.lower()
    if "tomorrow" in low:
        day = "कल"
    elif "today" in low:
        day = "आज"
    else:
        d = re.search(r"on (\w+)(?:, (\d{1,2}) (\w+))?", low)
        if d and d[1] in DAYS:
            day = DAYS[d[1]] + (f", {d[2]} {MONTHS.get(d[3], d[3])}" if d[2] else "") + " को"
    return " ".join(p for p in (day, when) if p)


def render(name: str, args: dict, r: str):
    r = r.strip()
    a = args or {}
    if re.match(r"^(error|NOT done)", r):
        return f"माफ़ कीजिए, {TH}, यह नहीं हो पाया। फिर से कहिए?"
    if r == "Nothing is playing.":
        return f"{TH}, अभी कुछ नहीं चल रहा है।"
    if name == "get_time":
        m = re.match(r"It's (\d{1,2}:\d{2}) (AM|PM)", r)
        if m:
            return f"{TH}, अभी {clock(m[1] + ' ' + m[2]).replace(' बजे', '')} बजे हैं।"
        m = re.match(r"Today is (\w+)(?:, (\d{1,2}) (\w+) (\d{4}))?", r)
        if m:
            return f"{TH}, आज {DAYS.get(m[1].lower(), m[1])}" + (
                f", {m[2]} {MONTHS.get(m[3].lower(), m[3])} {m[4]}" if m[2] else "") + " है।"
    if name == "set_timer" and (m := re.match(r"Timer set for (.+?)\.$", r)):
        return f"जी, {TH}। {duration(m[1])} का टाइमर लगा दिया है।"
    if name == "set_alarm" and (m := re.match(r"Alarm set for (.+?)\.$", r)):
        return f"जी, {TH}। {clock(m[1])} का अलार्म लगा दिया है।"
    if name == "set_reminder":
        m = re.match(r"I'll remind you to (.+?) (?:at (.+?)|in (.+?))\.$", r)
        if m:
            when = clock(m[2]) if m[2] else f"{duration(m[3])} में"
            return f"जी, {TH}। मैं आपको {when} याद दिला दूँगी: {m[1]}।"
    if name == "play_music":
        if (m := re.match(r"Playing your (.+?) playlist", r)):
            return f"जी, {TH}। आपकी {m[1]} प्लेलिस्ट चला रही हूँ।"
        if (m := re.match(r"Playing (?:another )?(.+?)\.?$", r)):
            return f"जी, {TH}। {m[1]} बजा रही हूँ।"
    if name == "music_control":
        act = a.get("action")
        if (m := re.search(r"Volume set to (\d+)", r)):
            return f"जी, {TH}। आवाज़ {m[1]} प्रतिशत कर दी है।"
        words = {"stop": "गाना बंद कर दिया है", "pause": "गाना रोक दिया है", "resume": "गाना फिर से चला दिया है",
                 "next": "अगला गाना लगा दिया है", "previous": "पिछला गाना लगा दिया है"}
        if act in words:
            return f"जी, {TH}। {words[act]}।"
    if name == "manage_list" and (m := re.match(r"Added (.+?) to your (.+?) list", r)):
        return f"जी, {TH}। {m[1]} आपकी {LISTS.get(m[2].lower(), m[2])} लिस्ट में जोड़ दिया है।"
    if name == "open_entertainment" and (m := re.match(r"Opening (.+?)(?: in (\w+))?\.$", r)):
        return f"जी, {TH}। {m[1]}{' ' + m[2] + ' में' if m[2] else ''} खोल रही हूँ।"
    if name == "manage_calendar":
        if (m := re.match(r"Added (.+?) to your calendar (.+?)\.$", r)):
            return f"जी, {TH}। {m[1]} आपके कैलेंडर में जोड़ दिया है, {clock(m[2]) or m[2]}।"
        if (m := re.match(r"Your calendar is clear (.+?)\.$", r)):
            return f"{TH}, {clock(m[1]) or m[1]} आपका कैलेंडर खाली है।"
        if (m := re.match(r"(.+?) you have (.+)\.$", r)):
            items = "; ".join(f"{t}" + (f", {clock(tm)}" if tm else "")
                              for t, tm in re.findall(r"([^,]+?)(?: at (\d{1,2}(?::\d{2})? [AP]M))?(?:,|$)", m[2]) if t.strip())
            return f"{TH}, {clock(m[1]) or m[1]} आपके कैलेंडर में: {items}।"
    if name == "remember":
        return f"जी, {TH}। मैं यह याद रखूँगी।"
    if name == "calculate" and (m := re.search(r"(-?[\d,.]+)\.?$", r)):
        return f"{TH}, जवाब है {m[1]}।"
    if name == "manage_playlist" and (m := re.match(r"Added it to (.+?)\.$", r)):
        return f"जी, {TH}। यह गाना {m[1]} प्लेलिस्ट में जोड़ दिया है।"
    return None
