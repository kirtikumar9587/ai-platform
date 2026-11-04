# One-time setup (Windows PowerShell). Run from the project root:  .\setup.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "== Backend: creating venv and installing libraries ==" -ForegroundColor Cyan
Set-Location "$root\backend"
if (-not (Test-Path "venv")) { python -m venv venv }
& .\venv\Scripts\python.exe -m pip install --upgrade pip
& .\venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created backend\.env  -> open it and add your keys" -ForegroundColor Yellow }

Write-Host "== Frontend: installing npm packages ==" -ForegroundColor Cyan
Set-Location "$root\frontend"
npm install
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }

Set-Location $root
Write-Host "`nSetup finished. Next: edit backend\.env, then run  .\run.ps1" -ForegroundColor Green
