# adb-ai installer for Windows (PowerShell 5+).
#
#   .\install.ps1            install what is missing, then adb-ai
#   .\install.ps1 -Check     only report what is missing, change nothing
#
# If Windows blocks the script, run PowerShell once with:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

param([switch]$Check)

function Say($m)  { Write-Host $m }
function Ok($m)   { Write-Host "[ok  ] $m"   -ForegroundColor Green }
function Warn($m) { Write-Host "[warn] $m"   -ForegroundColor Yellow }
function Bad($m)  { Write-Host "[FAIL] $m"   -ForegroundColor Red }

function Invoke-Step($command) {
    Say ""
    Say "    $command"
    Say ""
    if ($Check) { Warn "skipped (-Check). Run the command above yourself."; return $false }
    $reply = Read-Host "Run it now? [y/N]"
    if ($reply -match '^[yY]') { Invoke-Expression $command; return $true }
    Warn "skipped. Run the command above when you are ready."
    return $false
}

Say "adb-ai installer - Windows"
Say ""

# --- Python ------------------------------------------------------------------
$py = $null
foreach ($candidate in @("py -3", "python", "python3")) {
    $exe, $flag = $candidate.Split(" ", 2)
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        $version = & $exe $flag -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and [version]$version -ge [version]"3.9") { $py = $candidate; break }
    }
}

if ($py) {
    Ok "Python $version ($py)"
} else {
    Bad "Python 3.9+ not found"
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Invoke-Step "winget install -e --id Python.Python.3.12" | Out-Null
    } else {
        Say "Install Python from https://www.python.org/downloads/ and tick"
        Say "'Add python.exe to PATH' during setup, then run this again."
    }
    if (Get-Command python -ErrorAction SilentlyContinue) { $py = "python" }
    if (-not $py) { Bad "still no Python - stopping here."; exit 1 }
}

# --- adb ---------------------------------------------------------------------
if (Get-Command adb -ErrorAction SilentlyContinue) {
    Ok ((adb version | Select-Object -First 1))
} else {
    Bad "adb not found - this is the one real requirement"
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Invoke-Step "winget install -e --id Google.PlatformTools" | Out-Null
        Warn "If 'adb' is still not recognised, close and reopen PowerShell."
    } else {
        Say "Download https://developer.android.com/tools/releases/platform-tools,"
        Say "extract it to C:\platform-tools and add that folder to your PATH."
    }
}

# --- scrcpy (optional: only 'adb-ai mirror' and 'adb-ai record') -------------
if (Get-Command scrcpy -ErrorAction SilentlyContinue) {
    Ok ((scrcpy --version 2>&1 | Select-Object -First 1))
} else {
    Warn "scrcpy not found - optional, only 'adb-ai mirror' and 'adb-ai record' use it."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Invoke-Step "winget install -e --id Genymobile.scrcpy" | Out-Null
    } else {
        Say "Get it from https://github.com/Genymobile/scrcpy/releases if you"
        Say "want to watch the device's screen in a window."
    }
}

# --- adb-ai ------------------------------------------------------------------
if ($Check) { Say ""; Say "-Check: nothing was installed."; exit 0 }

Say ""
Say "Installing adb-ai..."
$exe, $flag = $py.Split(" ", 2)
& $exe $flag -m pip install --user .
if ($LASTEXITCODE -eq 0) { Ok "installed" } else { Warn "pip install failed - you can still run it from this folder with: $py -m adbai" }

Say ""
& $exe $flag -m adbai doctor
