# Inicia o English Builder localmente: http://localhost:8000
# Uso: clique com o botão direito > "Executar com o PowerShell", ou rode .\start.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Criando ambiente Python..."
    python -m venv (Join-Path $backend ".venv")
    & $python -m pip install -q -r (Join-Path $backend "requirements.txt")
}

if (-not (Test-Path (Join-Path $frontend "dist\index.html"))) {
    Write-Host "Gerando a interface (primeira execução)..."
    Push-Location $frontend
    npm install --no-audit --no-fund
    npm run build
    Pop-Location
}

Start-Process "http://localhost:8000"
& $python -m uvicorn app.main:app --app-dir $backend --host 127.0.0.1 --port 8000
