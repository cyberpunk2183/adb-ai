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

## Two sources

| | `v4l2` | `screenrecord` |
|---|---|---|
| Where | Linux | everywhere adb runs |
| Needs | ffmpeg, scrcpy, the v4l2loopback module | ffmpeg |
| You and the agent see | the same capture | two captures of the same screen |

`auto` (the default) uses `v4l2` when a loopback device exists and there is a
desktop to open the window on, and `screenrecord` otherwise. `adb-ai doctor`
says which one you will get.

To get `v4l2` on Debian, Ubuntu or Kali:

```bash
sudo apt install v4l2loopback-dkms
sudo modprobe v4l2loopback exclusive_caps=1 card_label=adb-ai
```

If you have a real webcam too, adb-ai tells the two apart by itself; set
`ADBAI_V4L2=/dev/videoN` to choose explicitly.

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
adb-ai live --source screenrecord --no-window
```

## How "settled" works

ffmpeg's `mpdecimate` filter drops frames that look like the one before, so a
frame only arrives here when the screen really changed. After an action the
view waits up to 1.5 s for the first change (none: `unchanged`), then until
nothing new has arrived for 0.35 s (`settled`), giving up after 4 s on a
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
