# adbctl

**Control the Android devices in your home — a TV, a streaming box, a phone, a
tablet — from your terminal, or let an AI agent do it for you.**

One command, no Python dependencies, same behaviour on Windows, Linux, macOS and
Termux. Ships three ways to use it:

- a **CLI** you can use on its own: `adbctl open netflix`
- an **MCP server** for Claude Desktop, Claude Code, Cursor and friends
- a **Claude Code skill**, so you can just say *"put on YouTube on the TV"*

```console
$ adbctl scan
192.168.0.102:5555

$ adbctl connect 192.168.0.102 --alias tv
connected to 192.168.0.102:5555
saved alias 'tv' -> 192.168.0.102:5555
default device is now 192.168.0.102:5555

$ adbctl open youtube
launched com.google.android.youtube.tv

$ adbctl youtube "lofi hip hop"
searching YouTube for 'lofi hip hop'

$ adbctl state
device:     192.168.0.102:5555
foreground: com.google.android.youtube.tv/com.google.android.apps.youtube.tv.MainActivity
screen:     Awake
playback:   playing
```

## Requirements

Python 3.9+ and the `adb` binary. `requirements.txt` is deliberately empty of
packages — everything is standard library — but **adb is not a Python package**,
so install it with your system's package manager:

| System | Command |
|---|---|
| Termux | `pkg install android-tools` |
| Debian/Ubuntu | `sudo apt install adb` |
| Fedora | `sudo dnf install android-tools` |
| Arch | `sudo pacman -S android-tools` |
| macOS | `brew install android-platform-tools` |
| Windows | `winget install Google.PlatformTools` |

Check it with `adb version`. If adb lives somewhere unusual, point `ADBCTL_ADB`
at the binary.

## Install

```bash
git clone https://github.com/cyberpunk2183/adbctl
cd adbctl
pip install -r requirements.txt   # confirms there is nothing to install
pip install .                     # or: pipx install .
```

No install needed either — `python -m adbctl ...` works straight from the clone.

## Turn on debugging on the device

This is the step people get stuck on.

- **Android TV / streaming box:** Settings → Device Preferences → About → click
  *Build* seven times → back → Developer options → enable **Network debugging**
  (sometimes *ADB debugging* / *USB debugging*).
- **Phone or tablet:** Settings → About → tap *Build number* seven times →
  Developer options → enable **Wireless debugging**. Newer Android versions
  need a pairing code: `adb pair <ip>:<port>` once, then `adbctl connect`.
- **USB first, wireless after:** plug it in, run `adb tcpip 5555`, unplug, then
  `adbctl scan`.

The first connection shows a dialog on the device asking you to allow this
computer. Say yes and tick *always allow*, or nothing will connect.

## Commands

```
adbctl devices                      list what adb knows about
adbctl scan [192.168.0.]            find devices on the local network
adbctl connect <ip> [--alias tv]    connect, optionally remember the name
adbctl use <alias|serial>           set the default device
adbctl alias [name] [target]        name a device, or list the names

adbctl key home | ok | play | ...   press keys, in order; -n repeats
adbctl keys                         list every key name
adbctl text "hello there"           type into the focused field

adbctl apps [--all]                 installed packages
adbctl open netflix                 launch by alias, package or fragment
adbctl close netflix                force-stop
adbctl url <url> [--app <pkg>]      open a URL or deep link
adbctl youtube <query>              search YouTube, no on-screen keyboard

adbctl state [--json]               foreground app, screen, playback
adbctl shot [out.png]               screenshot ('-' writes to stdout)
adbctl volume up|down|mute|set N    volume
adbctl off | on                     sleep or wake the screen

adbctl shell <cmd>                  raw adb shell, for anything not covered
adbctl mcp                          run the MCP server on stdio
```

Every command takes `-d <alias|serial>`; without it, the default device is used.
`ADBCTL_DEVICE` works too.

## Use it from an AI agent

### MCP server (Claude Desktop, Cursor, any MCP client)

```json
{
  "mcpServers": {
    "adbctl": {
      "command": "adbctl",
      "args": ["mcp"]
    }
  }
}
```

In Claude Code: `claude mcp add adbctl -- adbctl mcp`.

Fifteen tools, including `adb_scan`, `adb_connect`, `adb_key`, `adb_open_app`,
`adb_youtube_search`, `adb_state`, `adb_screenshot` and `adb_volume`. The
screenshot comes back as an image the model can actually look at.

`adb_shell` is **disabled by default** — an agent that can run any command on a
device in your home is a different level of trust from one that can press Play.
Set `ADBCTL_ALLOW_SHELL=1` in the server's environment if you want it.

### Claude Code skill

```bash
mkdir -p ~/.claude/skills && cp -r skills/adb-remote ~/.claude/skills/
```

Then just ask: *"pause the TV"*, *"what's on the living-room screen?"*, *"open
Spotify and play something quiet"*. See [`skills/README.md`](skills/README.md).

## Why not just use `adb` directly?

Because the details bite:

- **DHCP moves your devices.** `adbctl scan` finds them again with plain
  sockets — no nmap, works the same on Windows and Termux.
- **Some devices corrupt their own screenshots.** Several Android TV builds
  print driver noise on stdout before the PNG; a naively saved file is broken.
  `adbctl shot` always cuts to the PNG magic bytes.
- **Not every device has a working `grep`.** All output filtering happens on
  your machine in Python, never with a pipe on the device.
- **Key codes and package names are not memorable.** `adbctl key ok` beats
  `adb shell input keyevent KEYCODE_DPAD_CENTER`, and `adbctl open netflix`
  finds `com.netflix.ninja` or `com.netflix.mediaclient`, whichever is there.
- **"Did it work?"** `adbctl state` answers in one call: foreground app, screen
  state, and whether media is actually playing.

## Scope and good manners

This is a remote control, not a jailbreak. It drives devices **you own and have
enabled debugging on**, over your own network. It does not bypass licence
checks, paywalls or account restrictions, and it has no business touching a
device that is not yours.

A few things worth knowing before you point an agent at your living room:

- ADB over TCP is **unauthenticated once allowed** — anyone on the same network
  can reach port 5555. Keep it on a trusted network, and turn network debugging
  off when you are done.
- Anything with a screen in a shared home is a shared device. An agent that
  wakes the TV at 3am is technically working correctly.

## Development

```bash
python -m unittest discover -s tests    # 21 tests, no device needed
ruff check .
```

Pull requests welcome — especially app aliases for services outside Brazil and
the US, and fixes for device quirks like the screenshot one above.

## Licence

MIT © 2026 Gabriel Amaral
