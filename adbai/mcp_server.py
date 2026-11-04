"""An MCP server over stdio, implemented with nothing but the standard library.

Hand-rolling the protocol keeps ``pip install adb-ai`` dependency-free, which
matters because this often runs on a phone, a Raspberry Pi or a Termux shell.

Wire up in Claude Code / Claude Desktop / Cursor with:

    {"mcpServers": {"adb-ai": {"command": "adb-ai", "args": ["mcp"]}}}
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
import traceback
from typing import Any, Callable

from . import __version__, actions, adb, apps, images, keys, live, mirror, pairing, qr, target, ui

PROTOCOL_VERSION = "2024-11-05"

# Raw shell access is on: the whole point of ADB-AI is handing an agent the
# same reach you have over your own devices, and plenty of useful things
# (dumpsys, pm, settings, am) live only behind the shell. It can be turned off
# for a setup where that is too much - see _shell_enabled().
_SHELL_OFF = {"0", "false", "no", "off"}


def _shell_enabled() -> bool:
    """Whether adb_shell will run. On unless the operator says otherwise.

    Set ``ADBAI_ALLOW_SHELL=0`` (or ``ADBAI_NO_SHELL=1``) to disable it, for a
    shared machine or a device you would rather an agent could not reprogram.
    Read at call time, so a client can change it without a reinstall.
    """
    if os.environ.get("ADBAI_NO_SHELL", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    allow = os.environ.get("ADBAI_ALLOW_SHELL")
    if allow is None:
        return True
    return allow.strip().lower() not in _SHELL_OFF


def _text(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}]}


def _data(payload: object) -> dict[str, Any]:
    return _text(json.dumps(payload, indent=2, ensure_ascii=False))


# --- tool implementations ---------------------------------------------------

def _device(args: dict[str, Any]) -> str:
    return target.resolve(args.get("device"))


def tool_list_devices(args: dict[str, Any]) -> dict[str, Any]:
    return _data([{"serial": d.serial, "state": d.state, "model": d.model}
                  for d in adb.devices()])


def tool_scan(args: dict[str, Any]) -> dict[str, Any]:
    found = adb.scan(prefix=args.get("subnet"))
    return _data({"found": found, "hint": "connect with adb_connect"})


def tool_connect(args: dict[str, Any]) -> dict[str, Any]:
    return _text(adb.connect(args["target"]))


# A QR pairing is two calls: one to put the code on the screen the human is
# looking at, one to wait for the camera. Holding the credentials between them
# is what lets the agent show the code and then block on the scan without a
# single call sitting there for a minute.
_PENDING: dict[str, pairing.Credentials] = {}


def tool_pair_qr_start(args: dict[str, Any]) -> dict[str, Any]:
    credentials = pairing.new_credentials()
    _PENDING["current"] = credentials
    matrix = qr.encode(credentials.payload, ecl="M")
    return {
        "content": [
            {
                "type": "image",
                "data": base64.b64encode(qr.to_png_bytes(matrix, scale=8)).decode("ascii"),
                "mimeType": "image/png",
            },
            {
                "type": "text",
                "text": "Show this code to the person and tell them: on the device, "
                        "Settings > Developer options > Wireless debugging > 'Pair "
                        "device with QR code', then point the camera at it. Call "
                        "adb_pair_qr_finish once they are pointing at it - it waits "
                        "for the scan. Pairing is for Android 11+; a TV has no such "
                        "screen and pairs with adb_connect instead.",
            },
        ]
    }


def tool_pair_qr_finish(args: dict[str, Any]) -> dict[str, Any]:
    credentials = _PENDING.get("current")
    if credentials is None:
        raise ValueError("no pairing in progress - call adb_pair_qr_start first")
    timeout = float(args.get("timeout_seconds") or 60)
    try:
        result = pairing.pair_with_qr(credentials, timeout=timeout)
    finally:
        _PENDING.pop("current", None)
    return _data(result)


# Without live view there is no stream to watch settle, so "look" waits this
# long and takes a screenshot instead.
LOOK_DELAY = 0.6


def _image(data: bytes, mime: str) -> dict[str, Any]:
    return {"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": mime}


def _frame_content(view: live.LiveView, frame: live.Frame, note: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": f"{note}\n{view.describe(frame)}"},
            _image(frame.data, "image/jpeg")]


def _screenshot_content(serial: str, args: dict[str, Any], note: str) -> list[dict[str, Any]]:
    data, mime = images.shrink(adb.screencap(serial), max_size=_shot_max_size(args))
    return [{"type": "text", "text": note}, _image(data, mime)]


def _acting(args: dict[str, Any], act: Callable[[str], str]) -> dict[str, Any]:
    """Do something to the device, and with ``look`` show what it did.

    With live view running, "what it did" is the first frame after the screen
    stops moving - no fixed sleep, no second call. Without it, a screenshot a
    moment later.
    """
    serial = _device(args)
    if not args.get("look"):
        return _text(act(serial))
    view = live.get(serial)
    before = view.seq() if view else 0
    message = act(serial)
    if view is not None:
        frame, how = view.wait_settled(before)
        return {"content": _frame_content(view, frame, f"{message} - screen {how}")}
    time.sleep(LOOK_DELAY)
    return {"content": _screenshot_content(
        serial, args, f"{message} - screenshot {LOOK_DELAY:g}s later "
                      "(adb_live would show it the moment it settles)")}


def tool_key(args: dict[str, Any]) -> dict[str, Any]:
    return _acting(args, lambda serial: "pressed " + ", ".join(actions.press_sequence(
        args["keys"], serial=serial, repeat=int(args.get("repeat", 1)),
        pace_ms=int(args.get("pace_ms", 0)),
    )))


def tool_text(args: dict[str, Any]) -> dict[str, Any]:
    def act(serial: str) -> str:
        actions.type_text(args["text"], serial=serial)
        return "typed"
    return _acting(args, act)


def tool_tap(args: dict[str, Any]) -> dict[str, Any]:
    return _acting(args, lambda serial: actions.tap(args["x"], args["y"], serial=serial))


def tool_tap_text(args: dict[str, Any]) -> dict[str, Any]:
    return _acting(args, lambda serial: ui.tap_text(
        args["text"], serial=serial, index=int(args.get("index", 0))))


def tool_swipe(args: dict[str, Any]) -> dict[str, Any]:
    return _acting(args, lambda serial: actions.swipe(
        args["x1"], args["y1"], args["x2"], args["y2"],
        serial=serial, duration_ms=int(args.get("duration_ms", 300)),
    ))


def tool_scroll(args: dict[str, Any]) -> dict[str, Any]:
    return _acting(args, lambda serial: actions.scroll(
        args["direction"], serial=serial, amount=float(args.get("amount", 0.6))))


def tool_ui(args: dict[str, Any]) -> dict[str, Any]:
    items = ui.elements(_device(args))
    if args.get("clickable_only"):
        items = [item for item in items if item.clickable]
    return _data([item.as_dict() for item in items])


def tool_screen_size(args: dict[str, Any]) -> dict[str, Any]:
    width, height = actions.screen_size(_device(args))
    return _data({"width": width, "height": height})


def tool_apps(args: dict[str, Any]) -> dict[str, Any]:
    return _data(apps.installed(_device(args), third_party_only=not args.get("all")))


def tool_open_app(args: dict[str, Any]) -> dict[str, Any]:
    return _acting(args, lambda serial: "launched " + actions.open_app(args["app"], serial=serial))


def tool_close_app(args: dict[str, Any]) -> dict[str, Any]:
    return _text("stopped " + actions.close_app(args["app"], serial=_device(args)))


def tool_open_url(args: dict[str, Any]) -> dict[str, Any]:
    actions.open_url(args["url"], serial=_device(args), package=args.get("app"))
    return _text("opened " + args["url"])


def tool_youtube(args: dict[str, Any]) -> dict[str, Any]:
    actions.search_youtube(args["query"], serial=_device(args))
    return _text(f"searching YouTube for {args['query']!r}")


def tool_set_alarm(args: dict[str, Any]) -> dict[str, Any]:
    return _text(actions.set_alarm(
        args["time"], serial=_device(args), label=args.get("label"),
        days=args.get("days"),
    ))


def tool_set_timer(args: dict[str, Any]) -> dict[str, Any]:
    return _text(actions.set_timer(
        args["duration"], serial=_device(args), label=args.get("label"),
    ))


def tool_state(args: dict[str, Any]) -> dict[str, Any]:
    return _data(actions.state(_device(args)))


def tool_volume(args: dict[str, Any]) -> dict[str, Any]:
    return _text(actions.volume(
        args["action"], serial=_device(args),
        level=args.get("level"), steps=int(args.get("steps", 1)),
    ))


def tool_power(args: dict[str, Any]) -> dict[str, Any]:
    serial = _device(args)
    if args["action"] == "sleep":
        actions.sleep_device(serial)
        return _text("screen asleep")
    actions.wake_device(serial)
    return _text("device awake")


def _shot_max_size(args: dict[str, Any]) -> int:
    """How large a screenshot may be before it is scaled down for the model."""
    if args.get("max_size") is not None:
        return int(args["max_size"])
    override = os.environ.get("ADBAI_SHOT_MAX", "").strip()
    if override.isdigit():
        return int(override)
    return images.DEFAULT_MAX_SIZE


def tool_screenshot(args: dict[str, Any]) -> dict[str, Any]:
    data = adb.screencap(_device(args))
    # A 4K screen with artwork on it is megabytes of PNG, and every one of them
    # has to reach the model before it can answer. Scaled down it is a tenth of
    # that and says the same thing. Small screens are left alone; see images.py.
    data, mime = images.shrink(data, max_size=_shot_max_size(args))
    return {
        "content": [{
            "type": "image",
            "data": base64.b64encode(data).decode("ascii"),
            "mimeType": mime,
        }]
    }


def tool_mirror(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "start").lower()

    if action == "status":
        live = mirror.running()
        if not live:
            return _text("no mirror running")
        return _data([{"device": serial or "default device", "pid": pid}
                      for serial, pid in live.items()])

    if action != "stop":
        # Say "scrcpy will not run here" before "no device": the first is the
        # real problem, and it does not depend on a device being connected.
        mirror.preflight()
    serial = _device(args)
    if action == "stop":
        return _text(f"closed the mirror of {serial}" if mirror.stop(serial)
                     else f"no mirror of {serial} was running")

    proc = mirror.start(
        serial,
        view_only=bool(args.get("view_only")),
        record=args.get("record"),
        max_size=int(args["max_size"]) if args.get("max_size") else None,
        title=f"adb-ai {serial}",
    )
    return _text(
        f"a window showing {serial} is now open on the operator's computer "
        f"(pid {proc.pid}). You cannot see it - use adb_screenshot for that. "
        f"scrcpy's own messages go to {mirror.log_path()}. "
        "Close it with action='stop'."
    )


def tool_live(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "start").lower()
    if action == "status":
        views = list(live.running())
        if not views:
            return _text("live view is off. action='start' turns it on.")
        return _data([view.status() for view in views])

    serial = _device(args)
    if action == "stop":
        return _text("live view stopped" if live.stop(serial) else "live view was not running")
    if action != "start":
        raise ValueError(f"unknown action {action!r}: use start, stop or status")

    options: dict[str, Any] = {"source": args.get("source") or "auto",
                               "window": args.get("window", True)}
    if args.get("max_size") is not None:
        options["max_size"] = int(args["max_size"])
    if args.get("animations") is True:
        options["animations"] = True
    view = live.start(serial, **options)
    frame = view.current(timeout=10.0)
    status = view.status()
    if view.source in ("v4l2", "scrcpy") and status["window"] and view.window:
        who = "the person's scrcpy window and you are looking at the same capture"
    elif view.source == "scrcpy":
        who = "frames come from scrcpy, with no window"
    else:
        who = ("frames come from the device's screenrecord; once the screen is "
               "still, a screencap stands in for the last frame, so answers after "
               "an action take a second or two longer"
               + ("; the person has a scrcpy window of their own" if status["window"] else ""))
    return {"content": _frame_content(view, frame, (
        f"live view on via {view.source} - {who}. adb_look shows the newest frame "
        "at once; look=true on an action shows the screen once it settles; "
        "adb_wait_change waits for the screen to change by itself."))}


def tool_look(args: dict[str, Any]) -> dict[str, Any]:
    serial = _device(args)
    view = live.get(serial)
    if view is None:
        return {"content": _screenshot_content(
            serial, args, "live view is off, so this is a fresh screenshot - "
                          "adb_live makes looking instant")}
    frame = view.current()
    return {"content": _frame_content(view, frame, "live")}


def tool_wait_change(args: dict[str, Any]) -> dict[str, Any]:
    serial = _device(args)
    view = live.get(serial)
    if view is None:
        raise adb.AdbError("adb_wait_change needs live view - start it with adb_live")
    timeout = float(args.get("timeout_seconds") or 10)
    before = view.seq()
    if view.wait_change(before, timeout) is None:
        frame = view.current()
        return {"content": _frame_content(view, frame, f"no change in {timeout:g}s")}
    frame, how = view.wait_settled(before, change=0)
    return {"content": _frame_content(view, frame, f"the screen changed - {how}")}


def tool_shell(args: dict[str, Any]) -> dict[str, Any]:
    if not _shell_enabled():
        return _text(
            "raw shell is switched off on this server (ADBAI_NO_SHELL / "
            "ADBAI_ALLOW_SHELL=0). Ask the person who set it up, or use the "
            "ordinary tools - keys, apps, state and the rest cover most things."
        )
    output = adb.shell(args["command"], serial=_device(args), timeout=90.0)
    return _text(output if output.strip() else "(no output)")


_DEVICE_PROP = {
    "device": {
        "type": "string",
        "description": "serial, ip[:port] or saved alias; omit to use the default device",
    }
}


_LOOK_PROP = {
    "look": {
        "type": "boolean",
        "description": "also return the screen after the action - with adb_live on, "
                       "the moment it stops changing; otherwise a screenshot",
    }
}


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {**_DEVICE_PROP, **properties},
        "required": required or [],
    }


TOOLS: list[dict[str, Any]] = [
    {
        "name": "adb_list_devices",
        "description": "List the Android devices adb currently knows about.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_list_devices,
    },
    {
        "name": "adb_scan",
        "description": "Scan the local network for devices with the adb port open. "
                       "Use when a device's IP changed (DHCP) or nothing is connected.",
        "inputSchema": {"type": "object", "properties": {
            "subnet": {"type": "string", "description": "prefix such as 192.168.0."}}},
        "handler": tool_scan,
    },
    {
        "name": "adb_connect",
        "description": "Connect to a device over the network by ip[:port] or alias.",
        "inputSchema": {"type": "object", "properties": {
            "target": {"type": "string"}}, "required": ["target"]},
        "handler": tool_connect,
    },
    {
        "name": "adb_pair_qr_start",
        "description": "Begin pairing an Android 11+ phone or tablet by QR code. "
                       "Returns a QR image to show the person; they point the "
                       "device's camera at it from Wireless debugging > 'Pair device "
                       "with QR code'. Then call adb_pair_qr_finish. Use this when a "
                       "device has never been paired with this machine; an "
                       "already-paired device just needs adb_connect.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_pair_qr_start,
    },
    {
        "name": "adb_pair_qr_finish",
        "description": "Wait for the device to scan the code from adb_pair_qr_start, "
                       "pair with it, and connect. Blocks until it happens or the "
                       "timeout runs out.",
        "inputSchema": {"type": "object", "properties": {
            "timeout_seconds": {"type": "integer",
                                "description": "how long to wait, default 60"}}},
        "handler": tool_pair_qr_finish,
    },
    {
        "name": "adb_key",
        "description": "Press remote-control keys, in order. Names: "
                       + ", ".join(sorted(keys.KEYS)),
        "inputSchema": _schema({
            "keys": {"type": "array", "items": {"type": "string"},
                     "description": 'e.g. ["home"], ["down","down","ok"]'},
            "repeat": {"type": "integer", "description": "press each key N times"},
            "pace_ms": {"type": "integer",
                        "description": "all the keys go in one call by default; set "
                                       "this (e.g. 120) if a menu drops keys that "
                                       "arrive back to back"},
            **_LOOK_PROP,
        }, ["keys"]),
        "handler": tool_key,
    },
    {
        "name": "adb_type_text",
        "description": "Type text into the field that currently has focus.",
        "inputSchema": _schema({"text": {"type": "string"}, **_LOOK_PROP}, ["text"]),
        "handler": tool_text,
    },
    {
        "name": "adb_tap",
        "description": "Tap a point on the screen, in screen pixels. For phones and "
                       "tablets - a TV is driven with adb_key instead. When the target "
                       "has text, adb_tap_text is faster and exact; otherwise find the "
                       "point with adb_look or adb_screenshot.",
        "inputSchema": _schema({
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            **_LOOK_PROP,
        }, ["x", "y"]),
        "handler": tool_tap,
    },
    {
        "name": "adb_tap_text",
        "description": "Tap the on-screen element whose text or description matches - "
                       "a button, a menu item, a link - at its real centre, read from "
                       "the layout. No screenshot and no coordinates needed. Exact "
                       "matches win over partial ones; the error lists what is on "
                       "screen when nothing matches.",
        "inputSchema": _schema({
            "text": {"type": "string", "description": "e.g. 'Save', 'Wi-Fi'"},
            "index": {"type": "integer",
                      "description": "which match, when several do; default 0 (best)"},
            **_LOOK_PROP,
        }, ["text"]),
        "handler": tool_tap_text,
    },
    {
        "name": "adb_ui",
        "description": "Read the screen as text: every element with text, a "
                       "description or a click handler, with its centre in screen "
                       "pixels. Faster than a screenshot for finding what to tap, and "
                       "exact. Blind to games, video and maps - use adb_look for those.",
        "inputSchema": _schema({
            "clickable_only": {"type": "boolean"},
        }),
        "handler": tool_ui,
    },
    {
        "name": "adb_swipe",
        "description": "Swipe from one point to another. The same point twice, with a "
                       "longer duration_ms, is a long press.",
        "inputSchema": _schema({
            "x1": {"type": "integer"}, "y1": {"type": "integer"},
            "x2": {"type": "integer"}, "y2": {"type": "integer"},
            "duration_ms": {"type": "integer", "description": "default 300"},
            **_LOOK_PROP,
        }, ["x1", "y1", "x2", "y2"]),
        "handler": tool_swipe,
    },
    {
        "name": "adb_scroll",
        "description": "Scroll the screen up, down, left or right without working out "
                       "coordinates.",
        "inputSchema": _schema({
            "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
            "amount": {"type": "number",
                       "description": "fraction of the screen to travel, 0.1-0.9"},
            **_LOOK_PROP,
        }, ["direction"]),
        "handler": tool_scroll,
    },
    {
        "name": "adb_screen_size",
        "description": "The screen size in pixels, so taps and swipes can be aimed.",
        "inputSchema": _schema({}),
        "handler": tool_screen_size,
    },
    {
        "name": "adb_list_apps",
        "description": "List installed packages (third-party by default).",
        "inputSchema": _schema({"all": {"type": "boolean",
                                        "description": "include system packages"}}),
        "handler": tool_apps,
    },
    {
        "name": "adb_open_app",
        "description": "Launch an app by friendly alias (netflix, youtube, spotify...), "
                       "full package name, or a fragment of one.",
        "inputSchema": _schema({"app": {"type": "string"}, **_LOOK_PROP}, ["app"]),
        "handler": tool_open_app,
    },
    {
        "name": "adb_close_app",
        "description": "Force-stop an app.",
        "inputSchema": _schema({"app": {"type": "string"}}, ["app"]),
        "handler": tool_close_app,
    },
    {
        "name": "adb_open_url",
        "description": "Open a URL or deep link, optionally in a specific app.",
        "inputSchema": _schema({"url": {"type": "string"},
                                "app": {"type": "string"}}, ["url"]),
        "handler": tool_open_url,
    },
    {
        "name": "adb_youtube_search",
        "description": "Search YouTube on the device without using the on-screen keyboard.",
        "inputSchema": _schema({"query": {"type": "string"}}, ["query"]),
        "handler": tool_youtube,
    },
    {
        "name": "adb_set_alarm",
        "description": "Set an alarm in the device's clock app. Phones and tablets only - "
                       "most TVs have no clock app and the call will say so.",
        "inputSchema": _schema({
            "time": {"type": "string", "description": "7:30, 19:00"},
            "label": {"type": "string", "description": "what the alarm is for"},
            "days": {"type": "string", "description": "repeat, e.g. mon,tue,wed,thu,fri"},
        }, ["time"]),
        "handler": tool_set_alarm,
    },
    {
        "name": "adb_set_timer",
        "description": "Start a countdown timer in the device's clock app.",
        "inputSchema": _schema({
            "duration": {"type": "string", "description": "10m, 1h30m, 90s"},
            "label": {"type": "string"},
        }, ["duration"]),
        "handler": tool_set_timer,
    },
    {
        "name": "adb_state",
        "description": "What is in the foreground, whether the screen is on, and whether "
                       "media is playing. Call this to check an action worked.",
        "inputSchema": _schema({}),
        "handler": tool_state,
    },
    {
        "name": "adb_screenshot",
        "description": "Capture the screen and return it as an image you can look at. "
                       "Large screens are scaled down on the way (ffmpeg, when it is "
                       "installed) so you get the picture sooner; pass max_size to "
                       "change that, or 0 for the untouched original.",
        "inputSchema": _schema({
            "max_size": {"type": "integer",
                         "description": "longest side in pixels, default 1280; "
                                        "0 sends the full-size PNG"},
        }),
        "handler": tool_screenshot,
    },
    {
        "name": "adb_volume",
        "description": "Change the volume: up, down, mute, or set an exact level.",
        "inputSchema": _schema({
            "action": {"type": "string", "enum": ["up", "down", "mute", "set"]},
            "level": {"type": "integer", "description": "for action=set"},
            "steps": {"type": "integer", "description": "how many steps for up/down"},
        }, ["action"]),
        "handler": tool_volume,
    },
    {
        "name": "adb_power",
        "description": "Put the screen to sleep or wake the device.",
        "inputSchema": _schema({"action": {"type": "string",
                                           "enum": ["sleep", "wake"]}}, ["action"]),
        "handler": tool_power,
    },
    {
        "name": "adb_mirror",
        "description": "Open a live window of the device's screen on the operator's "
                       "computer, using scrcpy, so a human can watch what you are "
                       "doing and take over with mouse and keyboard. It is for them, "
                       "not for you: you cannot see the window. To watch along with "
                       "them, use adb_live instead - it opens the same window and "
                       "lets you see it too. Needs scrcpy installed and a desktop "
                       "session; it does not work from Termux.",
        "inputSchema": _schema({
            "action": {"type": "string", "enum": ["start", "stop", "status"],
                       "description": "default start"},
            "view_only": {"type": "boolean",
                          "description": "show the screen without giving mouse and "
                                         "keyboard control"},
            "record": {"type": "string",
                       "description": "also save the session to this .mp4 path - say "
                                      "so before you do it"},
            "max_size": {"type": "integer",
                         "description": "limit the longest side in pixels, e.g. 1024 "
                                        "on a slow network"},
        }),
        "handler": tool_mirror,
    },
    {
        "name": "adb_live",
        "description": "Stream the device's screen to this computer so you can see it "
                       "without waiting for screenshots: adb_look then returns the "
                       "newest frame at once, look=true on an action returns the "
                       "screen the moment it settles, and adb_wait_change waits for "
                       "it to change by itself. With source v4l2 (Linux, "
                       "v4l2loopback) the person's scrcpy window and you share one "
                       "capture; screenrecord works everywhere. Needs ffmpeg. Frames "
                       "are scaled down: the text with each one says how to turn what "
                       "you see into tap coordinates. On a phone this is a continuous "
                       "screenshot of everything that crosses the screen: start it "
                       "only when the person asks or agrees, and stop it when done.",
        "inputSchema": _schema({
            "action": {"type": "string", "enum": ["start", "stop", "status"],
                       "description": "default start"},
            "source": {"type": "string", "enum": ["auto", "v4l2", "scrcpy", "screenrecord"],
                       "description": "where the video comes from; auto picks the best "
                                      "that works here (v4l2, then scrcpy, then "
                                      "screenrecord)"},
            "window": {"type": "boolean",
                       "description": "open a scrcpy window for the person, default true"},
            "max_size": {"type": "integer",
                         "description": "longest side of the frames you get, default 1280"},
            "animations": {"type": "boolean",
                           "description": "default false: the device's animations are "
                                          "off while live view runs, so every action "
                                          "shows at once - over twice as fast. They are "
                                          "put back on stop. true leaves them on, if the "
                                          "user wants the device to look as usual"},
        }),
        "handler": tool_live,
    },
    {
        "name": "adb_look",
        "description": "See the screen now. With adb_live running this is the newest "
                       "frame, instantly; without it, a fresh screenshot.",
        "inputSchema": _schema({}),
        "handler": tool_look,
    },
    {
        "name": "adb_wait_change",
        "description": "Wait until the screen changes on its own - a page loading, a "
                       "video starting, a dialog appearing - then return it once it "
                       "settles. Needs adb_live.",
        "inputSchema": _schema({
            "timeout_seconds": {"type": "number", "description": "default 10"},
        }),
        "handler": tool_wait_change,
    },
    {
        "name": "adb_shell",
        "description": "Run any adb shell command on the device and return its output - "
                       "dumpsys, pm, am, settings, getprop, input, wm, content, and so "
                       "on. Use it for what the other tools do not cover; prefer them "
                       "when they do. Runs as the shell user (no root). Can be switched "
                       "off with ADBAI_NO_SHELL=1.",
        "inputSchema": _schema({"command": {"type": "string"}}, ["command"]),
        "handler": tool_shell,
    },
]

HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    tool["name"]: tool.pop("handler") for tool in TOOLS
}


# --- JSON-RPC plumbing ------------------------------------------------------

def _warm_up() -> None:
    """Start the adb server and connect, before a tool call has to wait for it.

    The first command of a session used to pay for all of it: starting adb's
    own server, then reconnecting a TV whose address came from the config. Both
    happen here instead, while the client is still listing tools.
    """
    try:
        adb.run(["start-server"], timeout=20.0, check=False)
        target.resolve()
    except Exception:  # a warm-up that fails must not break the session
        pass


def _handle(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")

    if method == "initialize":
        threading.Thread(target=_warm_up, daemon=True).start()
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "adb-ai", "version": __version__},
            },
        }

    if method in {"notifications/initialized", "initialized"}:
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        handler = HANDLERS.get(name)
        if handler is None:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32601, "message": f"unknown tool: {name}"}}
        try:
            result = handler(params.get("arguments") or {})
        except Exception as exc:  # tool errors belong in the result, not the envelope
            detail = str(exc) or exc.__class__.__name__
            if os.environ.get("ADBAI_DEBUG"):
                detail += "\n" + traceback.format_exc()
            result = {"content": [{"type": "text", "text": f"error: {detail}"}],
                      "isError": True}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": -32601, "message": f"unknown method: {method}"}}


def serve(stdin=None, stdout=None) -> None:
    """Read line-delimited JSON-RPC from stdin, write replies to stdout."""
    source = stdin or sys.stdin
    sink = stdout or sys.stdout
    try:
        _serve(source, sink)
    finally:
        # The client went away: leave no ffmpeg, screenrecord or window behind.
        live.stop_all()


def _serve(source, sink) -> None:
    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = _handle(request)
        if response is not None:
            sink.write(json.dumps(response) + "\n")
            sink.flush()
