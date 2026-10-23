---
name: adb-ai
description: Control Android devices in the user's home over ADB - a TV, a streaming box, a phone or a tablet. Use when the user asks to turn something on or off, open an app (Netflix, YouTube, Spotify...), play, pause, change the volume, navigate a menu, type into a field, see what is on the screen, or take a screenshot of a device. Also use when a device's IP has changed and needs to be found again.
---

# Controlling devices over ADB

`adb-ai` wraps `adb` with device discovery, friendly key names, app aliases and
state checks. Run it through your shell tool.

## First: make sure a device is there

```bash
adb-ai devices              # what is connected
adb-ai scan                 # find devices on the local network (DHCP moves them)
adb-ai connect 192.168.0.42 --alias tv    # connect and remember it as "tv"
```

Home networks hand out addresses by DHCP, so **an address that worked yesterday
often fails today**. If a command reports *no route to host* or *no device
connected*, run `adb-ai scan`, then `connect` the address it finds. Do not keep
retrying the old address.

`adb-ai` uses the default device when `-d` is omitted. With several devices
connected, pass `-d tv` (an alias) or the serial.

## Driving a device

```bash
adb-ai key home                 # one key
adb-ai key down down ok         # a sequence, in order
adb-ai key volup -n 5           # repeat a key
adb-ai keys                     # every key name available

adb-ai open netflix             # alias, package name, or a fragment of one
adb-ai apps                     # what is actually installed
adb-ai close netflix

adb-ai youtube "lofi hip hop"   # search without fighting the on-screen keyboard
adb-ai url "https://example.com"
adb-ai text "hello there"       # type into the focused field

adb-ai volume up -n 3
adb-ai volume set 12
adb-ai off                      # screen to sleep
adb-ai on                       # wake
```

## Checking your work, instead of assuming

```bash
adb-ai state          # foreground app, screen state, playback state
adb-ai shot out.png   # screenshot (reads correctly even on devices that
                      # print driver noise before the PNG)
```

Prefer `adb-ai state` over a screenshot when a text answer is enough - it is
much faster and cheaper.

Two details worth knowing:

- Right after launching or switching an app, the foreground may read as
  `unknown (transition?)`. Wait a second and check again before concluding the
  action failed.
- An app being open does not mean something is playing. `playback: playing` is
  the proof that it is.

## Working with the user

- **Say what you are about to do before doing it.** These commands act on a
  physical device in someone's home: a TV can wake up at 3am and a `close`
  loses what was playing.
- **Ask before anything disruptive** when the user has not asked for it
  directly: force-stopping an app, putting a device to sleep, or changing the
  volume by a lot.
- **Never use `adb-ai shell` for something a normal command already does.** Raw
  shell is for things the CLI does not cover, and it is disabled by default on
  the MCP server for a reason.
- Respect what the device is for. Opening a streaming app is fine; working
  around a paywall, a licence check or someone's account is not.
