# bid-pricing one-click launcher (Windows PowerShell 5.1+)
# 启动后端 8000 + 前端 8080；首次运行在仓库 .venv 内建隔离环境并装依赖；Ctrl+C 停止全部。
#
# ⚠ 本文件必须保存为「UTF-8 with BOM」。
#   Windows PowerShell 5.1 对**无 BOM** 的 .ps1 按系统 ANSI（中文 Windows = GBK）解码。
#   本文件含中文，一旦丢失 BOM 会解码错乱、吃掉引号与括号，报一批离奇语法错误。
#   tests/test_run_script.py 会拦住这种回归。
#
# 设计要点（每条都对应一个真实踩过的坑，勿删）：
#   1) 解释器判定用「能力探测」而非存在性判据。Windows 在
#      %LOCALAPPDATA%\Microsoft\WindowsApps 放了 0 字节的 python.exe 应用执行别名占位符：
#      Test-Path / Get-Command 都会命中它，执行时只打印 “Python was not found ... Microsoft
#      Store” 并返回非 0。同名别名可能有多个候选，必须逐个探测、取第一个真正可用的。
#   2) 探测的能力必须是「真正需要的能力」。只验 --version 会漏掉 _ssl 加载失败的残缺安装：
#      它能打印版本号，却无法 import ssl —— 于是 pip 走不了 HTTPS，装依赖必然失败。
#      本脚本探的是 import ssl,venv。
#   3) 依赖装在仓库内 .venv，不污染系统解释器；仓库根 .python-path（不入库）可钉死基础解释器。
#   4) 原生命令（pip）会往 stderr 写警告，而 $ErrorActionPreference="Stop" 会把原生命令的
#      stderr 升级成**终止性错误**，脚本会在装依赖中途直接暴毙。所有原生命令统一走 Invoke-Native。
#   5) 启动后必须真的探到 HTTP 200 才允许打印成功，杜绝「假成功」。
#   6) Wait-Process 的 -Id 只能出现一次，多进程必须传数组；写成 -Id $a -Id $b 会参数绑定失败。

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "==> bid-pricing start" -ForegroundColor Cyan

# ============================================================================
# 原生命令统一入口
# 临时把 ErrorActionPreference 降为 Continue，避免 stderr 被升级成终止错误。
# ============================================================================
function Invoke-Native {
    param([string]$Exe, [string[]]$ArgList = @(), [switch]$Capture)

    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($Capture) {
            $text = (& $Exe @ArgList 2>&1 | Out-String)
            return [pscustomobject]@{ Code = $LASTEXITCODE; Text = $text }
        }
        & $Exe @ArgList 2>&1 | ForEach-Object { Write-Host $_ }
        return [pscustomobject]@{ Code = $LASTEXITCODE; Text = "" }
    }
    catch {
        return [pscustomobject]@{ Code = 1; Text = $_.Exception.Message }
    }
    finally {
        $ErrorActionPreference = $old
    }
}

# 最低版本以 pyproject.toml 的 requires-python 为唯一来源（此处不重复硬编码）
$MinPy = "3.11"
$Ppj = Join-Path $Root "pyproject.toml"
if (Test-Path -LiteralPath $Ppj) {
    $m = [regex]::Match((Get-Content -LiteralPath $Ppj -Raw), 'requires-python\s*=\s*">=\s*([0-9]+\.[0-9]+)')
    if ($m.Success) { $MinPy = $m.Groups[1].Value }
}

