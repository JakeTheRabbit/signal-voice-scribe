<#
.SYNOPSIS
    Remove Signal Scribe's start-at-login entry, shortcuts and desktop app.

.DESCRIPTION
    Your Signal link, settings and history are kept unless you pass -Purge.
    Also remove "Signal Scribe" from your phone: Signal > Settings > Linked devices.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
    powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -Purge
#>
[CmdletBinding()]
param([switch]$Purge, [switch]$Yes)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

# Stop this install's own processes (the app, the engine and signal-cli).
$prefix = $Root.TrimEnd('\') + '\'
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

$python = Join-Path $Root '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $python) {
    $uninstallArgs = @('-m', 'scribe.installer.uninstall')
    if ($Purge) { $uninstallArgs += '--purge' }
    if ($Yes) { $uninstallArgs += '--yes' }
    Push-Location $Root
    try { & $python @uninstallArgs } finally { Pop-Location }
    exit $LASTEXITCODE
}

# The Python environment is gone: remove what we can directly.
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'SignalScribe' -ErrorAction SilentlyContinue
foreach ($folder in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
    Remove-Item -LiteralPath (Join-Path $folder 'Signal Scribe.lnk') -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath (Join-Path $env:APPDATA 'signal-scribe\root.txt') -ErrorAction SilentlyContinue
Write-Host "Start at login and shortcuts removed. Delete this folder to remove everything else."
