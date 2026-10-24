"""scrcpy: a live window onto the device, for the human in the loop.

ADB-AI's other commands are a remote control: one action, one answer. This is
the other half of being able to trust it - you watch the screen while the agent
drives, and you take the mouse back whenever you want.

scrcpy is optional. It is a second binary, it needs a desktop to draw on, and
nothing else here depends on it; when it is missing we say how to get it and
carry on.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence

from . import adb, config

SCRCPY_INSTALL = {
    "Windows": "winget install Genymobile.scrcpy    (or: scoop install scrcpy)",
    "Darwin": "brew install scrcpy",
    "Linux": "sudo apt install scrcpy          (Debian/Ubuntu)\n"
             "    sudo dnf install scrcpy          (Fedora)\n"
             "    sudo pacman -S scrcpy            (Arch)",
    "Termux": "scrcpy does not work from Termux - see TERMUX_NOTE.",
}

# Tested the hard way: scrcpy is not in Termux's default repo, and the X11
# route (x11-repo plus the Termux:X11 app) does not get there either. Rather
# than hand someone an SDL error, say so.
TERMUX_NOTE = (
    "scrcpy does not work from Termux. It is not in the default repo, and the "
    "X11 route (x11-repo plus the Termux:X11 app) does not get it running "
    "either - mirroring a phone onto the same phone is not what it is for.\n"
    "Everything else in adb-ai works here. To see a device's screen from "
    "Termux, use 'adb-ai shot' (an agent gets the same image from "
    "adb_screenshot). To mirror, run adb-ai from a desktop on the same "
    "network.\n"
    "If you did get scrcpy working on Android somehow, point ADBAI_SCRCPY at "
    "the binary and adb-ai will use it."
)


def _refuse_on_termux() -> None:
    """Fail with the explanation instead of letting scrcpy fail without one."""
    if adb.current_system() == "Termux" and not os.environ.get("ADBAI_SCRCPY"):
        raise adb.AdbError(TERMUX_NOTE)


def _candidate_paths() -> Iterable[Path]:
    yield Path("/opt/homebrew/bin/scrcpy")
    yield Path("/usr/local/bin/scrcpy")
    yield Path("/snap/bin/scrcpy")
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        yield Path(local_appdata) / "Microsoft" / "WinGet" / "Links" / "scrcpy.exe"


def scrcpy_path() -> str:
    """Locate the scrcpy executable, or explain how to get one."""
    override = os.environ.get("ADBAI_SCRCPY") or os.environ.get("SCRCPY")
    if override:
        if not Path(override).exists():
            raise adb.AdbError(f"ADBAI_SCRCPY points to a missing file: {override}")
        return override

    _refuse_on_termux()

    found = shutil.which("scrcpy") or shutil.which("scrcpy.exe")
    if found:
        return found

    for candidate in _candidate_paths():
        if candidate.exists():
            return str(candidate)

    system = adb.current_system()
    raise adb.AdbError(
        "scrcpy not found. It is optional - everything else in adb-ai works "
        "without it - but 'mirror' and 'record' need it.\n"
        f"  {SCRCPY_INSTALL.get(system, 'See github.com/Genymobile/scrcpy')}\n"
        "Or point ADBAI_SCRCPY at the binary."
    )


_help_cache: str | None = None


def help_text() -> str:
    """scrcpy's own ``--help``, cached.

    Flag names have moved around between releases (``--no-display`` became
    ``--no-playback``, ``--bit-rate`` became ``--video-bit-rate``), so instead
    of guessing from a version number we ask the binary in front of us what it
    accepts.
    """
    global _help_cache
    if _help_cache is None:
        try:
            proc = subprocess.run([scrcpy_path(), "--help"], capture_output=True,
                                  timeout=15, shell=False)
            # Some versions print help on stderr; take both and do not care.
            _help_cache = (proc.stdout + b"\n" + proc.stderr).decode("utf-8", "replace")
        except (OSError, subprocess.SubprocessError):
            _help_cache = ""
    return _help_cache


def supports(flag: str) -> bool:
    """Whether the installed scrcpy accepts a given long option."""
    return flag in help_text()


def version() -> str:
    """The first line of ``scrcpy --version``, e.g. ``scrcpy 3.1``."""
    proc = subprocess.run([scrcpy_path(), "--version"], capture_output=True,
                          timeout=15, shell=False)
    text = (proc.stdout or proc.stderr).decode("utf-8", "replace").strip()
    return text.splitlines()[0].strip() if text else "scrcpy (unknown version)"


def _no_playback_flags() -> list[str]:
    """Record without showing anything, whatever this version calls it."""
    flags = ["--no-playback" if supports("--no-playback") else "--no-display"]
    # Newer builds open a window even with playback off; this closes it.
    if supports("--no-window"):
        flags.append("--no-window")
    return flags


def headless() -> bool:
    """True when there is no display for scrcpy to draw a window on.

    Windows and macOS always have one. On Linux and Termux a missing DISPLAY
    means scrcpy would die with an SDL error that explains nothing.
    """
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return False
    return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def build_command(
    serial: str | None = None,
    *,
    window: bool = True,
    view_only: bool = False,
    record: str | None = None,
    max_size: int | None = None,
    fps: int | None = None,
    bitrate: str | None = None,
    fullscreen: bool = False,
    stay_awake: bool = False,
    screen_off: bool = False,
    audio: bool = True,
    time_limit: int | None = None,
    title: str | None = None,
    extra: Sequence[str] = (),
) -> list[str]:
    """Assemble the scrcpy command line for the options we expose."""
    cmd = [scrcpy_path()]
    if serial:
        cmd += ["-s", serial]
    if view_only:
        cmd.append("--no-control")
    if record:
        cmd.append(f"--record={record}")
    if not window:
        if not record:
            raise ValueError("there is nothing to do with no window and no recording")
        cmd += _no_playback_flags()
    if max_size:
        cmd += ["--max-size", str(int(max_size))]
    if fps and supports("--max-fps"):
        cmd += ["--max-fps", str(int(fps))]
    if bitrate:
        cmd.append(f"--video-bit-rate={bitrate}" if supports("--video-bit-rate")
                   else f"--bit-rate={bitrate}")
    if fullscreen and window:
        cmd.append("--fullscreen")
    if stay_awake:
        cmd.append("--stay-awake")
    if screen_off:
        cmd.append("--turn-screen-off")
    if not audio and supports("--no-audio"):
        cmd.append("--no-audio")
    if time_limit and supports("--time-limit"):
        cmd += ["--time-limit", str(int(time_limit))]
    if title and window and supports("--window-title"):
        cmd.append(f"--window-title={title}")
    cmd += list(extra)
    return cmd


def _require_display(window: bool) -> None:
    _refuse_on_termux()
    if window and headless():
        raise adb.AdbError(
            "no display to open a window on (DISPLAY and WAYLAND_DISPLAY are "
            "both unset). Run this from a desktop session, or record without a "
            "window: 'adb-ai record out.mp4'. To just see what is on screen, "
            "'adb-ai shot' saves a PNG anywhere."
        )


def preflight(window: bool = True) -> str:
    """Check scrcpy can run at all, before we go hunting for a device.

    Worth doing first: "scrcpy does not work here" is more useful than "no
    device connected" to someone who was never going to get a window anyway.
    """
    _refuse_on_termux()
    path = scrcpy_path()
    _require_display(window)
    return path


def mirror(serial: str | None = None, **options) -> int:
    """Open scrcpy and stay in the foreground until the window is closed.

    scrcpy keeps its own stdout and stderr, because its log lines ("INFO:
    Device: ...", codec warnings) are what you need when a device refuses to
    mirror.
    """
    preflight(options.get("window", True))
    cmd = build_command(serial, **options)
    try:
        return subprocess.call(cmd, shell=False)
    except FileNotFoundError as exc:  # pragma: no cover - binary vanished mid-run
        raise adb.AdbError(str(exc)) from exc


# --- running it in the background, for an agent ------------------------------

_running: dict[str, subprocess.Popen] = {}


def log_path() -> Path:
    """Where a backgrounded scrcpy's own output goes, so failures are findable."""
    return config.config_dir() / "scrcpy.log"


def _key(serial: str | None) -> str:
    return serial or ""


def running() -> dict[str, int]:
    """Serial (or ``""`` for the default device) -> pid, for live mirrors only."""
    for key, proc in list(_running.items()):
        if proc.poll() is not None:
            del _running[key]
    return {key: proc.pid for key, proc in _running.items()}


def start(serial: str | None = None, **options) -> subprocess.Popen:
    """Launch scrcpy detached and return at once.

    For callers that cannot block - the MCP server, mostly. One mirror per
    device: asking twice gives you back the one already running.
    """
    running()  # prune
    key = _key(serial)
    if key in _running:
        return _running[key]

    preflight(options.get("window", True))
    cmd = build_command(serial, **options)
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("ab")
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=handle, stderr=handle, shell=False,
            # Do not let a Ctrl-C in the agent's terminal take the window down.
            start_new_session=(os.name != "nt"),
        )
    finally:
        handle.close()
    _running[key] = proc
    return proc


def stop(serial: str | None = None) -> bool:
    """Close a mirror we started. False if there was nothing to close."""
    running()  # prune
    proc = _running.pop(_key(serial), None)
    if proc is None:
        return False
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:  # pragma: no cover - scrcpy ignoring SIGTERM
        proc.kill()
    return True
