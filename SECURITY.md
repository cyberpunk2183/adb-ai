# Security policy

## Reporting a vulnerability

Please report security problems privately, not as a public issue:

- GitHub → **Security** tab → *Report a vulnerability* (private advisory), or
- open an issue saying only *"security report, please provide a contact"* with
  no details.

Please include what you ran, what happened, and why it is a problem. A
proof-of-concept helps; a weaponised exploit is not needed and not wanted.

Expect a first reply within a week. This is a hobby project, not a vendor with
an on-call rota — if it is urgent for you, say so.

## What counts

In scope:

- command injection through device names, aliases, app names or text passed to
  the CLI or the MCP tools;
- the MCP server doing more than its tool definitions say — in particular
  anything that reaches a shell while `ADBAI_ALLOW_SHELL` is unset;
- the config file or screenshots being written somewhere unsafe, or leaking
  into logs;
- the installers running something other than what they print.

Out of scope, because they are properties of ADB itself, not of this project:

- **ADB over TCP is unauthenticated.** Once the owner has accepted the trust
  dialog, anyone who can reach port 5555 has full control. That is Android's
  design; this project documents it loudly in
  [DISCLAIMER.md](DISCLAIMER.md) rather than pretending to fix it.
- Anything that needs the attacker to already be on your local network *and*
  for you to have enabled debugging *and* accepted their computer on screen.
- `adb_shell` being dangerous when you deliberately enable it.

## Hardening checklist

- Keep debugging off when you are not using it.
- Never expose 5555 beyond your LAN; no port forwarding, no public Wi-Fi.
- Leave `ADBAI_ALLOW_SHELL` unset unless you have a specific reason.
- Prefer a separate network segment for devices you leave debuggable.
