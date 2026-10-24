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


def press(key: str, serial: str | None = None, repeat: int = 1,
          pace_ms: int = 0) -> str:
    """Send a key event, by friendly name or raw ``KEYCODE_*``."""
    press_sequence([key], serial=serial, repeat=repeat, pace_ms=pace_ms)
    return keys.resolve(key)


def press_sequence(names: list[str], serial: str | None = None, repeat: int = 1,
                   pace_ms: int = 0) -> list[str]:
    """Press several keys in order, in a single adb call where we can.

    ``input keyevent`` takes as many keycodes as you give it, so "down down ok"
    is one roundtrip rather than three - which is the difference between a
    remote that feels instant and one that does not, over wifi.

    Some menus drop keys that arrive back to back. ``pace_ms`` goes back to one
    call per key with a pause between them, for those.
    """
    codes = [keys.resolve(name) for name in names]
    sent = [code for code in codes for _ in range(max(1, repeat))]
    if pace_ms > 0:
        for index, code in enumerate(sent):
            if index:
                time.sleep(pace_ms / 1000)
            adb.shell(f"input keyevent {code}", serial=serial)
    else:
        adb.shell("input keyevent " + " ".join(sent), serial=serial)
    return codes


def type_text(text: str, serial: str | None = None) -> None:
    """Type text into the focused field.

    ``input text`` has no escaping of its own, so we quote the whole argument
    and translate the characters it refuses to carry.
    """
    payload = text.replace("%", "%%").replace(" ", "%s")
    adb.shell(f"input text {_quote(payload)}", serial=serial)


# A screen does not change size unless someone rotates the device, and a
# scroll asks for it on every call.
SIZE_TTL = 10.0
_size_cache: dict[str | None, tuple[float, tuple[int, int]]] = {}


def forget_sizes() -> None:
    """Drop cached screen sizes - after a rotation, for instance."""
    _size_cache.clear()


def screen_size(serial: str | None = None, *, fresh: bool = False) -> tuple[int, int]:
    """The display size in pixels, as (width, height), cached for ``SIZE_TTL``."""
    now = time.monotonic()
    cached = _size_cache.get(serial)
    if not fresh and cached is not None and now - cached[0] < SIZE_TTL:
        return cached[1]

    out = adb.shell("wm size", serial=serial)
    for line in out.splitlines():
        if "size:" in line:  # "Physical size: 720x1640" or an override line
            value = line.split(":", 1)[1].strip()
            if "x" in value:
                width, height = value.split("x", 1)
                size = (int(width), int(height))
                _size_cache[serial] = (now, size)
                return size
    raise adb.AdbError(f"could not read the screen size: {out.strip() or 'no output'}")


def tap(x: int, y: int, serial: str | None = None) -> str:
    """Tap a point. Phones are driven by touch; TVs by the d-pad."""
    adb.shell(f"input tap {int(x)} {int(y)}", serial=serial)
    return f"tapped {int(x)},{int(y)}"


def swipe(x1: int, y1: int, x2: int, y2: int, serial: str | None = None,
          duration_ms: int = 300) -> str:
    """Swipe between two points. Also a long press, when the points match."""
    adb.shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}",
              serial=serial)
    return f"swiped {int(x1)},{int(y1)} -> {int(x2)},{int(y2)} in {int(duration_ms)}ms"


def scroll(direction: str, serial: str | None = None, amount: float = 0.6) -> str:
    """Scroll the screen by a fraction of its height or width."""
    width, height = screen_size(serial)
    cx, cy = width // 2, height // 2
    span = int(min(width, height) * max(0.1, min(amount, 0.9)) / 2)
    moves = {
        "up": (cx, cy - span, cx, cy + span),
        "down": (cx, cy + span, cx, cy - span),
        "left": (cx - span, cy, cx + span, cy),
        "right": (cx + span, cy, cx - span, cy),
    }
    if direction.lower() not in moves:
        raise ValueError("scroll takes up, down, left or right")
    return swipe(*moves[direction.lower()], serial=serial, duration_ms=250)


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


def _parse_focus(out: str) -> str | None:
    """Pull the focused package/activity out of a dump, or one line of one."""
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


def current_app(serial: str | None = None) -> str | None:
    """The package/activity in the foreground, or ``None`` during a transition.

    The filtering happens here rather than with ``grep`` on the device, so it
    works on stripped-down systems whose grep is missing or broken.
    """
    return _parse_focus(adb.shell("dumpsys window", serial=serial, timeout=45.0))


