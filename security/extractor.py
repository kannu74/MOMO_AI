"""Structured extractor: the ONLY way web text can reach the LLM.

    raw web text --> sanitise --> split into sentences --> drop injection-like sentences
                 --> keep only the few sentences relevant to the question (context minimisation)
                 --> structured record {source, title, kind, retrieved, facts[]}
                 --> <external_data trust="untrusted"> ... </external_data>   (escaped, so it can't close the tag)

No LLM runs here: it's plain code, so a malicious page has nothing to talk to. The LLM that later reads the
record (the responder) has no tools bound, and the record never reaches the router.
"""
import html
import json
import re
import unicodedata
from datetime import date

import config

from .audit import log_event

# Invisible / direction-changing characters used to hide instructions (zero-width, bidi overrides, tag chars).
_HIDDEN = re.compile("[​-‏‪-‮⁠-⁩﻿\U000e0000-\U000e007f]")
_MARKUP = re.compile(r"<[^>]{0,300}>|\{\{.*?\}\}|\[\[|\]\]|```.*?```", re.S)
_LINKS = re.compile(r"https?://\S+|www\.\S+|[\w.+-]+@[\w-]+\.[\w.]+")

# Sentences that talk to an AI instead of describing the topic are dropped, not passed on.
INJECTION = re.compile(r"""
    \b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(instruction|prompt|rule|guideline|above|previous|prior|system)s?\b
  | \b(you\ are\ now|you\ must\ now|from\ now\ on\ you|pretend\ you|roleplay\ as|new\ persona)\b
  | \b(you|assistant|ai)\s+(should|must|will|now)\s+act\s+as\b | \bact\s+as\s+(an?\s+)?(ai|assistant|chatbot|dan|admin|developer)\b
  | \b(system|developer|admin)\s*(prompt|message|mode|override|instruction)s?\b
  | \b(new|updated|hidden|secret|real)\s+instructions?\b
  | \b(assistant|ai|chatbot|language\ model|llm|momo|claude|gpt|qwen)\b.{0,30}\b(must|should|will|shall|need\ to|has\ to)\b
  | \b(send|forward|email|e-mail|mail)\b.{0,40}\b(to|this|the\ user|contacts?|address|password|data|history)\b
  | \b(call|invoke|use|run|execute)\s+(the\s+)?(tool|function|command|api|draft_email|get_info)\b
  | \b(api[\s_-]?key|password|passcode|credentials)\b
  | \b(do\ not|don't|never)\s+(tell|inform|mention|reveal)\b.{0,30}\b(user|master|anyone)\b
  | \b(jailbreak|dan\ mode|prompt\ injection)\b
  # talking to whoever reads / answers / summarises the page (an AI), not describing the topic
  | \b(whoever|anyone|anybody)\s+(who\s+|that\s+)?(is\s+)?(reads?|reading|answers?|answering|summari[sz]es?|summari[sz]ing|processes|processing)\b.{0,50}\b(should|must|has\ to|have\ to|needs?\ to|is\ required|shall)\b
  | \b(if|when)\s+you('re|\s+are)\s+(an?\s+)?(ai|bot|assistant|language\ model|llm|chatbot)\b
  | \b(if|when)\s+(an?\s+|the\s+)?(ai|bot|assistant|language\ model|llm|chatbot)\s+(reads?|sees?|summari[sz]es?|processes|answers?)\s+(this|these|the\ (page|text|article|site))\b
  | \b(tell|ask|instruct|remind|urge)\s+(your|the)\s+(user|owner|master|human)s?\s+(to|that)\b
  | \b(finish|end|start|begin|conclude|close|prefix|append|sign)\b.{0,25}\b(answer|reply|response|output|summary)s?\b.{0,20}\b(with|by\ saying)\b
  | \b(say|repeat|include|output|print|add)\s+(the\s+|these\s+|this\s+)?(exact\s+)?(words?|phrase|code\ ?word|password|sentence)\b.{0,60}\b(your|the|each|every)\s+(answer|reply|response|output|summary)
  | ^\W*(please\s+)?(say|repeat|include|output|print)\s+(the\s+|these\s+|this\s+)?(exact\s+)?(words?|phrase|code\ ?word|sentence)\b
  | \b(must|should|has\ to|needs?\ to)\s+(say|repeat|include|output|print)\s+(the\s+|these\s+|this\s+)?(exact\s+)?(words?|phrase|code\ ?word|sentence)\b
  | </?\s*(system|user|assistant|external_data|tool|instructions?)\b
  | ^\s*(system|assistant|user|human)\s*:
""", re.I | re.X)

