# Create Desktop shortcuts for the desktop exe and the dev launcher.
# Run once after scripts/build_desktop.py.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath("Desktop")
$ws = New-Object -ComObject WScript.Shell

$exe = Join-Path $repo "dist\desktop\ashare-desktop\ashare-desktop.exe"
$ico = Join-Path $repo "packaging\ashare.ico"

$lnk = $ws.CreateShortcut((Join-Path $desktop "A股研究台.lnk"))
$lnk.TargetPath = $exe
$lnk.WorkingDirectory = Split-Path $exe
$lnk.IconLocation = "$ico,0"
$lnk.Description = "A股研究台 桌面版"
$lnk.Save()

$dev = $ws.CreateShortcut((Join-Path $desktop "A股研究台 (开发).lnk"))
$dev.TargetPath = "powershell.exe"
$dev.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $repo 'scripts\desktop-dev.ps1')`""
$dev.WorkingDirectory = $repo
$dev.IconLocation = "$ico,0"
$dev.Description = "A股研究台 (Edge app 窗口, 开发用)"
$dev.Save()

Write-Host "created:"
Get-ChildItem $desktop -Filter "A股研究台*.lnk" |
    ForEach-Object { "  $($_.FullName)" }