_PLAYBACK_STATES = {
    0: "none", 1: "stopped", 2: "paused", 3: "playing", 4: "fast-forwarding",
    5: "rewinding", 6: "buffering", 7: "error", 8: "connecting",
}


def _parse_playback(out: str) -> dict[str, object]:
    match = re.search(r"state=PlaybackState\s*\{[^}]*?state=(\d+)", out)
    if not match:
        return {"state": None, "label": "no media session"}
    code = int(match.group(1))
    return {"state": code, "label": _PLAYBACK_STATES.get(code, "unknown")}


def playback(serial: str | None = None) -> dict[str, object]:
    """What the active media session is doing, if there is one."""
    return _parse_playback(adb.shell("dumpsys media_session", serial=serial,
                                     timeout=45.0))


def _parse_wakefulness(out: str) -> str:
    match = re.search(r"mWakefulness=(\w+)", out)
    return match.group(1) if match else "unknown"


# `state` used to ask three questions in three adb calls, and the answer to
# each was one line buried in a dump that can run to hundreds of kilobytes -
# all of it crossing the wifi. This asks once, and lets the device throw the
# rest away, when it has a grep that works. Devices without one fall back to
# the three full dumps, filtered here, and are remembered so they only pay for
# the attempt once.
_MARK = "@@ADBAI"
_STATE_PROBE = (
    f"echo {_MARK}P; dumpsys power | grep -m1 mWakefulness; "
    f"echo {_MARK}W; dumpsys window | grep -m1 mCurrentFocus; "
    f"echo {_MARK}M; dumpsys media_session | grep -m1 state=PlaybackState; "
    f"echo {_MARK}END"
)
_probe_works: dict[str | None, bool] = {}


def _split_probe(out: str) -> dict[str, str] | None:
    """Cut the probe's output into its three sections, or ``None`` if it failed.

    The power section is the proof: ``mWakefulness`` is always there on a real
    device, so an empty one means the pipeline never ran (no grep, usually).
    """
    if f"{_MARK}END" not in out:
        return None
    sections = {}
    for key, marker in (("power", "P"), ("window", "W"), ("media", "M")):
        start = out.find(f"{_MARK}{marker}\n")
        if start < 0:
            return None
        start += len(f"{_MARK}{marker}\n")
        end = out.find(_MARK, start)
        sections[key] = out[start:end if end > 0 else None].strip()
    return sections if sections["power"] else None


def state(serial: str | None = None) -> dict[str, object]:
    """One call that answers "what is this thing doing right now?"."""
    if _probe_works.get(serial, True):
        out = adb.shell(_STATE_PROBE, serial=serial, timeout=45.0)
        sections = _split_probe(out)
        if sections is not None:
            _probe_works[serial] = True
            return {
                "foreground": _parse_focus(sections["window"]),
                "screen": _parse_wakefulness(sections["power"]),
                "playback": _parse_playback(sections["media"]),
            }
        _probe_works[serial] = False

    return {
        "foreground": current_app(serial),
        "screen": _parse_wakefulness(
            adb.shell("dumpsys power", serial=serial, timeout=45.0)),
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


def _am_start(cmd: str, serial: str | None = None) -> str:
    """Fire an intent and turn Android's polite failures into real errors.

    ``am start`` exits 0 even when nothing handled the intent, so the only
    honest signal is in the text it prints.
    """
    out = adb.shell(cmd, serial=serial, timeout=45.0)
    lowered = out.lower()
    if "error:" in lowered or "no activity found" in lowered or "exception" in lowered:
        raise adb.AdbError(out.strip().splitlines()[-1] if out.strip() else "intent refused")
    return out


_WEEKDAYS = {  # java.util.Calendar numbering, which the alarm intent expects
    "sun": 1, "mon": 2, "tue": 3, "wed": 4, "thu": 5, "fri": 6, "sat": 7,
    "dom": 1, "seg": 2, "ter": 3, "qua": 4, "qui": 5, "sex": 6, "sab": 7,
}


def parse_clock(value: str) -> tuple[int, int]:
    """``"7"``, ``"7:05"``, ``"07h05"``, ``"19:30"`` -> (hour, minute)."""
    cleaned = value.strip().lower().replace("h", ":").rstrip(":")
    parts = cleaned.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    except ValueError:
        raise ValueError(f"not a time: {value!r} (try 7:30 or 19:00)") from None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"not a valid time: {value!r}")
    return hour, minute


