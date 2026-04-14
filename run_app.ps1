$ErrorActionPreference = 'Stop'

$python = Join-Path $PSScriptRoot ".venv\\Scripts\\python.exe"
$requirements = Join-Path $PSScriptRoot "requirements.txt"
$app = Join-Path $PSScriptRoot "app.py"

if (-not (Test-Path -LiteralPath $python)) {
  throw "Virtual env not found at $python. Create it with: python -m venv .venv"
}

& $python -m pip install -r $requirements | Out-Host
& $python $app

