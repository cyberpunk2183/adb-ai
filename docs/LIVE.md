# Live view

An agent normally sees a device one screenshot at a time: it asks, the device
runs `screencap`, a PNG crosses the network, and only then can the agent
decide what to do. After a tap it asks again, just to check. Each look is a
second or two, and a five-step task is ten looks.

Live view streams the screen to your computer the whole time. The newest frame
is always waiting, already small, so looking costs nothing - and "tap, then
show me what happened" becomes one call that answers the moment the screen
stops moving.

```
phone ──H.264──► scrcpy ──► window            (you watch)
                    │
                    └──► v4l2loopback ──► ffmpeg ──► newest frame ──► agent
```

## Three sources

| | `v4l2` | `scrcpy` | `screenrecord` |
|---|---|---|---|
| Where | Linux | Linux, macOS | everywhere adb runs, Windows and Termux included |
| Needs | ffmpeg, scrcpy, the v4l2loopback module | ffmpeg, scrcpy | ffmpeg |
| You and the agent see | the same capture | the same capture | two captures of the same screen |
| Frame after an action | as soon as the screen stops | as soon as the screen stops | a screencap, about 1.5 s later |

`auto` (the default) picks the first of these that works here: `v4l2` when a
loopback device exists and there is a desktop for the window, `scrcpy` when
scrcpy can run, and `screenrecord` otherwise. `adb-ai doctor` says which one
you will get.

`scrcpy` records into a named pipe that ffmpeg reads, so it needs nothing in
the kernel. `v4l2` is there for when the loopback is already set up:

```bash
sudo apt install v4l2loopback-dkms
sudo modprobe v4l2loopback exclusive_caps=1 card_label=adb-ai
```

If you have a real webcam too, adb-ai tells the two apart by itself; set
`ADBAI_V4L2=/dev/videoN` to choose explicitly.

### Why screenrecord is slower after an action

The device's video encoder keeps the last frame it was given until the next
one arrives. On a screen that just stopped moving, that last frame is the one
that matters, and screenrecord never sends it: the stream ends one frame
early, with a fading button still half drawn. scrcpy avoids this by asking the
encoder to repeat the previous frame; screenrecord has no such option. So with
`screenrecord`, once the screen has been still for a moment, adb-ai takes a
screencap and uses it in place of the held frame. The picture is right; it
costs the time of one screencap.

## Using it

From an agent, over MCP:

- `adb_live` - start it (returns the first frame), `stop` it, or ask `status`
- `adb_look` - the newest frame, instantly
- `look: true` on `adb_tap`, `adb_tap_text`, `adb_key`, `adb_swipe`,
  `adb_scroll`, `adb_type_text` or `adb_open_app` - do it, then return the
  screen once it settles
- `adb_wait_change` - wait for the screen to change by itself

From the terminal, to see it working and how fast:

```bash
adb-ai live                         # prints a line per change
adb-ai live --out screen.jpg        # and keeps the newest frame in a file
adb-ai live --source scrcpy --no-window   # just the frames, no window
```

## Making it faster

Most of the time between an action and its answer is not adb-ai: it is the
device animating. So while live view runs, the device's three animation scales
are at 0 and every action shows at once. They are put back as they were when
live view stops - including when the agent's process exits. To leave them on:

```bash
adb-ai live --keep-animations
```

Over MCP it is `adb_live` with `animations: true`.

Taps and keys also go faster while live view runs: they are written to one
`adb shell` kept open for the device, instead of starting adb each time, and
use `cmd input`, which talks to the running input service, instead of `input`,
which starts a Java runtime on the device for every command.

Measured on a Xiaomi phone (HyperOS) through `scrcpy`, from sending an action
to having the settled screen, averaged over taps, keys and swipes:

| | per action |
|---|---|
| animations on, a new adb and `input` each time | 1.4-1.5 s |
| animations off, kept shell, `cmd input` | 0.6-1.0 s |

Keys now reach the device in 50-120 ms. What is left is the device: it takes
50-450 ms to start reacting, and HyperOS animates its notification shade and
back gesture with its own engine, which ignores the animation scales. Stock
Android follows them, and gains more.

## How "settled" works

ffmpeg's `mpdecimate` filter drops frames that look like the one before, so a
frame only arrives here when the screen really changed. After an action the
view waits up to 1.5 s for the first change (none: `unchanged`), then until
nothing new has arrived for 0.35 s (`settled`) - not less, because animations
measured on a phone pause for up to that long halfway through, giving up after 4 s on a
screen that keeps moving - a video, a spinner (`moving`).

Three things in the pipeline would each hold the last frame back until the
*next* change, which is exactly the frame you want when a screen stops: the
H.264 parser (it only ends a frame when the next one starts), frame-threaded
decoding and encoding, and ffmpeg's `fps` filter. So: adb-ai sends an access
unit delimiter whenever the device goes quiet for 30 ms, runs both codecs on
one thread, and caps the frame rate at scrcpy (`--fps`) instead of in ffmpeg.

## Limits

- **The agent does not watch video.** It sees a frame when it asks for one or
  when an action returns. Live view removes the waiting around each look; the
  agent's own thinking between steps is still there.
- **Frames are scaled down** to 1280 px on the long side. The text sent with
  each frame gives the factor that turns what the agent sees into the screen
  coordinates `adb_tap` expects.
- **`screenrecord` stops every three minutes** on most Android versions; adb-ai
  restarts it, and the newest frame stays available across the gap.
- **On a phone, live view is a continuous screenshot.** Everything that crosses
  the screen reaches the agent. Turn it on for a task and off after.
