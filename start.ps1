$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force -Path "data/telemetry-inbox", "data/telemetry-archive" | Out-Null
if (-not (Test-Path ".venv")) { py -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port $(if ($env:BURN_LEDGER_PORT) {$env:BURN_LEDGER_PORT} else {"8795"})
