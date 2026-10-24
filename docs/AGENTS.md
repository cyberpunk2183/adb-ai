# Handing it to an AI agent

Two ways, and you can use both at once.

| | MCP server | Claude Code skill |
|---|---|---|
| Works in | any MCP client: Claude Desktop, Claude Code, Cursor… | Claude Code |
| The model gets | 22 typed tools | instructions for using the CLI through its shell |
| Screenshots | returned as an image the model can look at | saved to a file |
| Setup | one JSON block | copy a folder |

---

## MCP server

The server speaks JSON-RPC over stdio and is written with the standard library
only — no `pip install mcp`, nothing to keep up to date.

### Claude Code

```bash
claude mcp add adb-ai -- adb-ai mcp
```

### Codex CLI

`~/.codex/config.toml`:

```toml
[mcp_servers.adb_ai]
command = "adb-ai"
args = ["mcp"]
```

### Claude Desktop, Cursor, and other clients

Add this to the client's MCP config
(`claude_desktop_config.json`, `~/.cursor/mcp.json`, …):

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

If `adb-ai` is not on the PATH of the app (common on macOS, where GUI apps get
a minimal PATH), give the full paths instead:

```json
{
  "mcpServers": {
    "adb-ai": {
      "command": "/usr/bin/python3",
      "args": ["-m", "adb-ai", "mcp"],
      "env": {
        "PYTHONPATH": "/home/you/adb-ai",
        "ADBAI_ADB": "/usr/bin/adb"
      }
    }
  }
}
```

Restart the client. You should see adb-ai's tools listed.

### The tools

| Tool | What it does |
|---|---|
| `adb_list_devices` | what adb knows about |
| `adb_scan` | find devices on the network (for when DHCP moved one) |
| `adb_connect` | connect by ip\[:port] or alias |
| `adb_key` | press keys, in order, optionally repeated |
| `adb_type_text` | type into the focused field |
| `adb_tap` | tap a point — phones and tablets |
| `adb_swipe` | swipe, or long-press when both points match |
| `adb_scroll` | scroll up / down / left / right |
| `adb_screen_size` | the screen size, so taps can be aimed |
| `adb_list_apps` | installed packages |
| `adb_open_app` | launch by alias, package or fragment |
| `adb_close_app` | force-stop |
| `adb_open_url` | URL or deep link |
| `adb_youtube_search` | search without the on-screen keyboard |
| `adb_state` | foreground app + screen + playback |
| `adb_screenshot` | PNG, returned as an image |
| `adb_volume` | up / down / mute / set |
| `adb_power` | sleep or wake |
| `adb_mirror` | open a live window of the screen **for the human** (scrcpy) |
| `adb_shell` | any shell command: dumpsys, pm, am, settings, content… |

Every tool takes an optional `device`, so one agent can drive several devices.

### Keeping it quick

What an agent feels is not throughput, it is the wait between asking and
answering — and that wait is mostly roundtrips. Each `adb` call costs about
50ms before it even reaches the network, so the server spends some effort
making fewer of them:

| What | Before | Now |
|---|---|---|
| Any tool call | one `adb devices` each time | the device list is remembered for 3s |
| `adb_state` | three `dumpsys` calls, full dumps | one call, filtered on the device, full dumps as fallback |
| `adb_key` with `["down","down","ok"]` | three calls, 120ms apart | one `input keyevent` with all three |
| `adb_open_app`, `adb_close_app` | `pm list packages` every time | that list is remembered for 60s |
| `adb_scroll`, aiming taps | `wm size` every time | remembered for 10s |
| The first call of a session | paid for starting adb and reconnecting | warmed up while the client lists tools |
| `adb_screenshot` | the full-size PNG, megabytes on a 4K screen | scaled down first, when ffmpeg is installed |

Knobs, for when a default is wrong:

- `pace_ms` on `adb_key` goes back to one call per key, for a menu that drops
  keys arriving together.
- `max_size` on `adb_screenshot` sets the longest side (`0` sends the untouched
  PNG), and `ADBAI_SHOT_MAX` sets the default for the whole server. Screens
  that are already small are never re-encoded.
- Nothing is cached for longer than a few seconds, and connecting or
  disconnecting a device drops the device list immediately — so "I just plugged
  it in" still works.

### About `adb_mirror`

This one is not for the model. It runs
[scrcpy](https://github.com/Genymobile/scrcpy) and puts the device's screen in
a window **on your computer**, so you can watch an agent work and grab the
mouse when you want to. The model cannot see that window — its eyes are still
`adb_screenshot` — and the tool description says so, to keep it from assuming
otherwise.

```json
{"action": "start", "view_only": true, "max_size": 1024}
```

`action` is `start`, `stop` or `status`. It needs scrcpy installed and a
desktop session: no window appears over SSH, and **it does not work from
Termux** at all. `record` saves the session to an mp4 — a video of everything
that crosses that screen, so an agent should say so before using it.

### About `adb_shell`

This one runs whatever you give it, as the shell user, with no root. It is on
by default, because the other tools are a remote control and the shell
is everything else: reading `dumpsys` for a device's own state, listing or
clearing an app with `pm`, firing an intent with `am`, reading settings with
`settings get`.

The trade-off is real: an agent that can press Play is a houseguest; an agent
with a shell can uninstall an app, change a setting or wipe an app's data. On a
shared machine, or a device you would rather stayed as it is, switch it off:

```json
{ "mcpServers": { "adb-ai": {
    "command": "adb-ai", "args": ["mcp"],
    "env": { "ADBAI_NO_SHELL": "1" }
} } }
```

`ADBAI_ALLOW_SHELL=0` does the same thing, for anyone who configured it the old
way round.

### Checking it by hand

The server is just a program reading stdin, so you can test it without any
client at all:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | adb-ai mcp
```

---

## Claude Code skill

```bash
mkdir -p ~/.claude/skills
cp -r skills/adb-ai ~/.claude/skills/
```

Restart Claude Code. Now plain language works:

> *put on YouTube on the TV*
> *pause whatever is playing*
> *what's on the living-room screen?*
> *turn the volume down a bit, it's late*

The skill does more than list commands — it tells the model to verify with
`adb-ai state` instead of assuming, to re-scan when an address stops
responding, to say what it is about to do before touching a device in your
home, and to leave `adb-ai shell` alone when a normal command exists.

For one project only, put it in `<project>/.claude/skills/` instead.

---

## Giving an agent sensible limits

These commands move something physical in your house. Worth deciding up front:

- **`adb_shell` is on by default** and can change the device, not just drive
   it. If an agent should only be able to work the remote, set
   `ADBAI_NO_SHELL=1` for that server.
- **Watch it when it matters.** `adb_mirror` (or `adb-ai mirror` in your own
  terminal) is the cheapest oversight there is: the screen in a window, live,
  with the mouse still yours.
- **Network debugging is unauthenticated** once you have accepted the dialog.
  Anyone on that network can reach port 5555 — so keep it off guest Wi-Fi, and
  turn it off on the device when you are done experimenting.
- **An agent has no idea what time it is in your living room.** Waking a TV at
  3am is, technically, correct behaviour.
- **A phone is not a TV.** Enabling debugging on the phone you actually use
  hands the agent your unlocked device: any app, any text field, and a
  screenshot of anything on screen — one-time codes included. Those screenshots
  also leave your device for whatever model provider the agent uses. Prefer a
  spare device, consider `ADBAI_NO_SHELL=1` there, and revoke the
  authorisation when you are done. The full picture:
  [Phones are not TVs](../DISCLAIMER.md#phones-are-not-tvs). Say so in your prompt if that matters.
