"""The things you actually want to do to a device."""

from __future__ import annotations

import re
import time
from urllib.parse import quote

from . import adb, apps, keys

_SHELL_SAFE = re.compile(r"^[A-Za-z0-9 ._:/@%&?=+,#~\-]*$")


def _quote(value: str) -> str:
    """Single-quote a value for the device's shell."""
    return "'" + value.replace("'", "'\\''") + "'"


def press(key: str, serial: str | None = None, repeat: int = 1) -> str:
    """Send a key event, by friendly name or raw ``KEYCODE_*``."""
    code = keys.resolve(key)
    for index in range(max(1, repeat)):
        if index:
            time.sleep(0.12)
        adb.shell(f"input keyevent {code}", serial=serial)
    return code


def type_text(text: str, serial: str | None = None) -> None:
    """Type text into the focused field.

    ``input text`` has no escaping of its own, so we quote the whole argument
    and translate the characters it refuses to carry.
    """
    payload = text.replace("%", "%%").replace(" ", "%s")
    adb.shell(f"input text {_quote(payload)}", serial=serial)


def open_app(name: str, serial: str | None = None) -> str:
    """Launch an app by alias, package name, or fragment. Returns the package."""
    package = apps.resolve(name, serial=serial)
    adb.shell(
        f"monkey -p {package} -c android.intent.category.LAUNCHER 1",
        serial=serial,
        timeout=45.0,
    )
    return package


def close_app(name: str, serial: str | None = None) -> str:
    package = apps.resolve(name, serial=serial)
    adb.shell(f"am force-stop {package}", serial=serial)
    return package


def open_url(url: str, serial: str | None = None, package: str | None = None) -> None:
    """Open a URL or deep link, optionally in a specific app."""
    cmd = f"am start -a android.intent.action.VIEW -d {_quote(url)}"
    if package:
        cmd += f" {package}"
    adb.shell(cmd, serial=serial, timeout=45.0)


def search_youtube(query: str, serial: str | None = None) -> None:
    """Search YouTube without fighting the on-screen keyboard."""
    url = "https://www.youtube.com/results?search_query=" + quote(query)
    package = None
    try:
        package = apps.resolve("youtube", serial=serial)
    except LookupError:
        pass
    open_url(url, serial=serial, package=package)


def current_app(serial: str | None = None) -> str | None:
    """The package/activity in the foreground, or ``None`` during a transition.

    The filtering happens here rather than with ``grep`` on the device, so it
    works on stripped-down systems whose grep is missing or broken.
    """
    out = adb.shell("dumpsys window", serial=serial, timeout=45.0)
    for line in out.splitlines():
        if "mCurrentFocus" not in line:
            continue
        value = line.split("mCurrentFocus=", 1)[1].strip()
        # Either "null" or "Window{<hash> <user> <package>/<activity>}".
        if "{" in value:
            inner = value[value.index("{") + 1:].rstrip("}").split()
            value = inner[-1] if inner else ""
        value = value.rstrip("}")
        return None if value in ("", "null") else value
    return None


_PLAYBACK_STATES = {
    0: "none", 1: "stopped", 2: "paused", 3: "playing", 4: "fast-forwarding",
    5: "rewinding", 6: "buffering", 7: "error", 8: "connecting",
}


def playback(serial: str | None = None) -> dict[str, object]:
    """What the active media session is doing, if there is one."""
    out = adb.shell("dumpsys media_session", serial=serial, timeout=45.0)
    match = re.search(r"state=PlaybackState\s*\{[^}]*?state=(\d+)", out)
    if not match:
        return {"state": None, "label": "no media session"}
    code = int(match.group(1))
    return {"state": code, "label": _PLAYBACK_STATES.get(code, "unknown")}


def state(serial: str | None = None) -> dict[str, object]:
    """One call that answers "what is this thing doing right now?"."""
    screen = adb.shell("dumpsys power", serial=serial, timeout=45.0)
    wakefulness = "unknown"
    match = re.search(r"mWakefulness=(\w+)", screen)
    if match:
        wakefulness = match.group(1)
    return {
        "foreground": current_app(serial),
        "screen": wakefulness,
        "playback": playback(serial),
    }


def volume(action: str, serial: str | None = None, level: int | None = None,
           steps: int = 1) -> str:
    """``up``/``down``/``mute`` press keys; ``set`` uses the media stream."""
    action = action.lower()
    if action == "set":
        if level is None:
            raise ValueError("volume set needs a level")
        adb.shell(f"cmd media_session volume --stream 3 --set {int(level)}",
                  serial=serial)
        return f"media volume set to {int(level)}"
    if action in {"up", "down"}:
        press("volup" if action == "up" else "voldown", serial=serial, repeat=steps)
        return f"volume {action} x{steps}"
    if action == "mute":
        press("mute", serial=serial)
        return "mute toggled"
    raise ValueError("volume takes up, down, mute or set")


def sleep_device(serial: str | None = None) -> None:
    """Put the screen to sleep (the safe equivalent of the power button)."""
    press("sleep", serial=serial)


def wake_device(serial: str | None = None) -> None:
    press("wake", serial=serial)
