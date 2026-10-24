# Troubleshooting

Start here, always:

```bash
adb-ai doctor
```

It checks your Python version, finds adb, lists devices and prints your config,
with a fix for each thing that is wrong.

---

### `adb-ai: command not found`

`pip install .` put the script in a folder that is not on your PATH. Either add
the folder pip warned you about, or just use the module form — it is identical:

```bash
python -m adbai devices
```

### `adb not found`

adb is not a Python package; `pip` cannot help. See
[installing adb](INSTALL.md#1-install-adb). If it is installed but somewhere
unusual:

```bash
export ADBAI_ADB=/full/path/to/adb
```

### `adb-ai needs Python 3.9 or newer`

You have an old Python, or the `python` on your PATH is a different one from
the Python you installed. Try `python3 -m adbai`, `py -3 -m adbai` on
Windows, or a specific version: `python3.12 -m adbai`.

### `adb-ai scan` finds nothing

In order of likelihood:

1. **Debugging is not enabled** on the device. This is almost always it — see
   [the setup steps](INSTALL.md#3-enable-debugging-on-the-device).
2. **The device is asleep.** Some TVs drop the network in standby. Turn it on
   with the real remote once.
3. **Different networks.** Phone on 5GHz guest Wi-Fi, TV on 2.4GHz main, or a
   mesh with client isolation. They must be able to reach each other.
4. **Wrong subnet guessed.** Pass it explicitly: `adb-ai scan 192.168.1.`
5. **Android 11+ phone** using wireless debugging on a random port, not 5555.
   Read the port off the *Wireless debugging* screen and
   `adb-ai connect 192.168.0.50:41234`.

### `failed to connect ... No route to host`

The address is stale — DHCP moved the device. `adb-ai scan` and connect again.
This is normal and will keep happening; it is why `scan` exists.

### `adb pair` fails with `protocol fault (couldn't read status message)`

Your adb was built without mDNS support, and the Android 11+ pairing flow needs
it. Confirm:

```bash
adb mdns check
```

If it answers *"mdns is not supported by this version of adb"*, no pairing code
will ever work with that binary — the code is not the problem. This affects
**Termux's `android-tools`** package, among others.

Two ways out:

1. **Pair from a machine with Google's official platform-tools**, then switch
   the phone to the classic port, which needs no pairing at all:
   ```bash
   adb tcpip 5555      # once, with the phone connected by USB
   ```
   From then on `adb-ai connect <ip>` works from anywhere, including Termux,
   until the phone reboots.
2. **Use a device that already listens on 5555** — Android TVs and TV boxes
   generally do once network debugging is on.

### `device unauthorized`

The device is waiting for you to accept *Allow USB debugging?* on its screen.
Look at the TV, accept, tick *Always allow from this computer*, and run the
command again. If no dialog appears, toggle network debugging off and on.

### `device offline`

The connection went stale, usually after the device slept:

```bash
adb-ai disconnect
adb-ai connect tv
```

If that fails, `adb kill-server` and try once more.

### `more than one device/emulator`

Pass a device, or set a default:

```bash
adb-ai -d tv key home
adb-ai use tv
```

### The screenshot file is corrupt

It should not be — adb-ai trims the junk some devices print before the PNG. If
you still get a broken file, open an issue with the first bytes:

```bash
adb-ai shot - | head -c 64 | od -c | head
```

### `adb-ai open <app>` says it matches several packages

Be specific: `adb-ai apps` lists what is installed, then pass the full package
name. Missing alias? Pull requests to the `ALIASES` table in `adbai/apps.py`
are very welcome.

### The app opened but nothing is playing

Opening is not playing. Check:

```bash
adb-ai state
```

`playback: playing` is the proof. Many apps need an explicit `adb-ai key ok` or
`adb-ai key play` after launching.

### `playback: no media session` while something is clearly playing

Not a bug, and not fixable from here: the app is not publishing a media
session, so the system has nothing to report. `dumpsys media_session` says
"have 0 sessions" on devices where this happens, whatever is on screen.

Read it as "cannot tell", never as "nothing is playing". A screenshot is the
only reliable answer for an app like that, and `adb-ai key play` still works -
the keycode goes to whatever has focus, with or without a session.

### `foreground: unknown (transition?)`

Harmless. The window manager has no focused window for a moment while an app
starts. Wait a second and ask again.

### An agent connected but every tool fails

The MCP server runs as a separate process with its own environment — often a
minimal PATH, especially for GUI apps on macOS. Give it absolute paths; see
[the MCP setup](AGENTS.md#claude-desktop-cursor-and-other-clients).

### A key sequence lands one step short

`adb-ai key down down ok` sends all three keycodes in one call, which is fast
but gives the UI no time between them, and some menus drop what arrives during
an animation. Slow it down:

```bash
adb-ai key down down ok --pace 120
```

From an agent, the same thing is `pace_ms: 120` on `adb_key`.

### Screenshots take forever through an agent

A 4K screen with artwork on it is several megabytes of PNG, and all of it has
to reach the model. Install `ffmpeg` and adb-ai scales the big ones down first
(`pkg install ffmpeg`, `sudo apt install ffmpeg`, `brew install ffmpeg`,
`winget install Gyan.FFmpeg`). `adb-ai doctor` says whether it found it.

To change the size: `max_size` on `adb_screenshot`, `ADBAI_SHOT_MAX` for the
whole server, `--max-size` on `adb-ai shot`. `0` means "send the original".
Screens that are already small are never re-encoded — PNG handles flat colours
better than a re-encode would.

### `adb-ai mirror` says scrcpy was not found

It is optional and separate from adb — nothing else in adb-ai needs it:

| System | Command |
|---|---|
| Debian/Ubuntu | `sudo apt install scrcpy` |
| Fedora | `sudo dnf install scrcpy` |
| Arch | `sudo pacman -S scrcpy` |
| macOS | `brew install scrcpy` |
| Windows | `winget install Genymobile.scrcpy` |

If it is installed somewhere unusual, point `ADBAI_SCRCPY` at the binary.
`adb-ai doctor` confirms what it found.

### `scrcpy does not work from Termux`

It does not, and this is not adb-ai being careful: scrcpy is not in Termux's
default repo, and the x11-repo plus Termux:X11 route does not get it running
either. Everything else in adb-ai works on Termux.

- To see a screen from a phone: `adb-ai shot` (an agent gets the same picture
  from `adb_screenshot`).
- To mirror: run adb-ai from a desktop on the same network.
- If you did somehow get scrcpy running on Android, point `ADBAI_SCRCPY` at it
  and adb-ai will use it.

### `no display to open a window on`

`DISPLAY` and `WAYLAND_DISPLAY` are both unset — usually an SSH session or a
server with no desktop. A mirror needs a screen to draw on; a recording does
not:

```bash
adb-ai record session.mp4
```

### The mirror opens but the mouse does nothing

You are on a TV or a TV box. There is no touchscreen behind that screen, so
taps go nowhere. Use the arrow keys in the scrcpy window, or `adb-ai key`.
`--view-only` makes the window honest about it.

### `adb_shell` says it is switched off

Someone set `ADBAI_NO_SHELL=1` (or `ADBAI_ALLOW_SHELL=0`) in that server's
environment — it is on by default. Remove the variable from your MCP config and
restart the client.

---

Still stuck? Open an issue with the output of `adb-ai doctor` and the exact
command you ran: <https://github.com/cyberpunk2183/adb-ai/issues>
