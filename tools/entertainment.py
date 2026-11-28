"""Open a streaming site in a browser. That's ALL this tool can do.

Safety:
  * Only the four sites below. The URL comes from this fixed table, never from the LLM or the user's words,
    so Momo can't be talked into opening any other page (no paths, no query strings, no other hosts).
  * Momo only launches the browser. She never reads, clicks, types into or controls the page (no automation,
    no remote-debugging port, nothing comes back from the site).
  * The browser is launched as a plain process with the URL as its only argument (no shell).
"""
import glob
import os
import subprocess

import config

SITES = {   # name -> the only URL Momo may open for it
    "netflix": "https://www.netflix.com/",
    "hotstar": "https://www.hotstar.com/",
    "primevideo": "https://www.primevideo.com/",
    "youtube": "https://www.youtube.com/",
}
NAMES = {"netflix": "Netflix", "hotstar": "Hotstar", "primevideo": "Prime Video", "youtube": "YouTube"}
ALIASES = {"prime": "primevideo", "prime video": "primevideo", "amazon prime": "primevideo", "amazon prime video": "primevideo",
           "disney hotstar": "hotstar", "jiohotstar": "hotstar", "jio hotstar": "hotstar", "you tube": "youtube"}

_BROWSERS = {
    "brave": [r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
              r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"],
    "chrome": [r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
               r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"],
    "edge": [r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
             r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"],
}


def site_key(name: str):
    k = (name or "").lower().strip().removesuffix(".com").replace(".", " ").strip()
    k = ALIASES.get(k, k).replace(" ", "")
    return k if k in SITES else None


def _browser_exe(browser: str):
    for p in _BROWSERS.get(browser, []):
        hits = glob.glob(os.path.expandvars(p))
        if hits:
            return hits[0]
    return None


def open_entertainment(website_name: str, browser: str = "default") -> str:
    T = config.USER_TITLE
    key = site_key(website_name)
    if not key:
        return f"I can only open Netflix, Hotstar, Prime Video or YouTube, {T}."
    url, browser = SITES[key], (browser or "default").lower()
    if browser == "default":
        os.startfile(url)                                         # Windows default browser
        return f"Opening {NAMES[key]}."
    exe = _browser_exe(browser)
    if not exe:
        return f"I couldn't find {browser.capitalize()} on this computer, {T}."
    subprocess.Popen([exe, url], close_fds=True)
    return f"Opening {NAMES[key]} in {browser.capitalize()}."
