# ADB-AI

**A universal remote for plugging your Android gear into your AI agent.**

Your TV, TV box, phone or tablet — driven from the terminal, or by
Claude, Codex, Cursor or any other agent that speaks MCP. One dependency-free
Python package, the same on Windows, Linux, macOS and Termux.

[Install](docs/INSTALL.md) · [Tutorial](docs/TUTORIAL.md) · [What it can do](docs/RECIPES.md) · [Use with an AI agent](docs/AGENTS.md) · [How it works](docs/HOW-IT-WORKS.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) · [Leia em português](README.pt-BR.md)

![adb-ai in a terminal: scan the network, connect to the TV, open YouTube, check that it is playing](docs/img/hero.svg)

One command, no Python dependencies, same behaviour on Windows, Linux, macOS and
Termux. Ships three ways to use it:

- a **CLI** you can use on its own: `adb-ai open netflix`
- an **MCP server** for Claude Desktop, Claude Code, Cursor and friends
- a **Claude Code skill**, so you can just say *"put on YouTube on the TV"*

## It really works like that

A TV's launcher, a phone's calculator driven only by taps, and a timer set from
the command line — all captured through ADB-AI itself:

| | |
|---|---|
| ![Android TV home screen](docs/img/demo-tv-home.png) | ![Calculator showing 144 divided by 12](docs/img/demo-phone-calculator.png) |
| The TV menu you drive with `home`, `down`, `ok` | `144 ÷ 12`, typed with `adb-ai tap` |
| ![Clock app counting down from ten minutes](docs/img/demo-phone-timer.png) | ![A note typed into the notes app](docs/img/demo-phone-note.png) |
| `adb-ai timer 10m --label ADB-AI` | `adb-ai text` into a new note |

## Requirements

Two things, and `adb-ai doctor` checks both for you at any time:

```console
$ adb-ai doctor
adb-ai 0.1.0 on Linux (Linux-6.8.0-x86_64-with-glibc2.39)

[ok  ] Python 3.12.3
[ok  ] adb found
       /usr/bin/adb
[ok  ] Android Debug Bridge version 1.0.41
[warn] no devices connected
       'adb-ai scan' looks for them on your network

ready to go.
```

**Python 3.9+** and the **`adb` binary**. `requirements.txt` is deliberately empty of
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

Check it with `adb version`. If adb lives somewhere unusual, point `ADBAI_ADB`
at the binary.

## Install

```bash
git clone https://github.com/cyberpunk2183/adb-ai
cd adb-ai
```

Then pick one:

```bash
./install.sh        # Linux, macOS, Termux - installs what is missing, asks first
.\install.ps1       # Windows (PowerShell)
pip install .       # if you already have adb and would rather do it yourself
```

Add `--check` (`-Check` on Windows) to see what is missing without changing
anything. No install at all is fine too — `python -m adbai ...` works straight
from the clone.

Step-by-step for each system, including turning on debugging on the device:
**[docs/INSTALL.md](docs/INSTALL.md)**.

## Plug it into your agent

This is the point of the project: one line, and your agent can drive your
devices.

**Claude Code**

```bash
claude mcp add adb-ai -- adb-ai mcp
```

**Claude Desktop** — `claude_desktop_config.json`

```json
{ "mcpServers": { "adb-ai": { "command": "adb-ai", "args": ["mcp"] } } }
```

**Codex CLI** — `~/.codex/config.toml`

```toml
[mcp_servers.adb_ai]
command = "adb-ai"
args = ["mcp"]
```

**Cursor** — `~/.cursor/mcp.json`

```json
{ "mcpServers": { "adb-ai": { "command": "adb-ai", "args": ["mcp"] } } }
```

Any other MCP client takes the same shape: run `adb-ai mcp`, talk JSON-RPC over
stdio. Fifteen tools arrive — scan, connect, keys, apps, URLs, YouTube search,
alarms, timers, volume, power, state and screenshots (returned as an image the
model can look at).

Then just ask, in whatever words you use at home:

> *put on YouTube on the TV*
> *pause whatever is playing*
> *what's on the living-room screen?*
> *set an alarm for 7:30 on my phone*

Using Claude Code and prefer it to drive the CLI directly? Copy the skill:

```bash
mkdir -p ~/.claude/skills && cp -r skills/adb-ai ~/.claude/skills/
```

Details, per-client paths and troubleshooting: **[docs/AGENTS.md](docs/AGENTS.md)**.

## Turn on debugging on the device

This is the step people get stuck on.

- **Android TV / TV box:** Settings → Device Preferences → About → click
  *Build* seven times → back → Developer options → enable **Network debugging**
  (sometimes *ADB debugging* / *USB debugging*).
- **Phone or tablet:** Settings → About → tap *Build number* seven times →
  Developer options → enable **Wireless debugging**. Newer Android versions
  need a pairing code: `adb pair <ip>:<port>` once, then `adb-ai connect`.
