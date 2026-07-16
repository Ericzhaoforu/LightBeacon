$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python environment not found. Follow docs/DEVELOPMENT.md first."
}
Set-Location $root
& $python -m lightbeacon.cli host

