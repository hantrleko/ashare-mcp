# Dev launcher: open an Edge --app window on the local web server.
# Starts `uv run python -m ashare_mcp.web` in a hidden window if 8600 is down.
# The server keeps running after the window closes (shared dev workflow);
# stop it with:  Stop-Process -Id (Get-Content $env:TEMP\ashare-web.pid)
param(
    [int]$Port = 8600,
    [string]$UserDataDir = ""
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$base = "http://127.0.0.1:$Port"

function Test-Health {
    try {
        $h = Invoke-RestMethod "$base/api/health" -TimeoutSec 2
        return $h.status -eq "ok"
    } catch { return $false }
}

if (-not (Test-Health)) {
    Write-Host "starting web server on $Port ..."
    $p = Start-Process -FilePath "uv" `
        -ArgumentList "run", "python", "-m", "ashare_mcp.web" `
        -WorkingDirectory $repo -WindowStyle Hidden -PassThru
    $p.Id | Set-Content "$env:TEMP\ashare-web.pid"
    $deadline = (Get-Date).AddSeconds(90)
    while (-not (Test-Health)) {
        if ((Get-Date) -gt $deadline) { throw "server did not come up within 90s" }
        Start-Sleep -Milliseconds 500
    }
}

# msedge from App Paths registry, fallback to default install path
$edge = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe" -ErrorAction SilentlyContinue).'(default)'
if (-not $edge) { $edge = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe" }
if (-not (Test-Path $edge)) { $edge = "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe" }
if (-not (Test-Path $edge)) { throw "msedge not found" }

$edgeArgs = @("--app=$base", "--window-size=1440,900")
if ($UserDataDir) { $edgeArgs += "--user-data-dir=$UserDataDir" }
$ep = Start-Process -FilePath $edge -ArgumentList $edgeArgs -PassThru
Write-Host "edge --app opened (pid $($ep.Id))"
