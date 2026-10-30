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

$dist = Join-Path $frontend "dist\index.html"
$stale = -not (Test-Path $dist)
if (-not $stale) {
    $built = (Get-Item $dist).LastWriteTime
    $stale = [bool](Get-ChildItem (Join-Path $frontend "src") -Recurse -File | Where-Object { $_.LastWriteTime -gt $built } | Select-Object -First 1)
}
if ($stale) {
    Write-Host "Gerando a interface..."
    Push-Location $frontend
    npm install --no-audit --no-fund
    npm run build
    Pop-Location
}

Start-Process "http://localhost:8000"
& $python -m uvicorn app.main:app --app-dir $backend --host 127.0.0.1 --port 8000
