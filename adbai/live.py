"""Live view: the screen as a stream an agent can look at without waiting.

``adb_screenshot`` asks the device for a fresh PNG every time - a second or two
of ``screencap`` and transfer before the agent sees anything, and one more of
those after every tap just to check it landed. Live view turns that around:
the screen is streamed to this computer the whole time, ffmpeg decodes it, and
the newest frame is always sitting here, small, as a JPEG. Looking costs
nothing, and "tap, then show me what happened" is one call.

ffmpeg does the change detection too. Its ``mpdecimate`` filter drops frames
that look like the one before, so a frame only reaches us when the screen
actually changed - "has it settled?" is just "has nothing arrived for a
moment?".

Three places the video can come from, best first:

``v4l2``
    scrcpy draws its window as usual and also feeds a v4l2loopback device,
    which ffmpeg reads. One capture, two viewers: the person watches the
    window, the agent reads the frames, and it is the same picture. Linux
    only, and the v4l2loopback kernel module has to be loaded.

``scrcpy``
    scrcpy records into a named pipe that ffmpeg reads - with its window, the
    same one capture for both, without the kernel module; without a window,
    just the frames. Needs scrcpy and a POSIX named pipe: Linux and macOS.

``screenrecord``
    ffmpeg reads H.264 straight from the device's own ``screenrecord``. Works
    wherever adb does, Windows and Termux included. But the device's encoder
    holds on to the last frame until another one comes, so the picture of a
    screen that just stopped moving would be the one before it. scrcpy asks
    the encoder to repeat that frame; screenrecord cannot. So once the screen
    is quiet, a screencap replaces the held frame - always right, about a
    second and a half slower to answer after an action.

ffmpeg is required here, unlike everywhere else in adb-ai: this is the one
feature that is nothing without it.
"""

from __future__ import annotations

import atexit
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import actions, adb, config, images, mirror

SOURCES = ("v4l2", "scrcpy", "screenrecord")

# No cap by default: the person is watching the same capture in a window,
# and a choppy window is worse than a busier ffmpeg.
DEFAULT_FPS: int | None = None
# JPEG quality on ffmpeg's 2-31 scale, lower is better. 5 keeps small UI text
# crisp at a fraction of a PNG's size.
DEFAULT_QUALITY = 5

# "Settled": nothing new for this long after the last change. Not shorter:
# measured on a phone, animations pause for up to 0.35 s halfway through,
# and settling there hands the agent a half-drawn screen.
QUIET_SECONDS = 0.35

# Android's three animation scales. Turned to 0 while live view runs - by
# default, since they are most of the wait after every action - so what the
# agent does lands at once instead of after a fade. Put back afterwards.
ANIMATION_SETTINGS = ("window_animation_scale", "transition_animation_scale",
                      "animator_duration_scale")
# How long an action gets to show any change at all before we decide it did
# not visibly do anything.
CHANGE_SECONDS = 1.5
# A playing video never settles; stop waiting after this.
SETTLE_TIMEOUT = 4.0

# An access unit delimiter. The H.264 parser only knows a frame is complete
# when the next one starts, so on a screen that stops moving the last frame -
# the one that matters - would sit in ffmpeg until something else changed.
# Feeding a delimiter whenever the device goes quiet ends the frame there.
AUD = b"\x00\x00\x00\x01\x09\xf0"
# How long the device must be quiet before we decide a frame is complete.
AUD_IDLE = 0.03

# screenrecord stops on its own after three minutes on most Android versions.
SCREENRECORD_LIMIT = 180

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"


@dataclass(frozen=True)
class Frame:
    seq: int
    at: float        # time.monotonic() when it arrived
    data: bytes      # a JPEG

    @property
    def age(self) -> float:
        return time.monotonic() - self.at

    def size(self) -> tuple[int, int]:
        return jpeg_size(self.data)


