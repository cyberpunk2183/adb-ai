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
import traceback
from typing import Any, Callable

from . import __version__, actions, adb, apps, images, keys, mirror, pairing, qr, target

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


def tool_key(args: dict[str, Any]) -> dict[str, Any]:
    pressed = actions.press_sequence(
        args["keys"], serial=_device(args), repeat=int(args.get("repeat", 1)),
        pace_ms=int(args.get("pace_ms", 0)),
    )
    return _text("pressed " + ", ".join(pressed))


def tool_text(args: dict[str, Any]) -> dict[str, Any]:
    actions.type_text(args["text"], serial=_device(args))
    return _text("typed")


def tool_tap(args: dict[str, Any]) -> dict[str, Any]:
    return _text(actions.tap(args["x"], args["y"], serial=_device(args)))


def tool_swipe(args: dict[str, Any]) -> dict[str, Any]:
    return _text(actions.swipe(
        args["x1"], args["y1"], args["x2"], args["y2"],
        serial=_device(args), duration_ms=int(args.get("duration_ms", 300)),
    ))


def tool_scroll(args: dict[str, Any]) -> dict[str, Any]:
    return _text(actions.scroll(args["direction"], serial=_device(args),
                                amount=float(args.get("amount", 0.6))))


def tool_screen_size(args: dict[str, Any]) -> dict[str, Any]:
    width, height = actions.screen_size(_device(args))
    return _data({"width": width, "height": height})


def tool_apps(args: dict[str, Any]) -> dict[str, Any]:
    return _data(apps.installed(_device(args), third_party_only=not args.get("all")))


def tool_open_app(args: dict[str, Any]) -> dict[str, Any]:
    return _text("launched " + actions.open_app(args["app"], serial=_device(args)))


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
        }, ["keys"]),
        "handler": tool_key,
    },
    {
        "name": "adb_type_text",
        "description": "Type text into the field that currently has focus.",
        "inputSchema": _schema({"text": {"type": "string"}}, ["text"]),
        "handler": tool_text,
    },
    {
        "name": "adb_tap",
        "description": "Tap a point on the screen. For phones and tablets - a TV is "
                       "driven with adb_key instead. Take a screenshot first to find "
                       "the coordinates, and adb_screen_size to know the bounds.",
        "inputSchema": _schema({
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        }, ["x", "y"]),
        "handler": tool_tap,
    },
    {
        "name": "adb_swipe",
        "description": "Swipe from one point to another. The same point twice, with a "
                       "longer duration_ms, is a long press.",
        "inputSchema": _schema({
            "x1": {"type": "integer"}, "y1": {"type": "integer"},
            "x2": {"type": "integer"}, "y2": {"type": "integer"},
            "duration_ms": {"type": "integer", "description": "default 300"},
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
        "inputSchema": _schema({"app": {"type": "string"}}, ["app"]),
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
                       "not for you: you cannot see the window, so keep using "
                       "adb_screenshot to look at the screen. Needs scrcpy installed "
                       "and a desktop session; it does not work from Termux.",
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
