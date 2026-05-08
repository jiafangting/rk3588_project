$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$MsysBash = "E:\msys64\usr\bin\bash.exe"
$TmpDir = Join-Path $ProjectRoot ".tmp"

if (!(Test-Path $MsysBash)) {
    throw "MSYS2 bash not found: $MsysBash"
}

New-Item -ItemType Directory -Force -Path $TmpDir | Out-Null

& $MsysBash -lc "cd /e/rk3588_project/rk3588_main && TMPDIR=/e/rk3588_project/.tmp make clean && TMPDIR=/e/rk3588_project/.tmp make CC=gcc"

Write-Host ""
Write-Host "Build finished: E:\rk3588_project\rk3588_main\rk3588_main.exe"
