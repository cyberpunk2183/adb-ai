# Legal notice and responsible use

**Short version:** ADB-AI is a remote control for Android devices **you own or
are authorised to administer**. It is provided as-is, with no warranty. What you
do with it is your responsibility, not the authors'.

## What this project is for

Letting people automate their own devices — a TV, a streaming box, a phone, a
tablet — from their own terminal or their own AI agent. Opening an app, pressing
play, checking what is on screen, setting an alarm. The everyday things a remote
control does, scriptable and available to an agent.

## What it is built on

ADB-AI does nothing that `adb` itself cannot do. It is a convenience layer over
Android's official debugging bridge, which:

- **requires the device owner to deliberately enable debugging**, in a menu that
  is hidden behind tapping *Build number* seven times;
- **requires accepting a trust dialog on the device's own screen**, physically,
  the first time a computer connects;
- **works on the local network**, not across the internet.

In other words, a device you do not control is not reachable with this tool
unless someone with physical access to it chose to open it up.

## Use it only where you have authority

Use ADB-AI on devices that are yours, or that you have been clearly authorised
to administer. Do not use it on someone else's device, on devices on a network
you do not have permission to probe, or to watch, record or control a person
without their knowledge and consent.

Depending on where you live, doing any of that may be a crime — unauthorised
access to computer systems, interception, or stalking/harassment offences.
Some of it is a crime even when the device belongs to you, if another person is
using it and does not know.

## Dual use, stated plainly

Any tool that controls devices over a network can be misused. The parts of this
project that could be misused are the parts that make it work at all:

- **`scan`** sweeps the local subnet for an open ADB port. On your own network
  that is how you find your TV after DHCP moved it. On a network that is not
  yours, scanning may itself be unlawful.
- **remote control of many devices** is just this tool in a loop. Built for a
  household; the same mechanism would serve a botnet herder with a list of
  already-compromised devices.

The authors do not endorse, support or accept responsibility for that use.
This project will not accept contributions whose purpose is covert control,
evading device owners' awareness, mass exploitation, or hiding the tool's
presence from the person in front of the screen.

## Security of your own setup

ADB over TCP has **no authentication** after you accept the trust dialog.
Anyone who can reach port 5555 on that device can control it as completely as
this tool can. So:

- **Never port-forward 5555 to the internet**, and never put a device with
  debugging enabled on a public or untrusted network.
- Keep it on a network you control; a guest or IoT VLAN is better still.
- **Turn network debugging off when you are done** experimenting.
- Treat an agent's access accordingly. `adb_shell` is disabled by default in
  the MCP server for this reason — it is arbitrary command execution on a
  device in your home.

If you find a security problem in this project, see [SECURITY.md](SECURITY.md).

## No warranty

ADB-AI is released under the [MIT Licence](LICENSE), which says this in legal
terms and is worth repeating in plain ones:

> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

The authors and contributors are not liable for anything that happens as a
result of using it: a device left in a strange state, a setting changed, an
alarm that did not go off, data lost, or any consequence of someone using it
where they had no right to. You run it; you own the outcome.

Not affiliated with, endorsed by, or connected to Google LLC or the Android
Open Source Project. "Android" and "Android TV" are trademarks of Google LLC.
App names are trademarks of their respective owners and appear here only to
identify which app a command would open.