def jpeg_size(data: bytes) -> tuple[int, int]:
    """(width, height) from a JPEG's frame header, without decoding it."""
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            index += 1 if marker == 0xFF else 2
            continue
        length = int.from_bytes(data[index + 2:index + 4], "big")
        # SOF0-SOF15, except DHT (C4), JPG (C8) and DAC (CC).
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = int.from_bytes(data[index + 5:index + 7], "big")
            width = int.from_bytes(data[index + 7:index + 9], "big")
            return width, height
        index += 2 + length
    raise ValueError("no frame header in JPEG")


def split_jpegs(buffer: bytearray) -> list[bytes]:
    """Take every complete JPEG off the front of ``buffer``, in place.

    ffmpeg's mjpeg encoder writes no thumbnails and stuffs every 0xFF in the
    image data, so the first end-of-image marker after a start-of-image is
    the end of that picture.
    """
    out: list[bytes] = []
    while True:
        start = buffer.find(SOI)
        if start < 0:
            # Keep a trailing 0xFF: it may be half of the next marker.
            del buffer[:max(0, len(buffer) - 1)]
            return out
        end = buffer.find(EOI, start + 2)
        if end < 0:
            del buffer[:start]
            return out
        out.append(bytes(buffer[start:end + 2]))
        del buffer[:end + 2]


def log_path() -> Path:
    return config.config_dir() / "live.log"


# --- finding a v4l2loopback device -------------------------------------------

def loopback_devices(sys_root: Path = Path("/sys/class/video4linux")) -> list[str]:
    """``/dev/videoN`` nodes that belong to v4l2loopback, not a real camera.

    A loopback device is virtual, so its sysfs entry resolves under
    ``/sys/devices/virtual``; a webcam's resolves under a USB or PCI bus.
    """
    if not sys.platform.startswith("linux") or not sys_root.is_dir():
        return []
    found = []
    for entry in sorted(sys_root.iterdir(), key=lambda p: _video_index(p.name)):
        try:
            resolved = str(entry.resolve())
        except OSError:
            continue
        if "/devices/virtual/" in resolved:
            found.append(f"/dev/{entry.name}")
    return found


def _video_index(name: str) -> int:
    digits = name[len("video"):] if name.startswith("video") else ""
    return int(digits) if digits.isdigit() else 1 << 30


LOOPBACK_HELP = (
    "v4l2loopback is not loaded, so scrcpy has nowhere to share its picture.\n"
    "  sudo apt install v4l2loopback-dkms      (Debian/Ubuntu/Kali)\n"
    "  sudo modprobe v4l2loopback exclusive_caps=1 card_label=adb-ai\n"
    "Or use source='screenrecord', which needs nothing extra."
)


def scrcpy_problem() -> str | None:
    """Why the ``scrcpy`` source cannot run here, or None if it can."""
    if not hasattr(os, "mkfifo"):
        return ("source='scrcpy' needs a POSIX named pipe, which Windows does not "
                "have; use 'screenrecord'")
    try:
        mirror.preflight(window=False)
    except adb.AdbError as exc:
        return str(exc)
    return None


def pick_source(requested: str | None) -> tuple[str, str | None]:
    """Resolve ``auto`` and check the choice can work: ``(source, v4l2 device)``."""
    choice = (requested or "auto").lower()
    if choice not in ("auto", *SOURCES):
        raise ValueError(f"unknown source {requested!r}: "
                         "use auto, v4l2, scrcpy or screenrecord")

    wanted = os.environ.get("ADBAI_V4L2")
    devices = [wanted] if wanted else loopback_devices()

    if choice == "screenrecord":
        return "screenrecord", None
    if choice == "v4l2":
        if not sys.platform.startswith("linux"):
            raise adb.AdbError("source='v4l2' is Linux only; use 'screenrecord'")
        if not devices:
            raise adb.AdbError(LOOPBACK_HELP)
        return "v4l2", devices[0]
    if choice == "scrcpy":
        problem = scrcpy_problem()
        if problem:
            raise adb.AdbError(problem)
        return "scrcpy", None

    # auto: share scrcpy's capture when we can, since then the person and the
    # agent are looking at literally the same frames; screenrecord is last
    # because its final frame has to be fetched separately.
    if scrcpy_problem() is None:
        if devices and not mirror.headless():
            return "v4l2", devices[0]
        return "scrcpy", None
    return "screenrecord", None