def parse_duration(value: str) -> int:
    """``"90"``, ``"10m"``, ``"1h30m"``, ``"45s"`` -> seconds."""
    text = value.strip().lower().replace(" ", "")
    if text.isdigit():
        return int(text)
    total = 0
    number = ""
    units = {"h": 3600, "m": 60, "s": 1}
    for char in text:
        if char.isdigit():
            number += char
        elif char in units and number:
            total += int(number) * units[char]
            number = ""
        else:
            raise ValueError(f"not a duration: {value!r} (try 10m, 1h30m, 90s)")
    if number:  # trailing bare number counts as seconds
        total += int(number)
    if total <= 0:
        raise ValueError(f"not a duration: {value!r}")
    return total


def alarm_handler(serial: str | None = None) -> str | None:
    """Which app would handle an alarm here, or ``None`` if nothing really will.

    Android TV ships a stub that accepts the intent and silently drops it, so
    "an activity was found" is not proof that an alarm can be created.
    """
    out = adb.shell(
        "cmd package query-activities -a android.intent.action.SET_ALARM",
        serial=serial, timeout=45.0,
    )
    packages = [
        line.split("=", 1)[1].strip()
        for line in out.splitlines()
        if line.strip().startswith("packageName=")
    ]
    real = [pkg for pkg in packages if "frameworkpackagestubs" not in pkg]
    return real[0] if real else None


def set_alarm(when: str, serial: str | None = None, label: str | None = None,
              days: str | None = None, vibrate: bool = True,
              confirm_on_device: bool = False) -> str:
    """Create an alarm in the device's clock app.

    Phones and tablets handle this; most TVs have no clock app and will say so.
    """
    hour, minute = parse_clock(when)
    if alarm_handler(serial) is None:
        raise adb.AdbError(
            "this device has no clock app that can hold an alarm - Android TV "
            "accepts the request and silently drops it. Alarms and timers work "
            "on phones and tablets."
        )
    cmd = (
        "am start -a android.intent.action.SET_ALARM "
        f"--ei android.intent.extra.alarm.HOUR {hour} "
        f"--ei android.intent.extra.alarm.MINUTES {minute} "
        f"--ez android.intent.extra.alarm.VIBRATE {str(bool(vibrate)).lower()} "
        f"--ez android.intent.extra.alarm.SKIP_UI {str(not confirm_on_device).lower()}"
    )
    if label:
        cmd += f" --es android.intent.extra.alarm.MESSAGE {_quote(label)}"
    if days:
        numbers = []
        for part in days.replace(";", ",").split(","):
            key = part.strip().lower()[:3]
            if key not in _WEEKDAYS:
                raise ValueError(f"unknown day {part!r} (use mon,tue,wed,thu,fri,sat,sun)")
            numbers.append(str(_WEEKDAYS[key]))
        cmd += " --eial android.intent.extra.alarm.DAYS " + ",".join(numbers)

    _am_start(cmd, serial=serial)
    repeat = f", repeating on {days}" if days else ""
    return f"alarm set for {hour:02d}:{minute:02d}{repeat}"


def set_timer(duration: str, serial: str | None = None, label: str | None = None,
              confirm_on_device: bool = False) -> str:
    """Start a countdown timer in the device's clock app."""
    seconds = parse_duration(duration)
    if alarm_handler(serial) is None:
        raise adb.AdbError(
            "this device has no clock app that can hold a timer - try a phone "
            "or a tablet."
        )
    cmd = (
        "am start -a android.intent.action.SET_TIMER "
        f"--ei android.intent.extra.alarm.LENGTH {seconds} "
        f"--ez android.intent.extra.alarm.SKIP_UI {str(not confirm_on_device).lower()}"
    )
    if label:
        cmd += f" --es android.intent.extra.alarm.MESSAGE {_quote(label)}"
    _am_start(cmd, serial=serial)
    minutes, rest = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    pretty = ":".join(f"{part:02d}" for part in (hours, minutes, rest))
    return f"timer started for {pretty}"


def show_alarms(serial: str | None = None) -> str:
    """Open the clock app on its list of alarms."""
    _am_start("am start -a android.intent.action.SHOW_ALARMS", serial=serial)
    return "opened the alarm list"


def sleep_device(serial: str | None = None) -> None:
    """Put the screen to sleep (the safe equivalent of the power button)."""
    press("sleep", serial=serial)


def wake_device(serial: str | None = None) -> None:
    press("wake", serial=serial)
