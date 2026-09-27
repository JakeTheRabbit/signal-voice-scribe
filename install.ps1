<#
.SYNOPSIS
    Install (or update) Signal Scribe for the current Windows user. No admin rights needed.

.DESCRIPTION
    Sets up everything inside this folder: Python and its packages (via uv), Java,
    signal-cli, the Whisper speech model and the desktop app. Run it again at any
    time to update or repair; your settings, Signal link and history are kept.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Gpu no -NoAutostart
#>
[CmdletBinding()]
param(
    # No desktop app: run the engine in the background at login instead.
    [switch]$Headless,
    # NVIDIA GPU acceleration: auto (if an NVIDIA driver is present), yes or no.
    [ValidateSet('auto', 'yes', 'no')][string]$Gpu = 'auto',
    # Whisper model to download now (auto picks one for your hardware), or none.
    [string]$Model = 'auto',
    # download (default), build (from source, needs Rust + pnpm), skip, or a path to a local build.
    [string]$Desktop = 'download',
    [switch]$NoAutostart,
    [switch]$NoShortcuts,
    [switch]$NoDesktopIcon,
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Root = $PSScriptRoot
$Runtime = Join-Path $Root 'runtime'
$UvVersion = '0.12.19'
$UvHashes = @{
    'x86_64'  = '6dbb02d79e419522f1c500f0adb1cddcff0cda7d59b0d66ea7f5e3b4a1b2f5f0'
    'aarch64' = '115b54cb823bc48260670f5782001add6067ac8d98d18c8263a833704e287de9'
}

Write-Host "Signal Scribe installer"
if (-not (Test-Path -LiteralPath (Join-Path $Root 'pyproject.toml'))) {
    throw "Run install.ps1 from the Signal Scribe folder (the one containing pyproject.toml)."
}
if ($Root.Contains("'") -or $Root.Contains('"')) {
    throw "Move Signal Scribe to a folder whose path has no quote characters, then run this again."
}

# Files are locked while Signal Scribe runs, so stop this install's own processes first.
$prefix = $Root.TrimEnd('\') + '\'
$running = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
})
if ($running.Count -gt 0) {
    Write-Host "Stopping the running copy of Signal Scribe..."
    $running | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

# 1. uv: a single-file Python installer and package manager (https://docs.astral.sh/uv/).
$uv = $null
$existing = Get-Command uv -ErrorAction SilentlyContinue
if ($existing) { $uv = $existing.Source }
if (-not $uv) {
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'aarch64' } else { 'x86_64' }
    $uvDir = Join-Path $Runtime 'uv'
    $uv = Join-Path $uvDir 'uv.exe'
    if (-not (Test-Path -LiteralPath $uv)) {
        Write-Host "Downloading uv $UvVersion..."
        New-Item -ItemType Directory -Force -Path $uvDir | Out-Null
        $zip = Join-Path $uvDir 'uv.zip'
        $url = "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-$arch-pc-windows-msvc.zip"
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne $UvHashes[$arch]) {
            Remove-Item -LiteralPath $zip -Force
            throw "The uv download failed its checksum and was deleted. Try again."
        }
        Expand-Archive -LiteralPath $zip -DestinationPath $uvDir -Force
        Remove-Item -LiteralPath $zip -Force
    }
}

# 2. Python 3.12 and packages, kept inside this folder.
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Runtime 'python'
$env:UV_PYTHON_PREFERENCE = 'only-managed'
$env:UV_PROJECT_ENVIRONMENT = Join-Path $Root '.venv'
$useGpu = ($Gpu -eq 'yes') -or ($Gpu -eq 'auto' -and $null -ne (Get-Command nvidia-smi -ErrorAction SilentlyContinue))
$syncArgs = @('sync', '--frozen', '--no-dev', '--python', '3.12', '--directory', $Root)
if ($useGpu) {
    Write-Host "NVIDIA GPU found: including GPU acceleration (about 1 GB extra)."
    $syncArgs += @('--extra', 'cuda')
}
Write-Host "Installing Python and packages..."
& $uv @syncArgs
if ($LASTEXITCODE -ne 0) { throw "Installing Python packages failed (uv exit code $LASTEXITCODE)." }

# 3. Everything else is shared with macOS and Linux.
$python = Join-Path $Root '.venv\Scripts\python.exe'
$installerArgs = @('-m', 'scribe.installer', '--model', $Model, '--desktop', $Desktop)
if ($Headless) { $installerArgs += '--headless' }
if ($NoAutostart) { $installerArgs += '--no-autostart' }
if ($NoShortcuts) { $installerArgs += '--no-shortcuts' }
if ($NoDesktopIcon) { $installerArgs += '--no-desktop-icon' }
if ($NoLaunch) { $installerArgs += '--no-launch' }
Push-Location $Root
try {
    & $python @installerArgs
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code
