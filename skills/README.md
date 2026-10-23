# Claude Code skill

Copy `adb-remote/` into one of these and restart Claude Code:

| Scope | Path |
|---|---|
| Just you, everywhere | `~/.claude/skills/adb-remote/` |
| One project | `<project>/.claude/skills/adb-remote/` |

```bash
mkdir -p ~/.claude/skills
cp -r skills/adb-remote ~/.claude/skills/
```

Then ask in plain language: *"put on YouTube on the TV"*, *"pause whatever is
playing"*, *"what's on the living-room screen?"*. The skill tells Claude how to
use `adbctl`, including checking its own work with `adbctl state`.

Prefer tools over a shell? Use the MCP server instead - see the main README.