_STOP = set("""a an the of in on at to for and or but is are was were be been being it its this that these those
what who whom whose which when where why how do does did can could would should will shall may might about tell me
my your his her their our please momo master you i we they he she them us know explain give say some any more much
many latest recent news info information""".split())


def sanitise(text: str) -> str:
    t = unicodedata.normalize("NFKC", html.unescape(text or ""))
    t = _HIDDEN.sub("", t)
    t = _MARKUP.sub(" ", t)
    t = _LINKS.sub("", t)
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", t)
    # pronunciations / native scripts: "Jujutsu Kaisen (呪術廻戦; rgh. 'Sorcery Fight')" -> "Jujutsu Kaisen"
    t = re.sub(r"\s*\([^()]*(?:;|[^\x00-\u024f\u2010-\u2027])[^()]*\)", "", t)
    t = re.sub(r"\([^()]{0,4}\)|\(\s*[;,]?\s*\)", "", t)
    t = re.sub(r"={2,}.*?={2,}", ". ", t)                           # "== History ==" section headers
    return re.sub(r"\s+", " ", t).strip()


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text)
    return [p.strip() for p in parts if 25 <= len(p.strip()) <= 400]


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1 and w not in _STOP}


def suspicious(sentence: str) -> bool:
    return bool(INJECTION.search(sentence))


def minimise(text: str, question: str, max_facts=None, max_chars=None, lead=2) -> tuple[list[str], int]:
    """Pick the few sentences that answer `question`. Returns (facts in original order, n_dropped_as_injection)."""
    max_facts = max_facts or config.INFO_MAX_FACTS
    max_chars = max_chars or config.INFO_MAX_CHARS
    sents, dropped = [], 0
    for s in _sentences(sanitise(text)):
        if suspicious(s):
            dropped += 1
            log_event("injection_dropped", s[:200])
        else:
            sents.append(s)
    q = _terms(question)
    scored = []
    for i, s in enumerate(sents):
        overlap = len(q & _terms(s))
        score = overlap + (1.5 if i < lead else 0) + (0.5 if re.search(r"\d", s) and overlap else 0)
        scored.append((score, -i, s))
    picked, used = [], 0
    for score, neg_i, s in sorted(scored, reverse=True):
        if len(picked) >= max_facts or (score <= 0 and picked):
            break
        if used + len(s) > max_chars:
            continue
        picked.append((-neg_i, s))
        used += len(s)
    return [s for _, s in sorted(picked)], dropped


def headline(text: str, limit=140):
    """One news title -> a clean, short, speakable line (or None if it's suspicious)."""
    t = sanitise(text)
    if not t or suspicious(t):
        if t:
            log_event("injection_dropped", f"headline: {t[:200]}")
        return None
    return t[:limit].rsplit(" ", 1)[0] + "..." if len(t) > limit else t


def record(source: str, title: str, kind: str, facts: list[str], dropped: int = 0) -> dict:
    return {"source": source, "title": sanitise(title)[:120], "kind": kind,
            "retrieved": date.today().isoformat(), "facts": facts, "suspicious_sentences_removed": dropped}


def wrap(rec: dict) -> str:
    """Record -> the untrusted block the responder sees. Every '<' '>' '&' inside is escaped, so the data
    can never close </external_data> or open a fake <system> tag."""
    body = html.escape(json.dumps({k: rec[k] for k in ("title", "kind", "facts", "sources") if k in rec},
                                  ensure_ascii=False), quote=False)
    return (f'<external_data source="{html.escape(rec["source"])}" retrieved="{rec["retrieved"]}" '
            f'trust="untrusted">\n{body}\n</external_data>')


EXTERNAL_BLOCK = re.compile(r"<external_data\b.*?</external_data>", re.S)