# ============================================================================
# 解释器能力探测：真跑一次 import ssl,venv，而不是只看文件存在
# ============================================================================
function Test-Interpreter {
    param([string]$Exe)

    if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) {
        return [pscustomobject]@{ Ok = $false; Version = $null; Reason = "路径不存在" }
    }
    if ((Get-Item -LiteralPath $Exe).Length -eq 0) {
        return [pscustomobject]@{ Ok = $false; Version = $null; Reason = "0 字节 —— Microsoft Store 应用执行别名占位符" }
    }

    $r = Invoke-Native -Exe $Exe -Capture -ArgList @(
        "-c", "import sys, ssl, venv; print('PYOK ' + sys.version.split()[0])"
    )

    if ($r.Code -ne 0) {
        $reason = "执行失败 (exit=$($r.Code))"
        if ($r.Text -match "_ssl") { $reason = "缺少 _ssl 模块 —— Python 安装残缺，pip 无法走 HTTPS" }
        elseif ($r.Text -match "Microsoft Store") { $reason = "Microsoft Store 占位符，执行时提示未安装 Python" }
        else {
            $last = @($r.Text -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
            if ($last.Count -gt 0) { $reason = "$reason：" + $last[0].Trim() }
        }
        return [pscustomobject]@{ Ok = $false; Version = $null; Reason = $reason }
    }
    if ($r.Text -notmatch "PYOK\s+(\S+)") {
        return [pscustomobject]@{ Ok = $false; Version = $null; Reason = "输出不可识别，未确认是 Python 3" }
    }

    $ver = $Matches[1]
    $verOk = $true
    try { $verOk = ([version]$ver -ge [version]$MinPy) } catch { $verOk = $true }
    if (-not $verOk) {
        return [pscustomobject]@{ Ok = $false; Version = $ver; Reason = "版本过低：$ver < $MinPy" }
    }
    return [pscustomobject]@{ Ok = $true; Version = $ver; Reason = "" }
}

# --- 候选清单（按优先级） ---
$VenvDir = Join-Path $Root ".venv"
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"

$Candidates = New-Object System.Collections.Generic.List[string]
function Add-Candidate([string]$Path) {
    if ($Path -and -not $Candidates.Contains($Path)) { [void]$Candidates.Add($Path) }
}

# 1) 显式环境变量
Add-Candidate $env:BIDPRICING_PYTHON
# 2) 仓库本地钉死文件（机器本地，不入库）
$PinFile = Join-Path $Root ".python-path"
if (Test-Path -LiteralPath $PinFile) {
    $pinned = @(Get-Content -LiteralPath $PinFile -ErrorAction SilentlyContinue |
                Where-Object { $_.Trim() } | Select-Object -First 1)
    if ($pinned.Count -gt 0) { Add-Candidate $pinned[0].Trim() }
}
# 3) 已有虚拟环境
Add-Candidate $VenvPy
# 4) PATH 上全部同名候选（跳过 WindowsApps 占位符；同一别名可能有多个）
foreach ($alias in @("python", "python3", "py")) {
    foreach ($hit in @(Get-Command $alias -All -ErrorAction SilentlyContinue)) {
        if (-not $hit.Source) { continue }
        if ($hit.Source -like "*\WindowsApps\*") { continue }
        Add-Candidate $hit.Source
    }
}
# 5) 常见安装位置（未加 PATH 的自装 Python 也能被找到）
foreach ($g in @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python3*\python.exe"),
        "C:\Python3*\python.exe",
        (Join-Path $env:ProgramFiles "Python3*\python.exe"))) {
    foreach ($f in @(Get-ChildItem -Path $g -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)) {
        Add-Candidate $f.FullName
    }
}

# --- 步骤 1：现成 .venv 可用就直接用 ---
$Py = $null
$VenvBroken = $false
$Rejected = New-Object System.Collections.Generic.List[string]

if (Test-Path -LiteralPath $VenvPy) {
    $t = Test-Interpreter $VenvPy
    if ($t.Ok) { $Py = [pscustomobject]@{ Exe = $VenvPy; Version = $t.Version } }
    else {
        $VenvBroken = $true
        $Rejected.Add("      - $VenvPy  →  $($t.Reason)（不可用，将重建）")
    }
}

# --- 步骤 2：找不到可用 .venv → 逐个探测候选，取第一个真正可用的作基础解释器 ---
$Base = $null
if (-not $Py) {
    foreach ($cand in $Candidates) {
        if ($cand -eq $VenvPy) { continue }
        $t = Test-Interpreter $cand
        if ($t.Ok) { $Base = [pscustomobject]@{ Exe = $cand; Version = $t.Version }; break }
        $Rejected.Add("      - $cand  →  $($t.Reason)")
    }
}

