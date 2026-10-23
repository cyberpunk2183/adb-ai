"""An MCP server over stdio, implemented with nothing but the standard library.

Hand-rolling the protocol keeps ``pip install adbctl`` dependency-free, which
matters because this often runs on a phone, a Raspberry Pi or a Termux shell.

Wire up in Claude Code / Claude Desktop / Cursor with:

    {"mcpServers": {"adbctl": {"command": "adbctl", "args": ["mcp"]}}}
"""

from __future__ import annotations

import base64
import json
import os
import sys
import traceback
from typing import Any, Callable

from . import __version__, actions, adb, apps, keys, target

PROTOCOL_VERSION = "2024-11-05"

# Raw shell access is off unless the operator opts in: an agent that can run
# any command on a device in your home is a different trust level from one
# that can press Play.
ALLOW_SHELL = os.environ.get("ADBCTL_ALLOW_SHELL", "").lower() in {"1", "true", "yes"}


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


def tool_key(args: dict[str, Any]) -> dict[str, Any]:
    serial = _device(args)
    pressed = [actions.press(name, serial=serial, repeat=int(args.get("repeat", 1)))
               for name in args["keys"]]
    return _text("pressed " + ", ".join(pressed))


def tool_text(args: dict[str, Any]) -> dict[str, Any]:
    actions.type_text(args["text"], serial=_device(args))
    return _text("typed")


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


def tool_screenshot(args: dict[str, Any]) -> dict[str, Any]:
    data = adb.screencap(_device(args))
    return {
        "content": [{
            "type": "image",
            "data": base64.b64encode(data).decode("ascii"),
            "mimeType": "image/png",
        }]
    }


def tool_shell(args: dict[str, Any]) -> dict[str, Any]:
    if not ALLOW_SHELL:
        return _text(
            "raw shell is disabled. The operator can enable it by setting "
            "ADBCTL_ALLOW_SHELL=1 in this server's environment."
        )
    return _text(adb.shell(args["command"], serial=_device(args), timeout=60.0))


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
        "name": "adb_key",
        "description": "Press remote-control keys, in order. Names: "
                       + ", ".join(sorted(keys.KEYS)),
        "inputSchema": _schema({
            "keys": {"type": "array", "items": {"type": "string"},
                     "description": 'e.g. ["home"], ["down","down","ok"]'},
            "repeat": {"type": "integer", "description": "press each key N times"},
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
        "name": "adb_state",
        "description": "What is in the foreground, whether the screen is on, and whether "
                       "media is playing. Call this to check an action worked.",
        "inputSchema": _schema({}),
        "handler": tool_state,
    },
    {
        "name": "adb_screenshot",
        "description": "Capture the screen as a PNG image.",
        "inputSchema": _schema({}),
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
        "name": "adb_shell",
        "description": "Run a raw adb shell command. Disabled unless the operator sets "
                       "ADBCTL_ALLOW_SHELL=1.",
        "inputSchema": _schema({"command": {"type": "string"}}, ["command"]),
        "handler": tool_shell,
    },
]

HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    tool["name"]: tool.pop("handler") for tool in TOOLS
}


# --- JSON-RPC plumbing ------------------------------------------------------

def _handle(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "adbctl", "version": __version__},
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
            if os.environ.get("ADBCTL_DEBUG"):
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
