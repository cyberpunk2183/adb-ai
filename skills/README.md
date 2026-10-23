# Claude Code skill

Copy `adb-ai/` into one of these and restart Claude Code:

| Scope | Path |
|---|---|
| Just you, everywhere | `~/.claude/skills/adb-ai/` |
| One project | `<project>/.claude/skills/adb-ai/` |

```bash
mkdir -p ~/.claude/skills
cp -r skills/adb-ai ~/.claude/skills/
```

Then ask in plain language: *"put on YouTube on the TV"*, *"pause whatever is
playing"*, *"what's on the living-room screen?"*. The skill tells Claude how to
use `adb-ai`, including checking its own work with `adb-ai state`.

Prefer tools over a shell? Use the MCP server instead - see the main README.
