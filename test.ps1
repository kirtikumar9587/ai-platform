# Runs backend tests (offline, no API keys needed)
$root = $PSScriptRoot
$venvPy = if (Test-Path "$root\backend\venv\Scripts\python.exe") { "$root\backend\venv\Scripts\python.exe" } elseif (Test-Path "D:\Desktop\ai_project\venv\Scripts\python.exe") { "D:\Desktop\ai_project\venv\Scripts\python.exe" } else { "python" }

Set-Location "$root\backend"
& $venvPy -m pytest -v
