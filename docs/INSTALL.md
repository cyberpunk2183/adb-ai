# Installing adb-ai

Two things have to be in place: **the `adb` binary** (not a Python package) and
**adb-ai itself**. Then you enable debugging on the device you want to control.

- [1. Install adb](#1-install-adb)
- [2. Install adb-ai](#2-install-adb-ai)
- [3. Enable debugging on the device](#3-enable-debugging-on-the-device)
- [4. First connection](#4-first-connection)

---

## 1. Install adb

`requirements.txt` is empty of Python packages on purpose — everything in
adb-ai is standard library. But `adb` comes from Android platform-tools and has
to be installed by your system's package manager.

### Windows

```powershell
winget install Google.PlatformTools
```

No winget? Download the [SDK Platform Tools zip][ptools], extract it to
`C:\platform-tools`, then add that folder to your PATH:
*Start → "environment variables" → Environment Variables → Path → New →*
`C:\platform-tools`. Close and reopen the terminal afterwards.

### macOS

```bash
brew install android-platform-tools
```

### Linux

```bash
sudo apt install adb          # Debian, Ubuntu, Mint, Raspberry Pi OS
sudo dnf install android-tools # Fedora
sudo pacman -S android-tools   # Arch, Manjaro
```

### Android (Termux)

```bash
pkg install android-tools python
```

Yes — this runs on a phone, controlling another device over Wi-Fi.

### Check it

```bash
adb version
```

You should see `Android Debug Bridge version 1.0.41` or similar. If the binary
lives somewhere unusual, point adb-ai at it instead of fighting your PATH:

```bash
export ADBAI_ADB=/opt/platform-tools/adb     # macOS, Linux, Termux
setx ADBAI_ADB "C:\platform-tools\adb.exe"   # Windows
```

### Optional: scrcpy

Only `adb-ai mirror` and `adb-ai record` use it — watching the device's screen
live in a window. Skip it if you do not want that; nothing else depends on it.

| System | Command |
|---|---|
| Windows | `winget install Genymobile.scrcpy` (or `scoop install scrcpy`) |
| macOS | `brew install scrcpy` |
| Debian/Ubuntu | `sudo apt install scrcpy` |
| Fedora | `sudo dnf install scrcpy` |
| Arch | `sudo pacman -S scrcpy` |
| Termux | **not supported** |

**scrcpy does not work from Termux.** It is not in the default repo, and the
x11-repo plus Termux:X11 route does not get it running either. adb-ai says so
rather than letting scrcpy fail with an SDL error, and nothing else is
affected: use `adb-ai shot` to see a screen from a phone, and run adb-ai from a
desktop on the same network when you want to mirror.

A mirror also needs a desktop session — over SSH there is no window to open,
though `adb-ai record` still works. As with adb, `ADBAI_SCRCPY` points at the
binary if it lives somewhere unusual.

### Optional: ffmpeg

Worth having if you use adb-ai through an agent. A screenshot of a 4K screen
with artwork on it is several megabytes of PNG, and all of it has to reach the
model before it can answer; with ffmpeg installed, adb-ai scales the big ones
down first. Small screenshots — a settings page, a TV's home row — are left
alone, because PNG already makes those tiny.

| System | Command |
|---|---|
| Windows | `winget install Gyan.FFmpeg` |
| macOS | `brew install ffmpeg` |
| Debian/Ubuntu | `sudo apt install ffmpeg` |
| Fedora | `sudo dnf install ffmpeg` |
| Arch | `sudo pacman -S ffmpeg` |
| Termux | `pkg install ffmpeg` |

This one does work on Termux. `ADBAI_FFMPEG` points at the binary if it is
somewhere unusual, and `ADBAI_SHOT_MAX` sets the default size (`0` turns the
scaling off).

---

## 2. Install adb-ai

### From a clone (recommended while it is young)

```bash
git clone https://github.com/cyberpunk2183/adb-ai
cd adb-ai
pip install -r requirements.txt   # confirms there is nothing to install
pip install .
```

On Windows use `py -m pip` instead of `pip` if `pip` is not found.

### With pipx (keeps it out of your system Python)

```bash
pipx install .
```

### Without installing at all

Any clone works as-is:

```bash
python -m adbai devices
```

Everywhere this documentation says `adb-ai ...`, `python -m adbai ...` does the
same thing.

### Check it

```bash
adb-ai --version
adb-ai keys        # should print the key names
```

If your shell says `adb-ai: command not found` after `pip install .`, the
scripts folder is not on your PATH. `python -m adbai` works regardless, or add
the folder `pip` warned you about.

---

## 3. Enable debugging on the device

This is the step everyone gets stuck on. Nothing connects until you do it.

### Android TV, TV box, Google TV, Fire TV

1. **Settings → Device Preferences → About**
2. Scroll to **Build** and click it **seven times**. A toast says *You are now a
   developer*.
3. Go back → **Developer options**
4. Turn on **Network debugging** (on some devices: *ADB debugging*, *USB
   debugging*, or both — turn on what you see).

Manufacturers move this around. On Philips, Sony and TCL it is usually under
*Device Preferences*; on Xiaomi/Mi Box, under *About → Build*; on Fire TV,
*Settings → My Fire TV → Developer options → ADB debugging*.

### Phone or tablet

1. **Settings → About phone** → tap **Build number** seven times
2. **Settings → System → Developer options**
3. Turn on **Wireless debugging**

Android 11 and newer need a one-time pairing. Two ways through it.

**By camera, which is the easy one:**

```bash
adb-ai pair
```

It draws a QR code in the terminal. On the phone, *Wireless debugging → Pair
device with QR code*, point the camera at the screen, and that is the whole
procedure — the phone pairs and ADB-AI connects to it. Nothing is typed, which
also means the random port cannot be copied wrong.

If the code comes out unreadable, two knobs: `--blocks` draws it twice as big
for terminals whose font mangles the half-block character, and `--png code.png`
writes it to an image file to open in a viewer.

**By typed code**, when the camera is not an option — the device showing the
code is the device the terminal is on, or the network blocks the discovery:

```bash
adb-ai pair 192.168.0.50:37123 418926   # the port INSIDE the pairing dialog
adb-ai connect 192.168.0.50:42701       # the port on the main screen
```

> **The pairing code flow needs an adb built with mDNS support.** Check yours:
>
> ```console
> $ adb mdns check
> mdns daemon version [10102001]      # good
> adb: mdns is not supported by this version of adb.   # pairing will fail
> ```
>
> Google's official platform-tools have it. Some distribution builds do not —
> **Termux's `android-tools` is one of them**, so pairing from Termux fails with
> `protocol fault (couldn't read status message)` no matter how fresh the code
> is. ADB-AI does its own mDNS discovery, so it can still *find* the device on
> such a build, but the pairing handshake itself belongs to adb and fails
> there. (On Termux the QR is a dead end for a second reason anyway: a phone's
> camera cannot read a code drawn on that same phone's screen.) Workaround:
> pair and enable TCP from a machine whose adb does support it, once, over USB:
>
> ```bash
> adb tcpip 5555          # on the computer, with the phone plugged in
> ```
>
> After that the phone listens on the classic port 5555, which needs no
> pairing, and Termux (or anything else) can `adb-ai connect <ip>` normally
> until the phone reboots. TVs and TV boxes are unaffected — they use 5555
> already.

### Already have a USB cable?

Easier, and it works on every version:

```bash
adb devices        # accept the dialog on the device
adb tcpip 5555     # switch it to network mode
```

Unplug, then `adb-ai scan`.

---

## 4. First connection

```bash
adb-ai scan
```

```
192.168.0.42:5555
```

```bash
adb-ai connect 192.168.0.42 --alias tv
```

**Watch the device's screen now.** The first time a computer connects, Android
shows *Allow USB debugging?* with a fingerprint. Tick **Always allow from this
computer** and accept. Nothing works until you do — and the dialog times out, so
if you missed it, just run `connect` again.

```bash
adb-ai devices
```

```
192.168.0.42:5555  [device]  Living Room TV  (default, tv)
```

That's it. Carry on with the [tutorial](TUTORIAL.md).

Nothing found? See [troubleshooting](TROUBLESHOOTING.md).

[ptools]: https://developer.android.com/tools/releases/platform-tools
