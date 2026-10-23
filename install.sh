#!/usr/bin/env bash
# adb-ai installer for Linux, macOS, Termux and WSL.
#
#   ./install.sh            install what is missing, then adb-ai
#   ./install.sh --check    only report what is missing, change nothing
#
# Nothing is installed with sudo without asking you first.
set -u

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

say()  { printf '%s\n' "$*"; }
ok()   { printf '[ok  ] %s\n' "$*"; }
warn() { printf '[warn] %s\n' "$*"; }
bad()  { printf '[FAIL] %s\n' "$*"; }

ask() {  # ask "command to run"  -> runs it after a y/n, unless --check
    say ""
    say "    $1"
    say ""
    if [ "$CHECK_ONLY" = "1" ]; then
        warn "skipped (--check). Run the command above yourself."
        return 1
    fi
    printf "Run it now? [y/N] "
    read -r reply </dev/tty || return 1
    case "$reply" in
        [yY]*) eval "$1" ;;
        *) warn "skipped. Run the command above when you are ready."; return 1 ;;
    esac
}

# --- which system is this? ---------------------------------------------------
if [ -n "${TERMUX_VERSION:-}" ] || command -v pkg >/dev/null 2>&1 && [ -d /data/data/com.termux ]; then
    SYSTEM=termux
elif [ "$(uname -s)" = "Darwin" ]; then
    SYSTEM=macos
else
    SYSTEM=linux
fi
say "adb-ai installer - detected: $SYSTEM"
say ""

# --- Python ------------------------------------------------------------------
PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
            PY="$candidate"
            break
        fi
    fi
done

if [ -n "$PY" ]; then
    ok "Python $("$PY" -c 'import platform; print(platform.python_version())') ($PY)"
else
    bad "Python 3.9+ not found"
    case "$SYSTEM" in
        termux) ask "pkg install -y python" ;;
        macos)  ask "brew install python" ;;
        linux)
            if   command -v apt    >/dev/null 2>&1; then ask "sudo apt install -y python3 python3-pip"
            elif command -v dnf    >/dev/null 2>&1; then ask "sudo dnf install -y python3 python3-pip"
            elif command -v pacman >/dev/null 2>&1; then ask "sudo pacman -S --noconfirm python python-pip"
            else say "Install Python 3.9+ with your package manager, then run this again."
            fi ;;
    esac
    command -v python3 >/dev/null 2>&1 && PY=python3
    [ -z "$PY" ] && { bad "still no Python - stopping here."; exit 1; }
fi

# --- adb ---------------------------------------------------------------------
if command -v adb >/dev/null 2>&1; then
    ok "$(adb version 2>/dev/null | head -1)"
else
    bad "adb not found - this is the one real requirement"
    case "$SYSTEM" in
        termux) ask "pkg install -y android-tools" ;;
        macos)  ask "brew install android-platform-tools" ;;
        linux)
            if   command -v apt    >/dev/null 2>&1; then ask "sudo apt install -y adb"
            elif command -v dnf    >/dev/null 2>&1; then ask "sudo dnf install -y android-tools"
            elif command -v pacman >/dev/null 2>&1; then ask "sudo pacman -S --noconfirm android-tools"
            else say "Install Android platform-tools, then run this again."
            fi ;;
    esac
    command -v adb >/dev/null 2>&1 || warn "adb still missing - adb-ai will not be able to do anything yet."
fi

# --- adb-ai ------------------------------------------------------------------
if [ "$CHECK_ONLY" = "1" ]; then
    say ""
    say "--check: nothing was installed."
    exit 0
fi

say ""
say "Installing adb-ai..."
if "$PY" -m pip install --user . ; then
    ok "installed"
else
    warn "pip install failed - you can still use it from this folder with: $PY -m adbai"
fi

say ""
command -v adb-ai >/dev/null 2>&1 && adb-ai doctor || "$PY" -m adbai doctor
