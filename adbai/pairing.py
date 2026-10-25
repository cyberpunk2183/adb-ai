"""Pairing an Android 11+ device by camera, instead of by typing.

Wireless debugging on a phone or tablet asks for a one-time pairing before it
will accept a connection. The screen offers two ways through: a six-digit code
you read and type, or a QR code the device's own camera reads. The second one
is strictly better - nothing to mistype, and the port, which is random on every
attempt, never has to be copied by hand.

What happens, end to end:

1. We invent a service name and a password and draw them as a QR:
   ``WIFI:T:ADB;S:<name>;P:<password>;;``
2. The device reads it, opens its pairing port and announces itself on the
   local network over mDNS as ``_adb-tls-pairing._tcp``.
3. We find that announcement, run ``adb pair`` against it with the password we
   just made up, and then connect on the port it advertises for debugging
   (``_adb-tls-connect._tcp``).

Step 2 is where this gets its own code. ``adb`` can do the discovery itself,
but Termux's build is compiled without mDNS, which is exactly where people need
the help - so when adb cannot look, we listen on the multicast socket and parse
the DNS ourselves.

A QR is a desktop-first idea. The device that scans cannot be the device the
terminal is on, so pairing a phone from the Termux running on that same phone
is not a thing this can do - see docs/TROUBLESHOOTING.md.
"""

from __future__ import annotations

import os
import secrets
import socket
import struct
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from . import adb

PAIRING_SERVICE = "_adb-tls-pairing._tcp.local."
CONNECT_SERVICE = "_adb-tls-connect._tcp.local."
MDNS_GROUP = "224.0.0.251"
MDNS_PORT = 5353


@dataclass
class Credentials:
    """What goes into the QR, and what we will pair with afterwards."""

    name: str
    password: str

    @property
    def payload(self) -> str:
        return f"WIFI:T:ADB;S:{self.name};P:{self.password};;"


@dataclass
class Service:
    """An mDNS announcement we can act on."""

    name: str
    host: str
    port: int

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"


def new_credentials(name: Optional[str] = None, password: Optional[str] = None) -> Credentials:
    """A fresh name and password. Both are throwaway - they live one pairing.

    The password is not a secret you keep; it is a secret for the next thirty
    seconds, shown on your screen on purpose. It still comes from ``secrets``,
    because anything on the network that guesses it before the device arrives
    gets paired in the device's place.
    """
    return Credentials(
        name=name or f"adb-ai-{secrets.token_hex(4)}",
        password=password or secrets.token_hex(6),
    )


# --- mDNS, the part adb will not always do for us ----------------------------


def _encode_name(name: str) -> bytes:
    out = bytearray()
    for label in name.rstrip(".").split("."):
        raw = label.encode("utf-8")
        out.append(len(raw))
        out.extend(raw)
    out.append(0)
    return bytes(out)


def _decode_name(data: bytes, offset: int) -> Tuple[str, int]:
    """Read a DNS name, following compression pointers.

    ``after`` is where the record continues, which is not where the name ends
    when the name was a pointer into an earlier part of the packet.
    """
    labels: List[str] = []
    after = -1
    seen = 0
    while True:
        if offset >= len(data) or seen > 64:  # a loop in a hostile packet
            break
        length = data[offset]
        if length == 0:
            offset += 1
            break
        if length & 0xC0 == 0xC0:
            pointer = struct.unpack_from(">H", data, offset)[0] & 0x3FFF
            if after < 0:
                after = offset + 2
            offset = pointer
            seen += 1
            continue
        labels.append(data[offset + 1:offset + 1 + length].decode("utf-8", "replace"))
        offset += 1 + length
    return ".".join(labels) + ".", (after if after >= 0 else offset)


def _query(service: str) -> bytes:
    header = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)
    # QU bit (0x8000) on the class: ask for a unicast answer, so this works
    # from an ephemeral port when something else already owns 5353.
    return header + _encode_name(service) + struct.pack(">HH", 12, 0x8001)


def _parse(data: bytes) -> Tuple[Dict[str, Tuple[str, int]], Dict[str, str], List[Tuple[str, str]]]:
    """Pull SRV, A and PTR records out of an mDNS packet.

    Returns (srv by instance name, address by host name, PTR pairs).
    """
    srv: Dict[str, Tuple[str, int]] = {}
    hosts: Dict[str, str] = {}
    ptrs: List[Tuple[str, str]] = []
    try:
        _, _, questions, answers, authority, additional = struct.unpack_from(">HHHHHH", data, 0)
    except struct.error:
        return srv, hosts, ptrs

    offset = 12
    for _ in range(questions):
        _, offset = _decode_name(data, offset)
        offset += 4

    for _ in range(answers + authority + additional):
        if offset >= len(data):
            break
        name, offset = _decode_name(data, offset)
        if offset + 10 > len(data):
            break
        rtype, _rclass, _ttl, length = struct.unpack_from(">HHIH", data, offset)
        offset += 10
        body = data[offset:offset + length]
        if rtype == 33 and length >= 7:  # SRV
            port = struct.unpack_from(">H", body, 4)[0]
            host, _ = _decode_name(data, offset + 6)
            srv[name] = (host, port)
        elif rtype == 1 and length == 4:  # A
            hosts[name] = socket.inet_ntoa(body)
        elif rtype == 12:  # PTR
            instance, _ = _decode_name(data, offset)
            ptrs.append((name, instance))
        offset += length
    return srv, hosts, ptrs


