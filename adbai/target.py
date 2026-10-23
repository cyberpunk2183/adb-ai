"""Deciding which device a command applies to."""

from __future__ import annotations

import os

from . import adb, config


class NoDeviceError(adb.AdbError):
    pass


def resolve(explicit: str | None = None, *, autoconnect: bool = True) -> str:
    """Work out the serial to act on.

    Order of preference: the argument, ``ADBAI_DEVICE``, the stored default,
    the only connected device. Aliases are expanded, and a network target that
    is configured but not connected is connected on demand.
    """
    candidate = explicit or os.environ.get("ADBAI_DEVICE") or config.load()["default"]

    if candidate:
        serial = adb.normalise_target(config.resolve_alias(candidate))
        online = {d.serial for d in adb.devices() if d.online}
        if serial not in online and ":" in serial and autoconnect:
            adb.connect(serial)
        return serial

    online = [d for d in adb.devices() if d.online]
    if len(online) == 1:
        return online[0].serial
    if not online:
        raise NoDeviceError(
            "no device connected. Try 'adb-ai scan' to find one on the network, "
            "then 'adb-ai connect <ip>'."
        )
    listing = "\n  ".join(d.describe() for d in online)
    raise NoDeviceError(
        "several devices are connected; pick one with --device or "
        f"'adb-ai use <serial>':\n  {listing}"
    )