# --- 步骤 3：建 .venv ---
if (-not $Py -and $Base) {
    if ($VenvBroken) {
        $bak = Join-Path $Root (".venv.broken-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
        Write-Host "[WARN] 现成 .venv 不可用，改名保留为 $(Split-Path -Leaf $bak)（确认后可删）" -ForegroundColor Yellow
        Move-Item -LiteralPath $VenvDir -Destination $bak -Force
    }
    Write-Host "==> 建 .venv 隔离环境（依赖装在仓库内，不污染系统 Python）" -ForegroundColor Cyan
    $r = Invoke-Native -Exe $Base.Exe -ArgList @("-m", "venv", $VenvDir)
    if ($r.Code -ne 0) {
        Write-Host "[ERR] 创建 .venv 失败 (exit=$($r.Code))：$VenvDir" -ForegroundColor Red
        exit 1
    }
    $t = Test-Interpreter $VenvPy
    if (-not $t.Ok) {
        Write-Host "[ERR] .venv 建好后仍不可用：$($t.Reason)" -ForegroundColor Red
        exit 1
    }
    $Py = [pscustomobject]@{ Exe = $VenvPy; Version = $t.Version }
}

if (-not $Py) {
    Write-Host "[ERR] 找不到可用的 Python（需 >= $MinPy，且能 import ssl）。已尝试：" -ForegroundColor Red
    $Rejected | ForEach-Object { Write-Host $_ -ForegroundColor DarkYellow }
    Write-Host ""
    Write-Host "  修法一：设置 > 应用 > 高级应用设置 > 应用执行别名，关闭 python.exe / python3.exe" -ForegroundColor Yellow
    Write-Host "          （WindowsApps 下那两个 0 字节占位符会顶掉真正的 Python）" -ForegroundColor Yellow
    Write-Host "  修法二：安装 Python $MinPy+ 并把安装目录加入 PATH" -ForegroundColor Yellow
    Write-Host "  修法三：在仓库根建 .python-path 文件（单行绝对路径，不入库），或设环境变量：" -ForegroundColor Yellow
    Write-Host "          `$env:BIDPRICING_PYTHON = 'C:\Path\to\python.exe'" -ForegroundColor Yellow
    exit 1
}
Write-Host ("    Python: " + $Py.Version + "  [" + $Py.Exe + "]") -ForegroundColor DarkGray

# --- node (used for Excel export; warn but continue if missing) ---
if (Get-Command node -ErrorAction SilentlyContinue) {
    Write-Host ("    Node:   " + (& node --version)) -ForegroundColor DarkGray
}
else { Write-Host "[WARN] node not found. Excel export will fail (JSON result still downloadable)." -ForegroundColor Yellow }

# --- 依赖：全部装在 .venv 内 ---
$ReqFile = Join-Path $Root "requirements-web.txt"

function Test-Mods {
    param([string[]]$Mods)
    $r = Invoke-Native -Exe $Py.Exe -Capture -ArgList @("-c", ("import " + ($Mods -join ", ")))
    return ($r.Code -eq 0)
}

$WebMods = @("fastapi", "uvicorn", "multipart")
$SolverMods = @("pulp", "highspy")

Write-Host "==> check deps: $ReqFile"
if (-not (Test-Mods $WebMods)) {
    Write-Host "==> installing web deps into .venv (first run, may take a while)..." -ForegroundColor Cyan
    $r = Invoke-Native -Exe $Py.Exe -ArgList @("-m", "pip", "install", "--disable-pip-version-check", "-r", $ReqFile)
    if ($r.Code -ne 0) {
        Write-Host "[ERR] 依赖安装失败 (exit=$($r.Code))，请检查网络或 pip 镜像源。" -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Mods $WebMods)) {
        Write-Host "[ERR] 依赖装完仍无法导入 fastapi / uvicorn / multipart。" -ForegroundColor Red
        exit 1
    }
}
if (-not (Test-Mods $SolverMods)) {
    Write-Host "[WARN] pulp/highspy 不可导入，Phase 2 MILP 将走 SKIP/UNAVAILABLE（网页仍可用）。" -ForegroundColor Yellow
}