def _open_socket() -> socket.socket:
    """A socket that hears mDNS answers, sharing 5353 when it can.

    On a desktop running avahi or Bonjour, port 5353 is already taken. With
    SO_REUSEPORT we join anyway and see everything; without it we fall back to
    an ephemeral port, which still works because the query asks for a unicast
    reply.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    try:
        sock.bind(("", MDNS_PORT))
        sock.setsockopt(
            socket.IPPROTO_IP,
            socket.IP_ADD_MEMBERSHIP,
            struct.pack("4s4s", socket.inet_aton(MDNS_GROUP), socket.inet_aton("0.0.0.0")),
        )
    except OSError:
        sock.bind(("", 0))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
    sock.settimeout(0.5)
    return sock


def _adb_mdns_services() -> List[Tuple[str, str, str]]:
    """What adb's own discovery sees, or nothing if this adb has none.

    Output is one service per line: name, type, then address.
    """
    try:
        result = subprocess.run(
            [adb.adb_path(), "mdns", "services"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError, adb.AdbError):
        return []
    found = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1].startswith("_adb"):
            found.append((parts[0], parts[1], parts[2]))
    return found


def discover(
    service: str = PAIRING_SERVICE,
    timeout: float = 60.0,
    want_name: Optional[str] = None,
    on_wait: Optional[Callable[[float], None]] = None,
) -> Optional[Service]:
    """Wait for a device to announce ``service``, and say where it is.

    ``want_name`` is preferred when several devices answer at once, but it is
    not required: in practice the only device announcing a pairing port while
    you stand there holding a phone is that phone, and some builds announce
    under a name of their own instead of the one from the QR.
    """
    short = service.split(".")[0]
    deadline = time.monotonic() + timeout
    sock = _open_socket()
    query = _query(service)
    srv: Dict[str, Tuple[str, int]] = {}
    hosts: Dict[str, str] = {}
    seen: Dict[str, str] = {}
    adb_has_mdns = True
    last_query = 0.0

    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now - last_query > 1.5:
                last_query = now
                try:
                    sock.sendto(query, (MDNS_GROUP, MDNS_PORT))
                except OSError:
                    pass
                if adb_has_mdns:
                    services = _adb_mdns_services()
                    if not services:
                        adb_has_mdns = False
                    for name, kind, address in services:
                        if not kind.startswith(short):
                            continue
                        host, _, port = address.rpartition(":")
                        if port.isdigit():
                            found = Service(name, host, int(port))
                            if want_name is None or name.startswith(want_name):
                                return found
                            seen[name] = ""
                if on_wait:
                    on_wait(max(0.0, deadline - now))

            try:
                data, _ = sock.recvfrom(9000)
            except (socket.timeout, OSError):
                continue

            new_srv, new_hosts, ptrs = _parse(data)
            srv.update(new_srv)
            hosts.update(new_hosts)
            for owner, instance in ptrs:
                if owner.startswith(short):
                    seen[instance] = owner

            candidates = [n for n in srv if n.endswith(service)] or list(seen)
            if want_name:
                preferred = [n for n in candidates if n.startswith(want_name)]
                candidates = preferred or candidates
            for name in candidates:
                if name not in srv:
                    continue
                host, port = srv[name]
                ip = hosts.get(host)
                if ip:
                    return Service(name.split(".")[0], ip, port)
    finally:
        sock.close()
    return None


# --- pairing ----------------------------------------------------------------


def pair(address: str, password: str, timeout: float = 30.0) -> str:
    """Run ``adb pair``. The password goes in on stdin, not in the command.

    An argument is visible to anyone who can list processes; one pairing's
    throwaway password is not worth much, but there is no reason to publish it.
    """
    result = subprocess.run(
        [adb.adb_path(), "pair", address],
        input=password + "\n", capture_output=True, text=True, timeout=timeout,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0 or "uccessfully paired" not in output:
        raise adb.AdbError(output or f"adb pair {address} failed without saying why")
    return output


def pair_with_qr(
    credentials: Credentials,
    timeout: float = 60.0,
    connect: bool = True,
    on_event: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, object]:
    """Wait for the scan, pair, and connect. Returns what happened.

    ``on_event(kind, message)`` is called as it goes, because the interesting
    part of this command is the waiting.
    """
    def say(kind: str, message: str) -> None:
        if on_event:
            on_event(kind, message)

    say("waiting", "waiting for the device to scan the code")
    found = discover(PAIRING_SERVICE, timeout=timeout, want_name=credentials.name)
    if found is None:
        raise adb.AdbError(
            "no device announced a pairing port.\n"
            "On the device: Settings > Developer options > Wireless debugging > "
            "'Pair device with QR code', then point it at the code.\n"
            "Both have to be on the same Wi-Fi, and some routers block the "
            "multicast that discovery needs - 'Pair device with pairing code' "
            "and 'adb-ai pair <ip>:<port> <code>' is the way through that."
        )

    say("found", f"device announced {found.address}")
    message = pair(found.address, credentials.password)
    say("paired", message)

    result: Dict[str, object] = {"paired": found.address, "message": message}
    if not connect:
        return result

    # Pairing and debugging are two different ports; the device announces the
    # second one only once it trusts us.
    debug = discover(CONNECT_SERVICE, timeout=15.0)
    if debug is None:
        result["connected"] = None
        result["note"] = (
            "paired, but the device did not announce its debugging port in time. "
            "'adb-ai scan' then 'adb-ai connect <ip>:<port>' finishes it."
        )
        return result
    result["connected"] = debug.address
    result["message"] = adb.connect(debug.address)
    say("connected", str(result["message"]))
    return result
