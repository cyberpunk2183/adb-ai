"""Friendly names for the Android key events worth having on a remote."""

from __future__ import annotations

KEYS: dict[str, str] = {
    # navigation
    "home": "KEYCODE_HOME",
    "back": "KEYCODE_BACK",
    "ok": "KEYCODE_DPAD_CENTER",
    "enter": "KEYCODE_ENTER",
    "up": "KEYCODE_DPAD_UP",
    "down": "KEYCODE_DPAD_DOWN",
    "left": "KEYCODE_DPAD_LEFT",
    "right": "KEYCODE_DPAD_RIGHT",
    "menu": "KEYCODE_MENU",
    "search": "KEYCODE_SEARCH",
    "apps": "KEYCODE_ALL_APPS",
    "settings": "KEYCODE_SETTINGS",
    "notifications": "KEYCODE_NOTIFICATION",
    "delete": "KEYCODE_DEL",
    "tab": "KEYCODE_TAB",
    "space": "KEYCODE_SPACE",
    # playback
    "play": "KEYCODE_MEDIA_PLAY",
    "pause": "KEYCODE_MEDIA_PAUSE",
    "playpause": "KEYCODE_MEDIA_PLAY_PAUSE",
    "stop": "KEYCODE_MEDIA_STOP",
    "next": "KEYCODE_MEDIA_NEXT",
    "prev": "KEYCODE_MEDIA_PREVIOUS",
    "forward": "KEYCODE_MEDIA_FAST_FORWARD",
    "rewind": "KEYCODE_MEDIA_REWIND",
    "record": "KEYCODE_MEDIA_RECORD",
    "captions": "KEYCODE_CAPTIONS",
    # sound
    "volup": "KEYCODE_VOLUME_UP",
    "voldown": "KEYCODE_VOLUME_DOWN",
    "mute": "KEYCODE_VOLUME_MUTE",
    # power
    "power": "KEYCODE_POWER",
    "sleep": "KEYCODE_SLEEP",
    "wake": "KEYCODE_WAKEUP",
    # TV specific
    "tv": "KEYCODE_TV",
    "input": "KEYCODE_TV_INPUT",
    "channelup": "KEYCODE_CHANNEL_UP",
    "channeldown": "KEYCODE_CHANNEL_DOWN",
    "guide": "KEYCODE_GUIDE",
    "info": "KEYCODE_INFO",
    "red": "KEYCODE_PROG_RED",
    "green": "KEYCODE_PROG_GREEN",
    "yellow": "KEYCODE_PROG_YELLOW",
    "blue": "KEYCODE_PROG_BLUE",
}

for _digit in range(10):
    KEYS[str(_digit)] = f"KEYCODE_{_digit}"


def resolve(name: str) -> str:
    """Map a friendly name to a keycode. Raw ``KEYCODE_*`` names pass through."""
    key = name.strip().lower().replace("-", "").replace("_", "")
    if key in KEYS:
        return KEYS[key]
    upper = name.strip().upper()
    if upper.startswith("KEYCODE_"):
        return upper
    if upper.isdigit():
        return upper  # a bare numeric keycode
    raise KeyError(
        f"unknown key {name!r}. Known: {', '.join(sorted(KEYS))}, "
        "or any raw KEYCODE_* name."
    )
