# Handing it to an AI agent

Two ways, and you can use both at once.

| | MCP server | Claude Code skill |
|---|---|---|
| Works in | any MCP client: Claude Desktop, Claude Code, Cursor… | Claude Code |
| The model gets | 15 typed tools | instructions for using the CLI through its shell |
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
| `adb_list_apps` | installed packages |
| `adb_open_app` | launch by alias, package or fragment |
| `adb_close_app` | force-stop |
| `adb_open_url` | URL or deep link |
| `adb_youtube_search` | search without the on-screen keyboard |
| `adb_state` | foreground app + screen + playback |
| `adb_screenshot` | PNG, returned as an image |
| `adb_volume` | up / down / mute / set |
| `adb_power` | sleep or wake |
| `adb_shell` | raw shell — **disabled by default** |

Every tool takes an optional `device`, so one agent can drive several devices.

### About `adb_shell`

It refuses to run unless the server's environment has `ADBAI_ALLOW_SHELL=1`.
An agent that can press Play is a houseguest; an agent that can run arbitrary
commands on a device on your network is something else. Turn it on only if you
need it:

```json
{ "mcpServers": { "adb-ai": {
    "command": "adb-ai", "args": ["mcp"],
    "env": { "ADBAI_ALLOW_SHELL": "1" }
} } }
```

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

- **Keep `adb_shell` off** unless you have a reason. The ordinary tools cover
  the remote-control surface.
- **Network debugging is unauthenticated** once you have accepted the dialog.
  Anyone on that network can reach port 5555 — so keep it off guest Wi-Fi, and
  turn it off on the device when you are done experimenting.
- **An agent has no idea what time it is in your living room.** Waking a TV at
  3am is, technically, correct behaviour. Say so in your prompt if that matters.
