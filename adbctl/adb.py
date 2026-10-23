"""Thin, cross-platform wrapper around the ``adb`` binary."""

from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_PORT = 5555
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class AdbError(RuntimeError):
    """Anything that went wrong while talking to adb or a device."""


def _candidate_paths() -> Iterable[Path]:
    home = Path.home()
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        yield Path(local_appdata) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
    yield home / "Android" / "Sdk" / "platform-tools" / "adb"
    yield home / "Library" / "Android" / "sdk" / "platform-tools" / "adb"
    yield Path("/usr/lib/android-sdk/platform-tools/adb")
    yield Path("/opt/homebrew/bin/adb")


def adb_path() -> str:
    """Locate the adb executable, or explain how to get one."""
    override = os.environ.get("ADBCTL_ADB") or os.environ.get("ADB")
    if override:
        if not Path(override).exists():
            raise AdbError(f"ADBCTL_ADB points to a missing file: {override}")
        return override

    found = shutil.which("adb") or shutil.which("adb.exe")
    if found:
        return found

    for candidate in _candidate_paths():
        if candidate.exists():
            return str(candidate)

    raise AdbError(
        "adb not found. Install Android platform-tools and make sure 'adb' is on "
        "your PATH, or point ADBCTL_ADB at the binary.\n"
        "  Termux:  pkg install android-tools\n"
        "  Debian:  sudo apt install adb\n"
        "  macOS:   brew install android-platform-tools\n"
        "  Windows: winget install Google.PlatformTools"
    )


def run(
    args: Sequence[str],
    *,
    serial: str | None = None,
    binary: bool = False,
    timeout: float = 30.0,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run ``adb [-s serial] <args>``.

    Returns the completed process. ``stdout`` is ``bytes`` when ``binary`` is
    set, otherwise text with line endings normalised (adb on Windows and some
    device shells emit CRLF).
    """
    cmd = [adb_path()]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            # Never go through a shell: keeps arguments intact on every platform.
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdbError(f"adb timed out after {timeout:g}s: {' '.join(args)}") from exc
    except FileNotFoundError as exc:  # pragma: no cover - adb vanished mid-run
        raise AdbError(str(exc)) from exc

    stderr = proc.stderr.decode("utf-8", "replace")
    if check and proc.returncode != 0:
        detail = stderr.strip() or proc.stdout.decode("utf-8", "replace").strip()
        raise AdbError(f"adb {' '.join(args)} failed: {detail or 'unknown error'}")

    if binary:
        return subprocess.CompletedProcess(cmd, proc.returncode, proc.stdout, stderr)

    text = proc.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    return subprocess.CompletedProcess(cmd, proc.returncode, text, stderr)


def shell(cmd: str, *, serial: str | None = None, timeout: float = 30.0) -> str:
    """Run a shell command on the device and return its stdout as text."""
    return run(["shell", cmd], serial=serial, timeout=timeout).stdout


@dataclass
class Device:
    serial: str
    state: str
    model: str = ""

    @property
    def is_network(self) -> bool:
        return ":" in self.serial

    @property
    def online(self) -> bool:
        return self.state == "device"

    def describe(self) -> str:
        label = self.model or "unknown model"
        return f"{self.serial}  [{self.state}]  {label}"


def devices() -> list[Device]:
    """Every device adb currently knows about."""
    out = run(["devices", "-l"], check=False).stdout
    found: list[Device] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        serial, state = parts[0], parts[1]
        model = ""
        for token in parts[2:]:
            if token.startswith("model:"):
                model = token.split(":", 1)[1].replace("_", " ")
        found.append(Device(serial, state, model))
    return found


def normalise_target(target: str, port: int = DEFAULT_PORT) -> str:
    """``192.168.0.5`` -> ``192.168.0.5:5555``; USB serials pass through."""
    if ":" in target:
        return target
    try:
        ipaddress.ip_address(target)
    except ValueError:
        return target  # a USB serial or a hostname without a port
    return f"{target}:{port}"


def connect(target: str, port: int = DEFAULT_PORT, timeout: float = 15.0) -> str:
    """Connect to a device over TCP. Returns adb's message."""
    address = normalise_target(target, port)
    out = run(["connect", address], timeout=timeout, check=False).stdout.strip()
    lowered = out.lower()
    if "connected to" not in lowered or "cannot" in lowered or "failed" in lowered:
        raise AdbError(
            f"could not connect to {address}: {out or 'no response from adb'}\n"
            "Check that the device is awake, on the same network, and that "
            "'Network debugging' / 'ADB debugging' is enabled."
        )
    return out


def disconnect(target: str | None = None) -> str:
    args = ["disconnect"] + ([normalise_target(target)] if target else [])
    return run(args, check=False).stdout.strip()


def local_subnets() -> list[str]:
    """Best guess at the /24 prefixes this machine sits on, e.g. ``192.168.0.``"""
    prefixes: list[str] = []

    def add(ip: str) -> None:
        if ip.startswith("127.") or ":" in ip:
            return
        prefix = ip.rsplit(".", 1)[0] + "."
        if prefix not in prefixes:
            prefixes.append(prefix)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packet is sent; this just asks the OS which interface would be used.
        sock.connect(("8.8.8.8", 80))
        add(sock.getsockname()[0])
    except OSError:
        pass
    finally:
        sock.close()

    if not prefixes:
        try:
            for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
                add(ip)
        except OSError:
            pass
    return prefixes


def _port_open(host: str, port: int, timeout: float) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def scan(
    prefix: str | None = None,
    port: int = DEFAULT_PORT,
    timeout: float = 0.4,
    workers: int = 128,
) -> list[str]:
    """Find hosts on the local network with the adb port open.

    Pure sockets, so it needs no nmap and behaves the same on Windows, Linux,
    macOS and Termux.
    """
    prefixes = [prefix] if prefix else local_subnets()
    if not prefixes:
        raise AdbError("could not work out the local subnet; pass one, e.g. 192.168.0.")

    hosts = [f"{p if p.endswith('.') else p + '.'}{i}" for p in prefixes for i in range(1, 255)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda h: (h, _port_open(h, port, timeout)), hosts)
        return [f"{host}:{port}" for host, is_open in results if is_open]


def screencap(serial: str | None = None, timeout: float = 30.0) -> bytes:
    """Grab a PNG screenshot, tolerating devices that pollute the stream.

    Some devices (several Android TV boxes, for instance) print driver noise on
    stdout before the image, which corrupts a naively saved file. We always cut
    everything before the PNG magic bytes.
    """
    proc = run(["exec-out", "screencap", "-p"], serial=serial, binary=True,
               timeout=timeout, check=False)
    data: bytes = proc.stdout or b""

    if PNG_MAGIC not in data:
        # Older devices lack exec-out; fall back to the shell and undo the
        # CRLF mangling that transport adds to binary output.
        proc = run(["shell", "screencap", "-p"], serial=serial, binary=True,
                   timeout=timeout, check=False)
        data = (proc.stdout or b"").replace(b"\r\n", b"\n")

    index = data.find(PNG_MAGIC)
    if index < 0:
        detail = proc.stderr.strip() or data[:120].decode("utf-8", "replace")
        raise AdbError(f"no PNG in screencap output: {detail or 'empty response'}")
    return data[index:]
