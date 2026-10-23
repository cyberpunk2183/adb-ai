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

### `foreground: unknown (transition?)`

Harmless. The window manager has no focused window for a moment while an app
starts. Wait a second and ask again.

### An agent connected but every tool fails

The MCP server runs as a separate process with its own environment — often a
minimal PATH, especially for GUI apps on macOS. Give it absolute paths; see
[the MCP setup](AGENTS.md#claude-desktop-cursor-and-other-clients).

### `adb_shell` refuses to run

By design. Set `ADBAI_ALLOW_SHELL=1` in the server's environment if you really
want an agent to have raw shell on a device in your home.

---

Still stuck? Open an issue with the output of `adb-ai doctor` and the exact
command you ran: <https://github.com/cyberpunk2183/adb-ai/issues>
