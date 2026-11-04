# Starts backend (http://localhost:8000) and frontend (http://localhost:5173)
$root = $PSScriptRoot
$venvPy = if (Test-Path "$root\backend\venv\Scripts\python.exe") { "$root\backend\venv\Scripts\python.exe" } elseif (Test-Path "D:\Desktop\ai_project\venv\Scripts\python.exe") { "D:\Desktop\ai_project\venv\Scripts\python.exe" } else { "python" }
$npmCmd = if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { "npm.cmd" } elseif (Test-Path "C:\Program Files\nodejs\npm.cmd") { "C:\Program Files\nodejs\npm.cmd" } else { "npm" }

Write-Host "Starting Enterprise Intelligence Platform..." -ForegroundColor Cyan
Write-Host "Python : $venvPy" -ForegroundColor Gray
Write-Host "NPM    : $npmCmd" -ForegroundColor Gray

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; & '$venvPy' -m uvicorn app.main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; & '$npmCmd' run dev"

Write-Host "`nBackend API Docs : http://localhost:8000/docs" -ForegroundColor Green
Write-Host "Frontend UI      : http://localhost:5173" -ForegroundColor Green