# --- the ffmpeg side ---------------------------------------------------------

_fps_mode_flag: str | None = None


def _fps_mode(ffmpeg: str) -> list[str]:
    """Pass frames through as they come, whatever this ffmpeg calls that.

    Without it ffmpeg duplicates frames to hold a constant rate, and the
    duplicates would look like changes.
    """
    global _fps_mode_flag
    if _fps_mode_flag is None:
        try:
            # Only the long help lists it; the short one lists neither.
            out = subprocess.run([ffmpeg, "-hide_banner", "-h", "long"], capture_output=True,
                                 timeout=15, shell=False)
            text = (out.stdout + out.stderr).decode("utf-8", "replace")
        except (OSError, subprocess.SubprocessError):
            text = ""
        _fps_mode_flag = "-fps_mode" if "fps_mode" in text else "-vsync"
    return [_fps_mode_flag, "vfr"]


def ffmpeg_command(ffmpeg: str, source: str, *, device: str | None = None,
                   max_size: int = images.DEFAULT_MAX_SIZE,
                   quality: int = DEFAULT_QUALITY) -> list[str]:
    """ffmpeg reading the stream and writing one JPEG per change to stdout."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin"]
    # Latency over everything: no probing, and one thread on each side - a
    # frame-threaded codec holds a frame per thread, so the picture you get
    # is the one from a few changes ago. Not "-fflags nobuffer", though: the
    # raw H.264 demuxer drops every frame with it.
    cmd += ["-flags", "low_delay", "-probesize", "32", "-analyzeduration", "0",
            "-threads", "1"]
    if source == "v4l2":
        if not device:
            raise ValueError("v4l2 needs a device")
        cmd += ["-f", "v4l2", "-i", device]
    elif source == "scrcpy":
        if not device:
            raise ValueError("scrcpy needs the pipe it records into")
        cmd += ["-f", "matroska", "-i", device]
    elif source == "screenrecord":
        cmd += ["-f", "h264", "-i", "pipe:0"]
    else:
        raise ValueError(f"unknown source {source!r}")

    size = int(max_size)
    # No fps filter: it holds each frame until it has seen the next, which is
    # exactly the frame we want when the screen stops. The rate is capped at
    # the source instead (scrcpy --max-fps).
    filters = ["mpdecimate"]
    if size > 0:
        filters.append(f"scale=w='min({size},iw)':h='min({size},ih)'"
                       ":force_original_aspect_ratio=decrease:flags=bicubic")
    # The mjpeg encoder only takes full-range YUV; video arrives limited-range.
    filters.append("format=yuvj420p")
    cmd += ["-vf", ",".join(filters)]
    cmd += _fps_mode(ffmpeg)
    cmd += ["-threads", "1", "-c:v", "mjpeg", "-q:v", str(int(quality)),
            "-f", "image2pipe", "-flush_packets", "1", "pipe:1"]
    return cmd


def screenrecord_command(size: tuple[int, int] | None, bitrate: int = 4_000_000) -> list[str]:
    """The adb arguments for a raw H.264 stream on stdout."""
    args = ["exec-out", "screenrecord", "--output-format=h264",
            f"--bit-rate={int(bitrate)}", f"--time-limit={SCREENRECORD_LIMIT}"]
    if size:
        args.append(f"--size={size[0]}x{size[1]}")
    return args + ["-"]


def encode_size(width: int, height: int, max_size: int) -> tuple[int, int] | None:
    """A smaller size for the device's encoder, or None to leave it native.

    Encoding small on the device is less to send over wifi. Both sides are
    multiples of 16, which every encoder accepts; screenrecord letterboxes the
    rounding, which is a few pixels.
    """
    longest = max(width, height)
    if max_size <= 0 or longest <= max_size:
        return None
    scale = max_size / longest
    w = max(16, int(round(width * scale / 16)) * 16)
    h = max(16, int(round(height * scale / 16)) * 16)
    return w, h


def pump(read: Callable[[], bytes], write: Callable[[bytes], None],
         *, idle: float = AUD_IDLE, stop: threading.Event | None = None) -> None:
    """Copy H.264 from ``read`` to ``write``, ending each frame when input pauses.

    ``read`` blocks and returns b"" at end of stream. A thread does the
    reading so this side can notice silence on every platform - a plain
    ``select`` does not work on pipes on Windows.
    """
    chunks: queue.Queue[bytes] = queue.Queue()

    def reader() -> None:
        try:
            while True:
                chunk = read()
                chunks.put(chunk)
                if not chunk:
                    return
        except (OSError, ValueError):
            chunks.put(b"")

    threading.Thread(target=reader, daemon=True, name="adbai-live-read").start()
    pending = False
    while stop is None or not stop.is_set():
        try:
            chunk = chunks.get(timeout=idle)
        except queue.Empty:
            if pending:
                write(AUD)
                pending = False
            continue
        if not chunk:
            if pending:
                write(AUD)
            return
        write(chunk)
        pending = True


# --- the view ----------------------------------------------------------------

class LiveView:
    """One device's screen, streaming in the background."""

    def __init__(self, serial: str | None, *, source: str = "auto", window: bool = True,
                 max_size: int = images.DEFAULT_MAX_SIZE, fps: int | None = DEFAULT_FPS,
                 quality: int = DEFAULT_QUALITY, animations: bool = False) -> None:
        self.serial = serial
        self.animations = animations
        self._saved_animations: dict[str, str] | None = None
        self.requested = source
        self.window = window
        self.max_size = int(max_size)
        self.fps = int(fps) if fps else None
        self.quality = int(quality)
        self.source: str | None = None
        self.device: str | None = None
        self.screen: tuple[int, int] | None = None
        self.started_at = 0.0

        self._cond = threading.Condition()
        self._frame: Frame | None = None
        self._seq = 0
        self._stop = threading.Event()
        self._ffmpeg: subprocess.Popen | None = None
        self._adb: subprocess.Popen | None = None
        self._runner: threading.Thread | None = None
        self._mirror_owned = False
        self._error: str | None = None
        self._log = None
        self._pipe_dir: str | None = None
        self._scrcpy: subprocess.Popen | None = None
        # screenrecord only: the newest frame came from the stream, so it may
        # be the one before what is really on screen (see the module doc).
        self._stale = False

    # -- lifecycle --

    def start(self) -> "LiveView":
        ffmpeg = images.ffmpeg_path()
        self.source, self.device = pick_source(self.requested)
        self.screen = actions.screen_size(self.serial)
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._log = path.open("ab")
        self._log.write(f"\n--- live {self.serial or 'default'} via {self.source} "
                        f"at {time.strftime('%Y-%m-%d %H:%M:%S')}\n".encode())
        self._log.flush()

        if not self.animations:
            self._animations_off()
        try:
            actions.keep_shell(self.serial)
        except (OSError, adb.AdbError) as exc:
            self._note(f"no kept shell, taps go through plain adb: {exc}")
        if self.source == "v4l2":
            self._start_scrcpy_sink()
        pipe = None
        if self.source == "scrcpy":
            self._pipe_dir = tempfile.mkdtemp(prefix="adbai-live-")
            pipe = os.path.join(self._pipe_dir, "screen.mkv")
            os.mkfifo(pipe)

        cmd = ffmpeg_command(ffmpeg, self.source, device=pipe or self.device,
                             max_size=self.max_size, quality=self.quality)
        self.started_at = time.monotonic()
        if self.source == "v4l2":
            self._runner = self._spawn(lambda: self._run_v4l2(cmd), "adbai-live-v4l2")
        elif self.source == "scrcpy":
            assert pipe is not None
            # ffmpeg first: opening a pipe waits for the other end, and scrcpy
            # only opens it once the first frame is on its way.
            self._launch_ffmpeg(cmd, stdin=subprocess.DEVNULL)
            try:
                self._start_scrcpy_recorder(pipe)
            except Exception:
                self.stop()
                raise
            self._runner = self._spawn(self._run_scrcpy, "adbai-live-scrcpy")
        else:
            self._launch_ffmpeg(cmd, stdin=subprocess.PIPE)
            self._runner = self._spawn(self._run_screenrecord_reader, "adbai-live-frames")
            self._spawn(self._feed_screenrecord, "adbai-live-feed")
            if self.window and not mirror.headless():
                self._start_window()
        return self

    def _spawn(self, target: Callable[[], None], name: str) -> threading.Thread:
        thread = threading.Thread(target=target, daemon=True, name=name)
        thread.start()
        return thread

    def _launch_ffmpeg(self, cmd: list[str], stdin: int) -> subprocess.Popen:
        self._ffmpeg = subprocess.Popen(
            cmd, stdin=stdin, stdout=subprocess.PIPE, stderr=self._log, shell=False,
            bufsize=0, start_new_session=(os.name != "nt"),
        )
        return self._ffmpeg

    def _start_scrcpy_sink(self) -> None:
        # A mirror already open without the sink cannot be given one, so it is
        # replaced by one that has it. The person sees the window blink.
        mirror.stop(self.serial)
        extra = [f"--v4l2-sink={self.device}"]
        if self.fps and mirror.supports("--max-fps"):
            extra += ["--max-fps", str(self.fps)]
        if self.window and not mirror.headless():
            title = " ".join(filter(None, ["adb-ai", self.serial, "(live)"]))
            mirror.start(self.serial, title=title, audio=False, extra=extra)
        else:
            mirror.start(self.serial, window=False, audio=False, sink=True, extra=extra)
        self._mirror_owned = True

    @property
    def quiet(self) -> float:
        """How long the screen must be still to count as settled."""
        return QUIET_SECONDS

    def _animations_off(self) -> None:
        saved: dict[str, str] = {}
        for name in ANIMATION_SETTINGS:
            value = adb.shell(f"settings get global {name}", serial=self.serial).strip()
            saved[name] = value if value and value != "null" else "1.0"
        self._saved_animations = saved
        for name in ANIMATION_SETTINGS:
            adb.shell(f"settings put global {name} 0", serial=self.serial)
        self._note("animations off: " + ", ".join(f"{k}={v}" for k, v in saved.items()))

    def _animations_back(self) -> None:
        saved, self._saved_animations = self._saved_animations, None
        if not saved:
            return
        for name, value in saved.items():
            try:
                adb.shell(f"settings put global {name} {value}", serial=self.serial)
            except adb.AdbError as exc:
                self._note(f"could not put {name} back to {value}: {exc}")

    def _start_scrcpy_recorder(self, pipe: str) -> None:
        mirror.stop(self.serial)
        window = self.window and not mirror.headless()
        extra = ["--record-format=mkv"]
        if self.fps and mirror.supports("--max-fps"):
            extra += ["--max-fps", str(self.fps)]
        title = " ".join(filter(None, ["adb-ai", self.serial, "(live)"]))
        # With a window the person gets the full picture and ffmpeg scales it;
        # without one, encoding small on the device is less to send.
        self._scrcpy = mirror.start(self.serial, record=pipe, window=window, audio=False,
                                    title=title if window else None,
                                    max_size=None if window else (self.max_size or None),
                                    extra=extra)
        self._mirror_owned = True

    def _start_window(self) -> None:
        try:
            mirror.start(self.serial, title=" ".join(filter(None, ["adb-ai", self.serial])))
            self._mirror_owned = True
        except adb.AdbError as exc:
            self._note(f"no window for the person: {exc}")

    def stop(self) -> None:
        self._stop.set()
        for proc in (self._adb, self._ffmpeg):
            if proc is not None and proc.poll() is None:
                proc.terminate()
        for proc in (self._adb, self._ffmpeg):
            if proc is None:
                continue
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:  # pragma: no cover
                proc.kill()
        if self._mirror_owned:
            mirror.stop(self.serial)
        actions.drop_shell(self.serial)
        self._animations_back()
        if self._pipe_dir is not None:
            shutil.rmtree(self._pipe_dir, ignore_errors=True)
            self._pipe_dir = None
        with self._cond:
            self._cond.notify_all()
        if self._log is not None:
            self._log.close()
            self._log = None

    @property
    def alive(self) -> bool:
        return (not self._stop.is_set() and self._error is None
                and self._runner is not None and self._runner.is_alive())

    def _note(self, message: str) -> None:
        if self._log is not None and not self._log.closed:
            try:
                self._log.write((message + "\n").encode("utf-8", "replace"))
                self._log.flush()
            except (OSError, ValueError):
                pass

    # -- the threads --

    def _read_frames(self, proc: subprocess.Popen) -> int:
        """Publish every frame ffmpeg writes until it stops; how many there were."""
        assert proc.stdout is not None
        buffer = bytearray()
        count = 0
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            buffer += chunk
            for data in split_jpegs(buffer):
                count += 1
                with self._cond:
                    self._seq += 1
                    self._frame = Frame(self._seq, time.monotonic(), data)
                    self._stale = self.source == "screenrecord"
                    self._cond.notify_all()
        proc.wait()
        return count

    def _fail(self, message: str) -> None:
        if not self._stop.is_set():
            self._error = message
            self._note(message)
        with self._cond:
            self._cond.notify_all()

    def _run_screenrecord_reader(self) -> None:
        assert self._ffmpeg is not None
        self._read_frames(self._ffmpeg)
        self._fail("ffmpeg stopped - see " + str(log_path()))

    def _run_scrcpy(self) -> None:
        """Read frames until scrcpy stops recording into the pipe.

        If scrcpy dies before it ever opens the pipe, ffmpeg would wait on it
        forever; a watcher ends ffmpeg then, so the failure gets reported.
        """
        assert self._ffmpeg is not None and self._scrcpy is not None
        ffmpeg, scrcpy = self._ffmpeg, self._scrcpy

        def watch() -> None:
            while not self._stop.is_set() and ffmpeg.poll() is None:
                if scrcpy.poll() is not None:
                    time.sleep(1.0)  # let ffmpeg finish what it was sent
                    if ffmpeg.poll() is None:
                        ffmpeg.terminate()
                    return
                time.sleep(0.3)

        self._spawn(watch, "adbai-live-watch")
        got = self._read_frames(ffmpeg)
        if self._stop.is_set():
            return
        if got and self.window and not mirror.headless():
            self._fail("the scrcpy window was closed, and live view with it. "
                       "Start it again with adb_live.")
        else:
            self._fail(f"scrcpy stopped sending the screen - see {mirror.log_path()} "
                       f"and {log_path()}")

    def _run_v4l2(self, cmd: list[str]) -> None:
        """Keep ffmpeg reading the loopback for as long as scrcpy feeds it.

        With exclusive_caps the device cannot even be opened for reading until
        scrcpy has written to it, and scrcpy takes a moment to get going - so
        the first attempts are expected to fail, and are retried.
        """
        startup = 20.0
        while not self._stop.is_set():
            got = self._read_frames(self._launch_ffmpeg(cmd, stdin=subprocess.DEVNULL))
            if self._stop.is_set():
                break
            if mirror._key(self.serial) not in mirror.running():
                self._fail("the scrcpy window was closed, and live view with it. "
                           "Start it again with adb_live.")
                break
            if not got and time.monotonic() - self.started_at > startup:
                self._fail(f"no picture from {self.device} after {startup:g}s - see "
                           f"{log_path()} and {mirror.log_path()}")
                break
            time.sleep(0.3)
        with self._cond:
            self._cond.notify_all()

    def _feed_screenrecord(self) -> None:
        assert self._ffmpeg is not None and self._ffmpeg.stdin is not None
        sink = self._ffmpeg.stdin
        size = encode_size(*self.screen, self.max_size) if self.screen else None
        cmd_base = [adb.adb_path()] + (["-s", self.serial] if self.serial else [])

        def write(data: bytes) -> None:
            sink.write(data)
            sink.flush()

        failures = 0
        while not self._stop.is_set():
            began = time.monotonic()
            self._adb = subprocess.Popen(
                cmd_base + screenrecord_command(size), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=self._log, shell=False, bufsize=0,
            )
            out = self._adb.stdout
            assert out is not None
            got = [0]

            def read() -> bytes:
                data = out.read(65536)
                got[0] += len(data)
                return data

            try:
                pump(read, write, stop=self._stop)
            except (BrokenPipeError, OSError, ValueError):
                break  # ffmpeg is gone; _read_frames reports it
            self._adb.wait()
            if self._stop.is_set():
                break
            # It ran and ended: the time limit. Start the next stretch.
            if got[0] and time.monotonic() - began > 5:
                failures = 0
                continue
            failures += 1
            if size is not None:
                # Some encoders refuse sizes they did not pick themselves.
                self._note(f"screenrecord refused --size={size[0]}x{size[1]}; "
                           "trying the native size")
                size = None
                continue
            if failures >= 3:
                self._error = ("screenrecord will not run on this device - see "
                               f"{log_path()}")
                break
            time.sleep(0.5)
        try:
            sink.close()
        except OSError:
            pass

    # -- looking --

    @property
    def error(self) -> str | None:
        return self._error

    def latest(self, timeout: float = 5.0) -> Frame:
        """The newest frame, waiting for the first one if the stream just started."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._frame is None:
                self._raise_if_dead()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise adb.AdbError("no picture from the device yet - see "
                                       + str(log_path()))
                self._cond.wait(remaining)
            return self._frame

    def current(self, timeout: float = 5.0) -> Frame:
        """The newest frame, made right if the stream may be holding one back.

        Instant from scrcpy and v4l2. From screenrecord, once the screen has
        been still for a moment, a screencap replaces the frame the device's
        encoder is sitting on.
        """
        frame = self.latest(timeout)
        if self._stale and frame.age >= self.quiet:
            return self.refresh()
        return frame

    def refresh(self) -> Frame:
        """Replace a possibly held-back screenrecord frame with a screencap.

        The frame keeps its sequence number: it is the same moment, seen
        properly, not a change. A stream frame that arrived while the
        screencap was being taken does not win over it: it is held back like
        every screenrecord frame, so it shows an earlier moment than the
        screencap does. Anything that arrives after this is newer, and
        replaces it as usual.
        """
        with self._cond:
            frame = self._frame
            if frame is None or not self._stale:
                return self.latest()
        try:
            png = adb.screencap(self.serial)
        except adb.AdbError as exc:
            self._note(f"could not refresh the last frame: {exc}")
            return frame
        data, mime = images.shrink(png, max_size=self.max_size, quality=self.quality,
                                   above=0)
        if mime != "image/jpeg":
            self._note("could not turn the screencap into a JPEG; keeping the stream's frame")
            return frame
        with self._cond:
            self._frame = Frame(self._seq, time.monotonic(), data)
            self._stale = False
            return self._frame

    def seq(self) -> int:
        with self._cond:
            return self._seq

    def wait_change(self, after: int, timeout: float) -> Frame | None:
        """The first frame newer than ``after``, or None if none came in time."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._seq <= after:
                self._raise_if_dead()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)
            return self._frame

    def wait_settled(self, after: int, *, change: float = CHANGE_SECONDS,
                     quiet: float | None = None,
                     timeout: float = SETTLE_TIMEOUT) -> tuple[Frame, str]:
        """After an action: wait for it to show, then for the screen to stop moving.

        Returns the frame and one of ``settled``, ``unchanged`` (nothing
        visibly happened) or ``moving`` (still changing at the timeout - a
        video, an animation).
        """
        if quiet is None:
            quiet = self.quiet
        began = time.monotonic()
        first = self.wait_change(after, change)
        if first is None:
            return self.current(), "unchanged"
        with self._cond:
            while True:
                self._raise_if_dead()
                now = time.monotonic()
                frame = self._frame
                assert frame is not None
                if now - frame.at >= quiet:
                    break
                if now - began >= timeout:
                    return frame, "moving"
                self._cond.wait(min(quiet - (now - frame.at), timeout - (now - began)))
        return self.refresh() if self._stale else frame, "settled"

    def _raise_if_dead(self) -> None:
        if self._error:
            raise adb.AdbError(self._error)
        if self._stop.is_set():
            raise adb.AdbError("live view was stopped")

    def describe(self, frame: Frame) -> str:
        """The line that goes with a frame: what it is and how to aim at it."""
        width, height = frame.size()
        text = f"frame {frame.seq}, {frame.age:.1f}s old, {width}x{height}"
        if self.screen:
            sw, sh = self.screen
            scale = sw / width if width else 1.0
            text += f" of a {sw}x{sh} screen"
            if abs(scale - 1.0) > 0.01:
                text += (f" - tap coordinates are screen pixels: multiply what you "
                         f"see by {scale:.3f}")
        return text

    def status(self) -> dict[str, object]:
        frame = self._frame
        return {
            "device": self.serial or "default device",
            "source": self.source,
            "v4l2_device": self.device,
            "last_frame": ("from the stream - a screencap replaces it once the "
                           "screen is still" if self._stale else "current"),
            "alive": self.alive,
            "error": self._error,
            "frames": self._seq,
            "last_frame_age_s": round(frame.age, 2) if frame else None,
            "uptime_s": round(time.monotonic() - self.started_at, 1),
            "window": mirror._key(self.serial) in mirror.running(),
            "animations": "off until live view stops" if self._saved_animations else "as set",
        }