- **USB first, wireless after:** plug it in, run `adb tcpip 5555`, unplug, then
  `adb-ai scan`.

The first connection shows a dialog on the device asking you to allow this
computer. Say yes and tick *always allow*, or nothing will connect.

## Commands

```
adb-ai devices                      list what adb knows about
adb-ai scan [192.168.0.]            find devices on the local network
adb-ai connect <ip> [--alias tv]    connect, optionally remember the name
adb-ai use <alias|serial>           set the default device
adb-ai alias [name] [target]        name a device, or list the names

adb-ai key home | ok | play | ...   press keys, in order; -n repeats
adb-ai keys                         list every key name
adb-ai text "hello there"           type into the focused field

adb-ai apps [--all]                 installed packages
adb-ai open netflix                 launch by alias, package or fragment
adb-ai close netflix                force-stop
adb-ai url <url> [--app <pkg>]      open a URL or deep link
adb-ai youtube <query>              search YouTube, no on-screen keyboard

adb-ai state [--json]               foreground app, screen, playback
adb-ai shot [out.png]               screenshot ('-' writes to stdout)
adb-ai volume up|down|mute|set N    volume
adb-ai off | on                     sleep or wake the screen

adb-ai doctor                       check Python, adb, devices and config
adb-ai shell <cmd>                  raw adb shell, for anything not covered
adb-ai mcp                          run the MCP server on stdio
```

Every command takes `-d <alias|serial>`; without it, the default device is used.
`ADBAI_DEVICE` works too.

## Use it from an AI agent

### MCP server (Claude Desktop, Cursor, any MCP client)

```json
{
  "mcpServers": {
    "adb-ai": {
      "command": "adb-ai",
      "args": ["mcp"]
    }
  }
}
```

In Claude Code: `claude mcp add adb-ai -- adb-ai mcp`.

Fifteen tools, including `adb_scan`, `adb_connect`, `adb_key`, `adb_open_app`,
`adb_youtube_search`, `adb_state`, `adb_screenshot` and `adb_volume`. The
screenshot comes back as an image the model can actually look at.

`adb_shell` is **disabled by default** — an agent that can run any command on a
device in your home is a different level of trust from one that can press Play.
Set `ADBAI_ALLOW_SHELL=1` in the server's environment if you want it.

### Claude Code skill

```bash
mkdir -p ~/.claude/skills && cp -r skills/adb-ai ~/.claude/skills/
```

Then just ask: *"pause the TV"*, *"what's on the living-room screen?"*, *"open
Spotify and play something quiet"*. See [`skills/README.md`](skills/README.md).

## Why not just use `adb` directly?

Because the details bite:

- **DHCP moves your devices.** `adb-ai scan` finds them again with plain
  sockets — no nmap, works the same on Windows and Termux.
- **Some devices corrupt their own screenshots.** Several Android TV builds
  print driver noise on stdout before the PNG; a naively saved file is broken.
  `adb-ai shot` always cuts to the PNG magic bytes.
- **Not every device has a working `grep`.** All output filtering happens on
  your machine in Python, never with a pipe on the device.
- **Key codes and package names are not memorable.** `adb-ai key ok` beats
  `adb shell input keyevent KEYCODE_DPAD_CENTER`, and `adb-ai open netflix`
  finds `com.netflix.ninja` or `com.netflix.mediaclient`, whichever is there.
- **"Did it work?"** `adb-ai state` answers in one call: foreground app, screen
  state, and whether media is actually playing.

## Scope, and a word of warning

This is a remote control, not a jailbreak. It drives devices **you own and have
enabled debugging on**, over your own network. It does not bypass licence
checks, paywalls or account restrictions.

It also cannot reach a device nobody opened up: ADB debugging lives behind a
hidden menu and a trust dialog that someone has to accept on the device's own
screen, in person.

That said — **any tool that controls devices over a network can be misused**,
and this one is no exception: `scan` sweeps a subnet, and controlling many
devices is this tool in a loop. The authors do not support that use and accept
no responsibility for it. Please read **[DISCLAIMER.md](DISCLAIMER.md)** before
using ADB-AI; the short version is:

- use it only on devices you own or are authorised to administer;
- **ADB over TCP is unauthenticated** once allowed — never expose port 5555 to
  the internet, and turn debugging off when you are done;
- it comes with **no warranty**; you run it, you own the outcome.

**Pointing it at a phone is a bigger decision than pointing it at a TV.** ADB
access to a phone is the same reach you have when it is unlocked in your hand —
any app, any text field, a screenshot of anything on screen, one-time codes
included. See [Phones are not TVs](DISCLAIMER.md#phones-are-not-tvs).

Security policy and hardening checklist: **[SECURITY.md](SECURITY.md)**.

## Development

```bash
python -m unittest discover -s tests    # 24 tests, no device needed
ruff check .
```

Pull requests welcome — especially app aliases for services outside Brazil and
the US, and fixes for device quirks like the screenshot one above.

## Licence

MIT © 2026 cyberpunk2183
