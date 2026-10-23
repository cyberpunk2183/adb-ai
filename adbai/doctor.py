"""``adb-ai doctor``: check everything needed, and say how to fix what is missing."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys

from . import __version__, adb, config

MIN_PYTHON = (3, 9)

ADB_INSTALL = {
    "Windows": "winget install Google.PlatformTools",
    "Darwin": "brew install android-platform-tools",
    "Linux": "sudo apt install adb      (Debian/Ubuntu)\n"
             "    sudo dnf install android-tools   (Fedora)\n"
             "    sudo pacman -S android-tools     (Arch)",
    "Termux": "pkg install android-tools",
}

PYTHON_INSTALL = {
    "Windows": "winget install Python.Python.3.12   (or python.org/downloads)",
    "Darwin": "brew install python",
    "Linux": "sudo apt install python3 python3-pip",
    "Termux": "pkg install python",
}


def _system() -> str:
    if "com.termux" in sys.prefix or os.environ.get("TERMUX_VERSION"):
        return "Termux"
    return platform.system()


def _line(ok: bool | None, title: str, detail: str = "") -> str:
    mark = {True: "ok  ", False: "FAIL", None: "warn"}[ok]
    return f"[{mark}] {title}" + (f"\n       {detail}" if detail else "")


def run() -> int:
    """Print a report. Returns 0 if adb-ai can work, 1 if something is missing."""
    system = _system()
    report: list[str] = [f"adb-ai {__version__} on {system} ({platform.platform()})", ""]
    failed = False

    # Python ---------------------------------------------------------------
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info >= MIN_PYTHON:
        report.append(_line(True, f"Python {version}"))
    else:
        failed = True
        needed = ".".join(str(part) for part in MIN_PYTHON)
        report.append(_line(False, f"Python {version} is too old (need {needed}+)",
                            PYTHON_INSTALL.get(system, "install a newer Python 3")))

    # adb ------------------------------------------------------------------
    try:
        path = adb.adb_path()
        report.append(_line(True, "adb found", path))
        try:
            out = subprocess.run([path, "version"], capture_output=True, timeout=15)
            first = out.stdout.decode("utf-8", "replace").splitlines()[0]
            report.append(_line(True, first.strip()))
        except Exception as exc:  # the binary is there but will not run
            failed = True
            report.append(_line(False, "adb will not run", str(exc)))
    except adb.AdbError:
        failed = True
        report.append(_line(False, "adb not found - this is the one real requirement",
                            ADB_INSTALL.get(system, "install Android platform-tools")))

    # Devices --------------------------------------------------------------
    if not failed:
        try:
            found = adb.devices()
        except adb.AdbError as exc:
            found = []
            report.append(_line(None, "could not list devices", str(exc)))
        if found:
            for device in found:
                state = True if device.online else None
                hint = "" if device.online else "run 'adb-ai connect' again and accept the dialog on the device"
                report.append(_line(state, device.describe(), hint))
        else:
            report.append(_line(None, "no devices connected",
                                "'adb-ai scan' looks for them on your network"))

    # Config ---------------------------------------------------------------
    stored = config.load()
    default = stored["default"] or "none set"
    aliases = ", ".join(f"{k}={v}" for k, v in stored["aliases"].items()) or "none"
    report.append(_line(True, f"config: {config.config_path()}",
                        f"default device: {default}  |  aliases: {aliases}"))

    if shutil.which("adb") is None and not failed:
        report.append(_line(None, "adb is not on your PATH",
                            "found through ADBAI_ADB or a known location - fine, "
                            "but plain 'adb' will not work in your shell"))

    report.append("")
    report.append("ready to go." if not failed else
                  "fix the FAIL lines above, then run 'adb-ai doctor' again.")
    print("\n".join(report))
    return 1 if failed else 0
