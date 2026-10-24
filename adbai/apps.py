"""Turn names a human would say ("netflix") into package names."""

from __future__ import annotations

import time

from . import adb

# Candidates are tried in order; the TV build of an app comes first because
# that is what a living-room device usually has.
ALIASES: dict[str, list[str]] = {
    "youtube": ["com.google.android.youtube.tv", "com.google.android.youtube"],
    "youtubemusic": ["com.google.android.youtube.tvmusic",
                     "com.google.android.apps.youtube.music"],
    "youtubekids": ["com.google.android.youtube.tvkids", "com.google.android.apps.youtube.kids"],
    "netflix": ["com.netflix.ninja", "com.netflix.mediaclient"],
    "prime": ["com.amazon.amazonvideo.livingroom", "com.amazon.avod.thirdpartyclient"],
    "disney": ["com.disney.disneyplus"],
    "max": ["com.wbd.stream"],
    "globoplay": ["com.globo.globotv", "com.globo.globotv.tv"],
    "spotify": ["com.spotify.tv.android", "com.spotify.music"],
    "twitch": ["tv.twitch.android.viewer", "tv.twitch.android.app"],
    "crunchyroll": ["com.crunchyroll.crunchyroid"],
    "appletv": ["com.apple.atve.androidtv.appletv"],
    "plex": ["com.plexapp.android"],
    "kodi": ["org.xbmc.kodi"],
    "vlc": ["org.videolan.vlc"],
    "chrome": ["com.android.chrome"],
    "browser": ["com.android.chrome", "org.mozilla.firefox", "com.android.browser"],
    "playstore": ["com.android.vending"],
    "settings": ["com.android.tv.settings", "com.android.settings"],
}


# `pm list packages` is one of the slowest things we ask a device, and the
# answer only changes when something is installed or removed. Every
# `open`/`close` resolves a name through it, so an agent opening three apps in
# a row paid for three listings.
PACKAGES_TTL = 60.0
_packages_cache: dict[tuple[str | None, bool], tuple[float, list[str]]] = {}


def forget_packages() -> None:
    """Drop the cached package lists - after installing or removing an app."""
    _packages_cache.clear()


def installed(serial: str | None = None, third_party_only: bool = False,
              *, fresh: bool = False) -> list[str]:
    """Package names present on the device, cached for ``PACKAGES_TTL``."""
    key = (serial, third_party_only)
    now = time.monotonic()
    cached = _packages_cache.get(key)
    if not fresh and cached is not None and now - cached[0] < PACKAGES_TTL:
        return cached[1]

    flags = "pm list packages" + (" -3" if third_party_only else "")
    out = adb.shell(flags, serial=serial)
    packages = sorted(
        line.strip().removeprefix("package:")
        for line in out.splitlines()
        if line.strip().startswith("package:")
    )
    _packages_cache[key] = (now, packages)
    return packages


def resolve(name: str, serial: str | None = None) -> str:
    """Find the best installed package for ``name``.

    Accepts an alias ("netflix"), a full package name, or a fragment of one.
    """
    wanted = name.strip()
    packages = installed(serial)
    present = set(packages)

    if wanted in present:
        return wanted

    for candidate in ALIASES.get(wanted.lower().replace(" ", "").replace("+", ""), []):
        if candidate in present:
            return candidate

    needle = wanted.lower()
    matches = [pkg for pkg in packages if needle in pkg.lower()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        # Prefer a package whose last segment is exactly the name, e.g. ".youcinetv"
        exact = [pkg for pkg in matches if pkg.rsplit(".", 1)[-1].lower() == needle]
        if len(exact) == 1:
            return exact[0]
        raise LookupError(
            f"{name!r} matches several packages: {', '.join(matches[:10])}. "
            "Pass the full package name."
        )

    raise LookupError(
        f"no installed package matches {name!r}. Run 'adb-ai apps' to list them."
    )
