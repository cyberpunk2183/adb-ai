# What you can actually do with it

Everything below is a real command. Where a feature depends on the device,
it says so — a TV is not a phone, and both lie about some things.

> Notes marked **TV** come from running these against a 2020-era Android TV set
> over Wi-Fi; phones behave differently where said.

- [Watch something](#watch-something)
- [Volume and sound](#volume-and-sound)
- [Power and screen](#power-and-screen)
- [Navigate like a remote](#navigate-like-a-remote)
- [Alarms and timers](#alarms-and-timers)
- [Screenshots](#screenshots)
- [Knowing what is happening](#knowing-what-is-happening)
- [Several devices at once](#several-devices-at-once)
- [Things that will not work](#things-that-will-not-work)

---

## Watch something

```bash
adb-ai open youtube                  # by alias
adb-ai open com.netflix.ninja        # by package
adb-ai open youcine                  # by fragment of the package name
adb-ai apps                          # what is installed here
adb-ai close netflix                 # force-stop
```

Search without touching the on-screen keyboard — this is the single biggest
time-saver:

```bash
adb-ai youtube "lofi hip hop radio"
```

Deep links work for anything that registers one:

```bash
adb-ai url "https://www.netflix.com/title/80100172"
adb-ai url "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M" --app com.spotify.tv.android
adb-ai url "https://www.primevideo.com/detail/0M1PFJ..."
```

Then press play, because launching an app does not start playback:

```bash
adb-ai key ok          # most TV apps resume on OK
adb-ai key play
adb-ai state           # playback: playing  <- the proof
```

## Volume and sound

```bash
adb-ai volume up -n 5
adb-ai volume down -n 3
adb-ai volume mute          # toggles
adb-ai volume set 12        # exact level on the media stream
```

**TV:** `up`/`down`/`mute` are key presses and always work. `set` uses the media
session and is ignored by some TV firmwares — check with `adb-ai state` or your
ears. On phones it is reliable.

## Power and screen

```bash
adb-ai off      # screen to sleep - the safe "turn it off"
adb-ai on       # wake
adb-ai key power
```

`off` sends `KEYCODE_SLEEP`, which is idempotent: running it twice leaves the
device asleep. `KEYCODE_POWER` toggles, so it can wake a device you meant to
turn off — prefer `off`/`on` in scripts.

**TV:** many sets drop off the network in standby, so after `off` the next
command may need a `scan` and `connect`. That is the TV, not the tool.

## Navigate like a remote

```bash
adb-ai key home
adb-ai key back
adb-ai key down down ok      # a sequence, left to right
adb-ai key right -n 4        # repeat
adb-ai keys                  # all ~50 names
```

Names: `home` `back` `ok` `up` `down` `left` `right` `menu` `search` `apps`
`settings` `play` `pause` `playpause` `stop` `next` `prev` `forward` `rewind`
`captions` `volup` `voldown` `mute` `power` `sleep` `wake` `tv` `input`
`channelup` `channeldown` `guide` `info` `red` `green` `yellow` `blue`, digits
`0`–`9`, plus any raw `KEYCODE_*`.

Typing into a focused field:

```bash
adb-ai text "my login@example.com"
```

## Alarms and timers

```bash
adb-ai alarm 7:30 --label "Work"
adb-ai alarm 6:45 --days mon,tue,wed,thu,fri --label "Gym"
adb-ai timer 10m --label "Pizza"
adb-ai timer 1h30m
adb-ai alarms                 # open the clock app's list
```

**Phones and tablets only.** Android TV ships a stub that accepts the alarm
intent and silently throws it away, so "it worked" would be a lie — ADB-AI
checks for a real clock app first and refuses with an explanation instead:

```console
$ adb-ai alarm 7:30
adb-ai: this device has no clock app that can hold an alarm - Android TV
accepts the request and silently drops it. Alarms and timers work on phones
and tablets.
```

By default the alarm is created silently (`SKIP_UI`). Pass `--confirm` to open
the clock app and let a human confirm it instead.

> **Pointing this at a phone is a bigger decision than pointing it at a TV.**
> Alarms live on phones, and ADB access to a phone is the same reach you have
> when it is unlocked in your hand: opening your bank or your messages, typing
> into them, and screenshotting whatever is on screen — including one-time
> codes. Read **[Phones are not TVs](../DISCLAIMER.md#phones-are-not-tvs)**
> before you enable debugging on your daily driver. A spare phone or an old
> tablet is a much better place to experiment.

## Screenshots

```bash
adb-ai shot                      # saves screen.png
adb-ai shot living-room.png
adb-ai shot - > /tmp/now.png     # straight to stdout
```

Two things ADB-AI handles for you:

- Some firmwares print driver noise before the PNG. Saved naively, the file is
  corrupt. ADB-AI always cuts to the PNG header. **TV:** this is exactly what
  that Philips does.
- Old devices without `exec-out` fall back to `shell`, with the CRLF mangling
  undone.

**Protected content comes back empty.** Live TV inputs, Netflix playback and
anything else under HDCP/DRM return zero bytes — that is Android refusing, not
a bug here:

```console
$ adb-ai shot            # while on the live TV input
adb-ai: no PNG in screencap output: empty response
```

Go to the launcher (`adb-ai key home`) and the screenshot works again.

## Knowing what is happening

```bash
adb-ai state
adb-ai state --json
adb-ai devices
adb-ai doctor
```

```console
$ adb-ai state
device:     192.168.0.42:5555
foreground: com.google.android.tvlauncher/com.google.android.tvlauncher.MainActivity
screen:     Awake
playback:   no media session
```

- `foreground` — which app and activity has focus. `unknown (transition?)` for a
  second after switching apps; ask again.
- `screen` — `Awake`, `Asleep`, `Dozing`.
- `playback` — from the active media session. `playing`, `paused`, `buffering`,
  or `no media session`. **An app being open is not playback.**

## Several devices at once

```bash
adb-ai alias tv 192.168.0.42
adb-ai alias quarto 192.168.0.60
adb-ai alias                       # list them

adb-ai -d quarto key pause
adb-ai -d tv open youtube
adb-ai use tv                      # change the default
```

Good night, everything:

```bash
for device in tv quarto cozinha; do adb-ai -d "$device" off; done
```

## Things that will not work

Worth knowing before you file a bug:

- **Setting an alarm on a TV** — no clock app. See above.
- **Screenshots of protected video** — HDCP/DRM returns empty. Expected.
- **Controlling a device that is off**, or asleep in a way that drops Wi-Fi.
  Most TVs do exactly that; wake it with its real remote once.
- **Anything needing root** — this uses the ordinary shell user.
- **Pairing an Android 11+ phone from an adb without mDNS** (Termux's build, for
  one). Not a limitation of ADB-AI; see
  [troubleshooting](TROUBLESHOOTING.md#adb-pair-fails-with-protocol-fault-couldnt-read-status-message).
- **Streaming the screen.** Use [scrcpy](https://github.com/Genymobile/scrcpy)
  for mirroring; come back here for automation.
- **Changing system settings broadly.** Deliberately out of scope: this is a
  remote control, not a device management suite.
- **Bypassing a licence, a paywall or someone's account.** Not supported, not
  wanted — see [DISCLAIMER.md](../DISCLAIMER.md).