# --- one view per device -----------------------------------------------------

_views: dict[str, LiveView] = {}
_views_lock = threading.Lock()


def _key(serial: str | None) -> str:
    return serial or ""


def get(serial: str | None) -> LiveView | None:
    """The running view of a device, if there is one that is still alive."""
    with _views_lock:
        view = _views.get(_key(serial))
        if view is not None and not view.alive and view.error is None:
            del _views[_key(serial)]
            return None
        return view


_atexit_registered = False


def start(serial: str | None, **options) -> LiveView:
    """Start a view, or hand back the one already running for this device."""
    global _atexit_registered
    if not _atexit_registered:
        # Whatever happens to this process, the device gets its animations back.
        atexit.register(stop_all)
        _atexit_registered = True
    with _views_lock:
        view = _views.get(_key(serial))
        if view is not None and view.alive:
            return view
        if view is not None:
            view.stop()
        view = LiveView(serial, **options)
        try:
            view.start()
        except BaseException:
            view.stop()
            raise
        _views[_key(serial)] = view
        return view


def stop(serial: str | None) -> bool:
    with _views_lock:
        view = _views.pop(_key(serial), None)
    if view is None:
        return False
    view.stop()
    return True


def stop_all() -> None:
    with _views_lock:
        views = list(_views.values())
        _views.clear()
    for view in views:
        view.stop()


def running() -> Iterable[LiveView]:
    with _views_lock:
        return list(_views.values())
