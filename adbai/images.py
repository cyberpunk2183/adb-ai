"""Making a screenshot small enough to be worth handing to a model.

A 4K television's screencap is several megabytes of PNG, and a phone's is over
one. A vision model scales the picture down the moment it arrives, so those
megabytes buy nothing: they cost upload time, they cost tokens, and - the part
you actually feel - they cost seconds before the agent says anything back.

So when ffmpeg is around, we scale the picture to something a model can read
and re-encode it; when it is not, the full PNG goes as it always did. ffmpeg is
optional, like scrcpy, and unlike scrcpy it installs fine everywhere, Termux
included.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

from . import adb

FFMPEG_INSTALL = {
    "Windows": "winget install Gyan.FFmpeg",
    "Darwin": "brew install ffmpeg",
    "Linux": "sudo apt install ffmpeg           (Debian/Ubuntu)\n"
             "    sudo dnf install ffmpeg          (Fedora)\n"
             "    sudo pacman -S ffmpeg            (Arch)",
    "Termux": "pkg install ffmpeg",
}

# Big enough that UI text stays readable, small enough to stop paying for
# pixels the model is going to throw away.
DEFAULT_MAX_SIZE = 1280

# Below this, do not bother. Measured, because the intuition is wrong: PNG is
# very good at flat colours, so a 4K settings screen or a TV home row arrives
# as about 30KB, and re-encoding it would spend the best part of a second to
# save fifteen kilobytes. The screens worth shrinking are the ones with artwork
# or a video frame in them, and those are megabytes.
SHRINK_ABOVE = 250_000


def _candidate_paths() -> Iterable[Path]:
    yield Path("/opt/homebrew/bin/ffmpeg")
    yield Path("/usr/local/bin/ffmpeg")
    yield Path("/data/data/com.termux/files/usr/bin/ffmpeg")


def ffmpeg_path() -> str:
    """Locate ffmpeg, or explain how to get it."""
    override = os.environ.get("ADBAI_FFMPEG") or os.environ.get("FFMPEG")
    if override:
        if not Path(override).exists():
            raise adb.AdbError(f"ADBAI_FFMPEG points to a missing file: {override}")
        return override

    found = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if found:
        return found

    for candidate in _candidate_paths():
        if candidate.exists():
            return str(candidate)

    raise adb.AdbError(
        "ffmpeg not found. It is optional: without it screenshots are sent at "
        "full size, which is slower and costs an agent more tokens.\n"
        f"  {FFMPEG_INSTALL.get(adb.current_system(), 'install ffmpeg')}\n"
        "Or point ADBAI_FFMPEG at the binary."
    )


def available() -> bool:
    try:
        ffmpeg_path()
        return True
    except adb.AdbError:
        return False


def shrink(data: bytes, *, max_size: int = DEFAULT_MAX_SIZE, quality: int = 3,
           jpeg: bool = True, above: int = SHRINK_ABOVE) -> tuple[bytes, str]:
    """Scale an image down, returning ``(bytes, mime type)``.

    Never upscales, keeps the aspect ratio, leaves small pictures alone, and -
    importantly - never fails: anything wrong with ffmpeg and you get the
    original bytes back, because a big screenshot is worth more than an error
    message.
    """
    if max_size <= 0 or len(data) < above:
        return data, "image/png"
    try:
        binary = ffmpeg_path()
    except adb.AdbError:
        return data, "image/png"

    # min() on both sides means the box can only ever shrink the picture.
    scale = (f"scale=w='min({int(max_size)},iw)':h='min({int(max_size)},ih)'"
             ":force_original_aspect_ratio=decrease:flags=bicubic")
    cmd = [binary, "-hide_banner", "-loglevel", "error",
           "-f", "image2pipe", "-i", "pipe:0",
           "-vf", scale, "-frames:v", "1"]
    # The encoder has to be named. Writing to a pipe there is no filename to
    # guess from, and ffmpeg's guess is JPEG - which would quietly put JPEG
    # bytes in a file called .png.
    if jpeg:
        cmd += ["-c:v", "mjpeg", "-q:v", str(int(quality)), "-f", "image2pipe"]
        mime = "image/jpeg"
    else:
        cmd += ["-c:v", "png", "-f", "image2pipe"]
        mime = "image/png"
    cmd += ["pipe:1"]

    try:
        proc = subprocess.run(cmd, input=data, capture_output=True, timeout=30,
                              shell=False)
    except (OSError, subprocess.SubprocessError):
        return data, "image/png"

    if proc.returncode != 0 or not proc.stdout:
        return data, "image/png"
    # Shrinking that did not shrink is not worth a second format to debug.
    if len(proc.stdout) >= len(data):
        return data, "image/png"
    return proc.stdout, mime
