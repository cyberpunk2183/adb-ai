"""Command line interface: ``adb-ai <command> [...]``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, actions, adb, apps, config, keys, target


def _out(message: str) -> None:
    print(message)


def _json(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


# --- commands ---------------------------------------------------------------

def cmd_devices(args: argparse.Namespace) -> int:
    found = adb.devices()
    if args.json:
        _json([{"serial": d.serial, "state": d.state, "model": d.model} for d in found])
        return 0
    if not found:
        _out("no devices. 'adb-ai scan' looks for one on your network.")
        return 0
    stored = config.load()
    for device in found:
        marks = []
        if device.serial == stored["default"]:
            marks.append("default")
        for alias, value in stored["aliases"].items():
            if adb.normalise_target(value) == device.serial:
                marks.append(alias)
        suffix = f"  ({', '.join(marks)})" if marks else ""
        _out(device.describe() + suffix)
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    found = adb.scan(prefix=args.subnet, port=args.port, timeout=args.timeout)
    if args.json:
        _json(found)
        return 0
    if not found:
        _out(
            "nothing listening on the adb port.\n"
            "On the device: Settings > Developer options > enable 'Network debugging' "
            "(Android TV) or 'Wireless debugging' (phones).\n"
            "A USB-connected device can be switched over with 'adb tcpip 5555'."
        )
        return 1
    for address in found:
        _out(address)
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    message = adb.connect(config.resolve_alias(args.target), port=args.port)
    _out(message)
    serial = adb.normalise_target(config.resolve_alias(args.target), args.port)
    if args.alias:
        config.set_alias(args.alias, serial)
        _out(f"saved alias {args.alias!r} -> {serial}")
    if args.use or args.alias:
        config.set_default(serial)
        _out(f"default device is now {serial}")
    return 0


def cmd_disconnect(args: argparse.Namespace) -> int:
    _out(adb.disconnect(args.target) or "disconnected")
    return 0


def cmd_use(args: argparse.Namespace) -> int:
    if args.target in (None, "-"):
        config.set_default(None)
        _out("default device cleared")
        return 0
    serial = adb.normalise_target(config.resolve_alias(args.target))
    config.set_default(serial)
    _out(f"default device is now {serial}")
    return 0


def cmd_alias(args: argparse.Namespace) -> int:
    if args.remove:
        _out("removed" if config.remove_alias(args.name) else "no such alias")
        return 0
    if args.target is None:
        _json(config.load()["aliases"])
        return 0
    serial = adb.normalise_target(args.target)
    config.set_alias(args.name, serial)
    _out(f"{args.name} -> {serial}")
    return 0


def cmd_key(args: argparse.Namespace) -> int:
    serial = target.resolve(args.device)
    for name in args.keys:
        code = actions.press(name, serial=serial, repeat=args.repeat)
        _out(f"{name} -> {code}")
    return 0


def cmd_keys(args: argparse.Namespace) -> int:
    if args.json:
        _json(keys.KEYS)
        return 0
    for name, code in sorted(keys.KEYS.items()):
        _out(f"{name:<14} {code}")
    return 0


def cmd_text(args: argparse.Namespace) -> int:
    serial = target.resolve(args.device)
    actions.type_text(" ".join(args.words), serial=serial)
    return 0


def cmd_tap(args: argparse.Namespace) -> int:
    _out(actions.tap(args.x, args.y, serial=target.resolve(args.device)))
    return 0


def cmd_swipe(args: argparse.Namespace) -> int:
    _out(actions.swipe(args.x1, args.y1, args.x2, args.y2,
                       serial=target.resolve(args.device), duration_ms=args.ms))
    return 0


def cmd_scroll(args: argparse.Namespace) -> int:
    _out(actions.scroll(args.direction, serial=target.resolve(args.device),
                        amount=args.amount))
    return 0


def cmd_size(args: argparse.Namespace) -> int:
    width, height = actions.screen_size(target.resolve(args.device))
    _out(f"{width}x{height}")
    return 0


def cmd_apps(args: argparse.Namespace) -> int:
    serial = target.resolve(args.device)
    packages = apps.installed(serial, third_party_only=not args.all)
    if args.json:
        _json(packages)
        return 0
    for package in packages:
        _out(package)
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    serial = target.resolve(args.device)
    package = actions.open_app(args.app, serial=serial)
    _out(f"launched {package}")
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    serial = target.resolve(args.device)
    _out(f"stopped {actions.close_app(args.app, serial=serial)}")
    return 0


def cmd_url(args: argparse.Namespace) -> int:
    serial = target.resolve(args.device)
    actions.open_url(args.url, serial=serial, package=args.app)
    _out(f"opened {args.url}")
    return 0


def cmd_youtube(args: argparse.Namespace) -> int:
    serial = target.resolve(args.device)
    query = " ".join(args.query)
    actions.search_youtube(query, serial=serial)
    _out(f"searching YouTube for {query!r}")
    return 0


def cmd_alarm(args: argparse.Namespace) -> int:
    serial = target.resolve(args.device)
    _out(actions.set_alarm(args.time, serial=serial, label=args.label,
                           days=args.days, vibrate=not args.no_vibrate,
                           confirm_on_device=args.confirm))
    return 0


def cmd_timer(args: argparse.Namespace) -> int:
    serial = target.resolve(args.device)
    _out(actions.set_timer(args.duration, serial=serial, label=args.label,
                           confirm_on_device=args.confirm))
    return 0


def cmd_alarms(args: argparse.Namespace) -> int:
    _out(actions.show_alarms(target.resolve(args.device)))
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    serial = target.resolve(args.device)
    snapshot = actions.state(serial)
    if args.json:
        _json(snapshot)
        return 0
    playback = snapshot["playback"]
    _out(f"device:     {serial}")
    _out(f"foreground: {snapshot['foreground'] or 'unknown (transition?)'}")
    _out(f"screen:     {snapshot['screen']}")
    _out(f"playback:   {playback['label']}")
    return 0


def cmd_shot(args: argparse.Namespace) -> int:
    serial = target.resolve(args.device)
    data = adb.screencap(serial)
    if args.output == "-":
        sys.stdout.buffer.write(data)
        return 0
    path = Path(args.output)
    path.write_bytes(data)
    _out(f"{path} ({len(data)} bytes)")
    return 0


def cmd_volume(args: argparse.Namespace) -> int:
    serial = target.resolve(args.device)
    _out(actions.volume(args.action, serial=serial, level=args.level, steps=args.steps))
    return 0


def cmd_off(args: argparse.Namespace) -> int:
    actions.sleep_device(target.resolve(args.device))
    _out("sleeping")
    return 0


def cmd_on(args: argparse.Namespace) -> int:
    actions.wake_device(target.resolve(args.device))
    _out("awake")
    return 0


def cmd_shell(args: argparse.Namespace) -> int:
    serial = target.resolve(args.device)
    sys.stdout.write(adb.shell(" ".join(args.command), serial=serial, timeout=args.timeout))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import run

    return run()


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import serve

    serve()
    return 0


# --- parser -----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adb-ai",
        description="Control the Android devices in your home - TVs, TV boxes, "
                    "phones and tablets - from a terminal or an AI agent.",
    )
    parser.add_argument("--version", action="version", version=f"adb-ai {__version__}")
    parser.add_argument("-d", "--device", dest="global_device", metavar="DEVICE",
                        help="serial, ip[:port] or saved alias")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, func, help_text: str, *, device: bool = True):
        child = sub.add_parser(name, help=help_text, description=help_text)
        child.set_defaults(func=func)
        if device:
            child.add_argument("-d", "--device", help="serial, ip[:port] or saved alias")
        return child

    p = add("devices", cmd_devices, "list the devices adb knows about", device=False)
    p.add_argument("--json", action="store_true")

    p = add("scan", cmd_scan, "find devices on the local network", device=False)
    p.add_argument("subnet", nargs="?", help="prefix such as 192.168.0.")
    p.add_argument("--port", type=int, default=adb.DEFAULT_PORT)
    p.add_argument("--timeout", type=float, default=0.4, help="per-host timeout")
    p.add_argument("--json", action="store_true")

    p = add("connect", cmd_connect, "connect to a device over the network", device=False)
    p.add_argument("target", help="ip[:port] or saved alias")
    p.add_argument("--port", type=int, default=adb.DEFAULT_PORT)
    p.add_argument("--alias", help="remember it under this name (implies --use)")
    p.add_argument("--use", action="store_true", help="make it the default device")

    p = add("disconnect", cmd_disconnect, "drop a network connection", device=False)
    p.add_argument("target", nargs="?")

    p = add("use", cmd_use, "set the default device ('-' to clear)", device=False)
    p.add_argument("target", nargs="?")

    p = add("alias", cmd_alias, "name a device, or list the names", device=False)
    p.add_argument("name", nargs="?", default=None)
    p.add_argument("target", nargs="?", default=None)
    p.add_argument("--remove", action="store_true")

    p = add("key", cmd_key, "press one or more remote-control keys")
    p.add_argument("keys", nargs="+", help="e.g. home ok play volup")
    p.add_argument("-n", "--repeat", type=int, default=1)

    p = add("keys", cmd_keys, "list the key names", device=False)
    p.add_argument("--json", action="store_true")

    p = add("text", cmd_text, "type text into the focused field")
    p.add_argument("words", nargs="+")

    p = add("tap", cmd_tap, "tap a point (phones and tablets)")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)

    p = add("swipe", cmd_swipe, "swipe between two points, or long-press")
    for name in ("x1", "y1", "x2", "y2"):
        p.add_argument(name, type=int)
    p.add_argument("--ms", type=int, default=300, help="duration in milliseconds")

    p = add("scroll", cmd_scroll, "scroll up, down, left or right")
    p.add_argument("direction", choices=["up", "down", "left", "right"])
    p.add_argument("--amount", type=float, default=0.6,
                   help="fraction of the screen to travel (0.1-0.9)")

    add("size", cmd_size, "print the screen size in pixels")

    p = add("apps", cmd_apps, "list installed packages")
    p.add_argument("--all", action="store_true", help="include system packages")
    p.add_argument("--json", action="store_true")

    p = add("open", cmd_open, "launch an app by alias, package or fragment")
    p.add_argument("app")

    p = add("close", cmd_close, "force-stop an app")
    p.add_argument("app")

    p = add("url", cmd_url, "open a URL or deep link")
    p.add_argument("url")
    p.add_argument("--app", help="package to handle it")

    p = add("youtube", cmd_youtube, "search YouTube without the on-screen keyboard")
    p.add_argument("query", nargs="+")

    p = add("alarm", cmd_alarm, "set an alarm in the device's clock app")
    p.add_argument("time", help="7:30, 19:00, 07h05")
    p.add_argument("--label", help="what the alarm is for")
    p.add_argument("--days", help="repeat, e.g. mon,tue,wed,thu,fri")
    p.add_argument("--no-vibrate", action="store_true")
    p.add_argument("--confirm", action="store_true",
                   help="open the clock app instead of creating it silently")

    p = add("timer", cmd_timer, "start a countdown timer")
    p.add_argument("duration", help="10m, 1h30m, 90s")
    p.add_argument("--label")
    p.add_argument("--confirm", action="store_true")

    add("alarms", cmd_alarms, "open the clock app on its alarm list")

    p = add("state", cmd_state, "what is on screen and whether media is playing")
    p.add_argument("--json", action="store_true")

    p = add("shot", cmd_shot, "save a screenshot ('-' for stdout)")
    p.add_argument("output", nargs="?", default="screen.png")

    p = add("volume", cmd_volume, "up, down, mute or set the volume")
    p.add_argument("action", choices=["up", "down", "mute", "set"])
    p.add_argument("level", nargs="?", type=int, default=None)
    p.add_argument("-n", "--steps", type=int, default=1)

    add("off", cmd_off, "put the screen to sleep")
    add("on", cmd_on, "wake the device")

    p = add("shell", cmd_shell, "run a raw shell command on the device")
    p.add_argument("command", nargs="+")
    p.add_argument("--timeout", type=float, default=60.0)

    add("doctor", cmd_doctor, "check Python, adb, devices and config", device=False)
    add("mcp", cmd_mcp, "run the MCP server on stdio (for AI clients)", device=False)

    return parser


MIN_PYTHON = (3, 9)


def _check_python() -> None:
    """Fail with a sentence a human can act on, not a traceback."""
    if sys.version_info >= MIN_PYTHON:
        return
    have = ".".join(str(part) for part in sys.version_info[:3])
    need = ".".join(str(part) for part in MIN_PYTHON)
    raise SystemExit(
        f"adb-ai needs Python {need} or newer, but this is Python {have}.\n"
        "Install a newer one (python.org/downloads, 'brew install python', "
        "'sudo apt install python3', 'pkg install python'), or run adb-ai with "
        "it directly: python3.12 -m adbai"
    )


def main(argv: list[str] | None = None) -> int:
    _check_python()
    parser = build_parser()
    args = parser.parse_args(argv)
    # "adb-ai -d tv key home" and "adb-ai key home -d tv" mean the same thing:
    # a --device given before the subcommand must not lose to the subcommand's
    # own default of None.
    if getattr(args, "device", None) is None:
        args.device = getattr(args, "global_device", None)
    try:
        return args.func(args)
    except (adb.AdbError, LookupError, ValueError) as exc:
        print(f"adb-ai: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
