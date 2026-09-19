# bid-pricing one-click launcher (Windows PowerShell 5.1+)
# Starts backend 8000 + frontend 8080; auto-installs deps on first run. Press Ctrl+C to stop.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "==> bid-pricing start" -ForegroundColor Cyan

# --- locate Python (prefer current env, then python/python3) ---
$Py = "python"
if (Get-Command $Py -ErrorAction SilentlyContinue) { } else { $Py = "py" }
if (-not (Get-Command $Py -ErrorAction SilentlyContinue)) {
  Write-Host "[ERR] python not found. Install Python 3.10+ and add to PATH." -ForegroundColor Red
  exit 1
}
Write-Host ("    Python: " + (& $Py --version)) -ForegroundColor DarkGray

# --- node (used for Excel export; warn but continue if missing) ---
$HasNode = [bool](Get-Command node -ErrorAction SilentlyContinue)
if ($HasNode) { Write-Host ("    Node:   " + (& node --version)) -ForegroundColor DarkGray }
else { Write-Host "[WARN] node not found. Excel export will fail (JSON result still downloadable)." -ForegroundColor Yellow }

# --- dependency check / install ---
function Ensure-Req($file) {
  Write-Host "==> check deps: $file"
  try { & $Py -c "import fastapi, uvicorn" 2>$null; $Present = ($LASTEXITCODE -eq 0) }
  catch { $Present = $false }
  if (-not $Present) { Write-Host "==> installing web deps (first run)..."; & $Py -m pip install -r $file }
}
Ensure-Req (Join-Path $Root "requirements-web.txt")

# --- output dir (logs) ---
New-Item -ItemType Directory -Force -Path (Join-Path $Root "outputs\logs") | Out-Null

# --- start backend 8000 ---
$env:PYTHONPATH = "src"
Write-Host "==> backend http://localhost:8000  ..."
$backend = Start-Process -FilePath $Py -ArgumentList @("-m", "uvicorn", "api.app:app", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $Root -PassThru -NoNewWindow

# --- start frontend 8080 (static server only) ---
Write-Host "==> frontend http://localhost:8080  ..."
$frontend = Start-Process -FilePath $Py -ArgumentList @("-m", "http.server", "8080", "--directory", "frontend") -WorkingDirectory $Root -PassThru -NoNewWindow

Write-Host ""
Write-Host "  frontend: http://localhost:8080" -ForegroundColor Green
Write-Host "  backend:  http://localhost:8000/api/health" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop both services ..." -ForegroundColor DarkGray

try { Wait-Process -Id $backend.Id -Id $frontend.Id -ErrorAction SilentlyContinue | Out-Null }
finally { Write-Host "==> stopping services"; Stop-Process -Id $backend.Id,$frontend.Id -ErrorAction SilentlyContinue }