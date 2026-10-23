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

## Phones are not TVs

Setting an alarm or a timer means pointing this at a phone — and a phone is a
different proposition from a TV. Be deliberate about it.

**What ADB access to a phone actually gives an agent.** Not "alarm
permissions": the same reach you have when the device is unlocked in your hand.

- **Open any app** — your bank, your email, your messages — and navigate it
  with key presses, exactly as a person would.
- **Type anything** into whatever has focus: send a message, fill a form,
  confirm a payment, accept a dialog.
- **Take screenshots at any moment.** That includes your inbox, a chat, a
  banking balance, a notification shade — and **the one-time codes that arrive
  by SMS or an authenticator**. Screenshots are the quiet one: a code on screen
  plus the ability to type it is an account takeover in two steps.
- **Read what the system will tell the shell user** — installed apps, running
  activities, the files on shared storage (your photos, your downloads).
- **Run arbitrary commands**, if you turned on `ADBAI_ALLOW_SHELL`. Don't,
  unless you mean it.

**Where it goes.** A screenshot handed to an agent leaves your device: it is
sent to whatever model provider that agent uses and may be retained under their
terms. Treat "take a screenshot of my phone" as publishing that screen to a
third party, and take it on a screen you are willing to publish.

**The device does not have to be awake or watched.** The agent acts whether or
not you are looking at it, and ADB does not log to your face — there is no
notification saying something just opened your messages.

### If you do it anyway

- **Use a spare device** for anything experimental: an old phone, a tablet, a
  test profile. A TV or a dedicated box is a much safer target than your daily
  driver.
- **Turn wireless debugging off when you are done.** On most phones it already
  resets at reboot; that is a feature, not an inconvenience.
- **Revoke trust afterwards:** Developer options → *Revoke USB debugging
  authorisations*. It costs you one pairing next time.
- **Leave `ADBAI_ALLOW_SHELL` unset.** The ordinary tools cover alarms, apps,
  keys and volume without a shell.
- **Keep the phone locked when idle.** Most of the reach above needs an
  unlocked screen.
- **Say what is off limits** in your agent's instructions — and remember that
  an instruction is a request, not an enforcement mechanism. The permission
  boundary is what debugging is enabled on, not what you asked the agent to
  avoid.
- **Sign out of what matters**, or use a profile without your banking and
  messaging apps, if the device will stay debuggable.

Alarms and timers are the harmless end of this. They are documented here
because they are the reason people point this at a phone in the first place.

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
