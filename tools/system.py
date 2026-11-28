"""PC volume and media keys (Tier 0), via Windows virtual key presses (ctypes, no extra dependencies).

Media keys control whatever app owns media playback (Spotify, browser video, ...), not Momo's own music:
that one is `music.music_control`.
"""
import ctypes
import sys
import time

VK = {"volume_mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF,
      "media_next": 0xB0, "media_previous": 0xB1, "media_stop": 0xB2, "media_play_pause": 0xB3}
KEYUP = 0x0002
STEP = 2               # Windows changes the master volume by 2% per key press


def _press(vk: int, times: int = 1):
    if sys.platform != "win32":
        raise RuntimeError("only works on Windows")
    user32 = ctypes.windll.user32
    for _ in range(times):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, KEYUP, 0)
        time.sleep(0.004)


def system_control(action: str, level: int = -1) -> str:
    if action == "volume_up":
        _press(VK["volume_up"], 5); return "Turned the computer volume up."
    if action == "volume_down":
        _press(VK["volume_down"], 5); return "Turned the computer volume down."
    if action == "mute":
        _press(VK["volume_mute"]); return "Toggled mute on the computer."
    if action == "set_volume":
        if not 0 <= int(level) <= 100:
            return "What level should I set the computer volume to?"
        _press(VK["volume_down"], 50)            # to zero, then up in 2% steps
        _press(VK["volume_up"], round(int(level) / STEP))
        return f"Computer volume set to {int(level)} percent."
    if action in VK:
        _press(VK[action])
        return {"media_play_pause": "Pressed play/pause.", "media_next": "Skipped to the next track.",
                "media_previous": "Went back a track.", "media_stop": "Stopped the media."}.get(action, "Done.")
    return "I can't do that on the computer."