# --- output dir (logs) ---
$LogDir = Join-Path $Root "outputs\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# --- start backend 8000 ---
$BackendPort = 8000
$FrontendPort = 8080
$env:PYTHONPATH = "src"
$env:PYTHONUNBUFFERED = "1"

Write-Host "==> backend  http://127.0.0.1:$BackendPort  ..."
$backend = Start-Process -FilePath $Py.Exe `
    -ArgumentList @("-m", "uvicorn", "api.app:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
    -WorkingDirectory $Root -PassThru -NoNewWindow `
    -RedirectStandardOutput (Join-Path $LogDir "backend.out.log") `
    -RedirectStandardError (Join-Path $LogDir "backend.err.log")

# --- start frontend 8080 (static server only) ---
Write-Host "==> frontend http://127.0.0.1:$FrontendPort  ..."
$frontend = Start-Process -FilePath $Py.Exe `
    -ArgumentList @("-m", "http.server", "$FrontendPort", "--directory", "frontend") `
    -WorkingDirectory $Root -PassThru -NoNewWindow `
    -RedirectStandardOutput (Join-Path $LogDir "frontend.out.log") `
    -RedirectStandardError (Join-Path $LogDir "frontend.err.log")

# --- 启动后真实探测：没探到就不许打印成功 ---
function Wait-HttpOk {
    param([string]$Url, [int]$TimeoutSec)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { return $true }
        }
        catch { }
        Start-Sleep -Milliseconds 400
    }
    return $false
}

function Stop-Both {
    Stop-Process -Id @($backend.Id, $frontend.Id) -Force -ErrorAction SilentlyContinue
}

if (-not (Wait-HttpOk "http://127.0.0.1:$BackendPort/api/health" 60)) {
    Write-Host "[ERR] 后端 60s 内未就绪（http://127.0.0.1:$BackendPort/api/health）。" -ForegroundColor Red
    if ($backend.HasExited) { Write-Host ("      后端进程已退出，exit code = " + $backend.ExitCode) -ForegroundColor Red }
    Write-Host "      日志：outputs\logs\backend.err.log" -ForegroundColor Yellow
    Stop-Both
    exit 1
}
if (-not (Wait-HttpOk "http://127.0.0.1:$FrontendPort/" 20)) {
    Write-Host "[ERR] 前端 20s 内未就绪（http://127.0.0.1:$FrontendPort/）。" -ForegroundColor Red
    Write-Host "      日志：outputs\logs\frontend.err.log" -ForegroundColor Yellow
    Stop-Both
    exit 1
}

Write-Host ""
Write-Host "  frontend: http://127.0.0.1:$FrontendPort" -ForegroundColor Green
Write-Host "  backend:  http://127.0.0.1:$BackendPort/api/health" -ForegroundColor Green
Write-Host "  logs:     outputs\logs\*.log" -ForegroundColor DarkGray
Write-Host "Press Ctrl+C to stop both services ..." -ForegroundColor DarkGray

try {
    # -Id 只能出现一次；多进程必须传数组。
    # 写成 -Id $a -Id $b 会以「多次指定了参数 Id」参数绑定失败，停止路径直接报错。
    Wait-Process -Id @($backend.Id, $frontend.Id) -ErrorAction SilentlyContinue
}
catch [System.Management.Automation.PipelineStoppedException] {
    # Ctrl+C：预期路径
}
catch {
    Write-Host ("[WARN] 等待服务时出错：" + $_.Exception.Message) -ForegroundColor Yellow
}
finally {
    Write-Host "==> stopping services"
    Stop-Process -Id @($backend.Id, $frontend.Id) -Force -ErrorAction SilentlyContinue
}
