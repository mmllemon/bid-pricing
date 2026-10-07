# bid-pricing one-click launcher (Windows PowerShell 5.1+)
# 启动后端 8000（Python FastAPI，含前端静态）+ 个人工作台 3456（Node，可选，BIDPRICING_WORKBENCH_PORT 可覆盖；
# agent 已并入工作台进程（/agent 前缀），不再独立占 :8010；:8080 已并入 :8000；
#   代码取仓库内 workbench-app/（React 前端）+ workbench-server/（Express 后端），不再指向 skill 安装目录）；
# 首次运行在仓库 .venv 内建隔离环境并装依赖；Ctrl+C 停止全部。
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
#   7) 端口三重防护：预检占用 / 探活后校验进程存活 / 端口可覆盖。
#      起服务前先查端口占用并明说占用者；探活通过后还须确认是自己拉起的进程
#      还活着；端口可用 BIDPRICING_BACKEND_PORT / BIDPRICING_WORKBENCH_PORT 覆盖。
#   8) WORKBENCH_UPSTREAM 必须在**起后端进程之前**设好：api/wb_proxy.py 在 import 时
#      读它（默认 127.0.0.1:3456），后端拉起后再改只能影响新进程，反代仍指向旧地址。
#   9) lshu 工作台要跑 src/index.ts（node --import tsx），不能跑 dist/index.js：
#      那份 dist 由 moduleResolution=bundler 的 tsc 产出，相对导入不带扩展名，
#      普通 node 按 ESM 解析会 ERR_MODULE_NOT_FOUND —— 它的 npm start 本身就是坏的。
#  10) lshu 工作台是**仓库内 vendored 代码**（workbench-app/ + workbench-server/），
#      故本脚本要负责它的「依赖安装 / 前端构建 / 启动」三段，且全部按增值组件处理：
#      Node 缺失、产物构建失败、端口被外来服务占用，一律只告警不阻断主应用。
#      注意 3456 上回答 /api/health 的是**同一个 Express 进程**（SPA 与 API 同进程），
#      前端 dist 由它在请求期读盘，故重建产物后无需重启。
#
# 启动拓扑（一览表，出问题先看这张）：
#
#   浏览器 ──► :8000  后端 API + 前端静态（FastAPI，api/app.py；/ 挂 frontend/）
#                ├─ /api/*              报价 / 项目 / 井库 / 方案
#                ├─ /*                  前端静态（html=True，/ → index.html）
#                └─ /api/wb/* ──► :3456 反代（strangler；已收编的走本地 wb_local）
#              :3456  个人工作台（Express，SPA 与 API 同进程；可选边车）
#                └─ /agent/*           Agent（Pi Durable，原独立 :8010，已并入本进程）
#
#   端口覆盖（重跑生效，无需改脚本）：
#     $env:BIDPRICING_BACKEND_PORT（8000）/ $env:BIDPRICING_WORKBENCH_PORT（3456）
#
#   数据目录（备份就拷这几个）：
#     outputs/projects/<user>/   quote.db（方案）＋ projects.json（项目）＋ well-library.json（井库）
#     outputs/workbench-data/     workbench.db（工作台待办/热点/小红书）
#     agent-service/agent.sqlite  Agent 会话 / 提醒 / 审批记录
#   日志：outputs\logs\*.log（backend / workbench 各一对 out/err）
#
#   故障速查：
#     启动报端口被占用   → 按提示用 $env:<名> 换端口重跑
#     页面空白 / 转圈    → 先看 outputs\logs\backend.err.log（:8000 挂则全挂）
#     工作台 iframe 空白 → outputs\logs\workbench.err.log（边车，可选，不影响主应用）
#     审批 / 模型设置 401 → 服务端 AGENT_API_TOKEN 与面板 token 是否一致
#     井库 / 项目列表为空 → :8000 是否在跑；看 backend.err.log

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

# --- node (used for Excel export and agent-service; warn but continue if missing) ---
if (Get-Command node -ErrorAction SilentlyContinue) {
    Write-Host ("    Node:   " + (& node --version)) -ForegroundColor DarkGray
}
else { Write-Host "[WARN] node not found. Excel export and agent-service will be unavailable (JSON result still downloadable)." -ForegroundColor Yellow }

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

# ============================================================================
# 端口：默认 8000（后端+前端）/ 3456（工作台，含 agent），可用环境变量覆盖（端口被其他应用占用时无需改脚本）
# ============================================================================
function Get-PortOrDefault {
    param([string]$EnvName, [int]$Default)
    $raw = [Environment]::GetEnvironmentVariable($EnvName)
    if (-not $raw) { return $Default }
    $p = 0
    if (-not [int]::TryParse($raw.Trim(), [ref]$p) -or $p -lt 1 -or $p -gt 65535) {
        Write-Host "[ERR] 环境变量 $EnvName='$raw' 不是合法端口（1-65535）。" -ForegroundColor Red
        exit 1
    }
    return $p
}

function Assert-PortFree {
    param([int]$Port, [string]$Label, [string]$EnvName)
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
    }
    catch {
        Write-Host "[WARN] 无法预检端口占用（Get-NetTCPConnection 不可用），跳过预检。" -ForegroundColor Yellow
        return
    }
    if ($conn) {
        $procName = ""
        try { $procName = (Get-Process -Id $conn.OwningProcess -ErrorAction Stop).ProcessName } catch { }
        Write-Host "[ERR] $Label 端口 $Port 已被占用：PID $($conn.OwningProcess)（$procName）。" -ForegroundColor Red
        Write-Host "      换端口无需改脚本：`$env:$EnvName = '<端口>' 后重跑。"
        exit 1
    }
}

$BackendPort  = Get-PortOrDefault "BIDPRICING_BACKEND_PORT" 8000
Assert-PortFree $BackendPort  "后端" "BIDPRICING_BACKEND_PORT"

# ============================================================================
# lshu-workbench 边车：解析目录与端口，并**提前**把反代上游告诉后端。
# WORKBENCH_UPSTREAM 必须在起后端进程之前设置：api/wb_proxy.py 在模块 import 时
# 读取它（默认 http://127.0.0.1:3456），后端一旦拉起再改就晚了。
# 目录是**仓库内 vendored 代码**（收编后不再指向 skill 安装目录）：
#   workbench-app/     React 前端，构建产物 dist/ 由 Express 在请求期读盘
#   workbench-server/  Express 后端（SPA 与 API 同进程），入口是 TS 源码
# 端口优先级：BIDPRICING_WORKBENCH_PORT > workbench-server\.env.local 的 PORT > 3456。
# ============================================================================
$WbAppDir = Join-Path $Root "workbench-app"
$WbBackendDir = Join-Path $Root "workbench-server"
$WbDist = Join-Path $WbAppDir "dist"
$WbDataDir = Join-Path $Root "outputs\workbench-data"
# 入口是 TS 源码而不是 dist：该 skill 的 tsconfig 用 moduleResolution=bundler，
# tsc 产出的 dist 里全是无扩展名的相对导入（import './bootstrapEnv'），
# 普通 node 按 ESM 规则解析必然 ERR_MODULE_NOT_FOUND —— 即它自己的 npm start 就是坏的。
# 故用 tsx 直跑 src/index.ts（原 skill 的 Start.ps1 亦如此）。
$WbEntry = Join-Path $WbBackendDir "src\index.ts"
$WbTsx = Join-Path $WbBackendDir "node_modules\tsx"
$WbEnvFile = Join-Path $WbBackendDir ".env.local"

$WbPort = 3456
if ($env:BIDPRICING_WORKBENCH_PORT) {
    $WbPort = Get-PortOrDefault "BIDPRICING_WORKBENCH_PORT" 3456
}
elseif (Test-Path -LiteralPath $WbEnvFile) {
    # 与后端读同一份配置，避免「脚本探一个端口、服务绑另一个端口」的静默错位
    $wm = [regex]::Match((Get-Content -LiteralPath $WbEnvFile -Raw), '(?m)^\s*PORT\s*=\s*"?(\d+)"?')
    if ($wm.Success) { $WbPort = [int]$wm.Groups[1].Value }
}

$env:WORKBENCH_UPSTREAM = "http://127.0.0.1:$WbPort"

# --- start backend ---
$env:PYTHONPATH = "src"
$env:PYTHONUNBUFFERED = "1"

Write-Host "==> backend  http://127.0.0.1:$BackendPort  ..."
# P2: 严禁加 --workers！api/app.py 的 _SLOT_LOCK 是 threading.Lock，不跨进程；
# 多 worker 下每个进程各持一把锁，槽位并发写会互相覆盖。真要加 workers，先把锁换成 SQLite 事务/文件锁。
$backend = Start-Process -FilePath $Py.Exe `
    -ArgumentList @("-m", "uvicorn", "api.app:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
    -WorkingDirectory $Root -PassThru -NoNewWindow `
    -RedirectStandardOutput (Join-Path $LogDir "backend.out.log") `
    -RedirectStandardError (Join-Path $LogDir "backend.err.log")

# P0 架构收敛（2026-10-07）：前端静态改由 :8000 FastAPI 同进程 serving（api/app.py 末尾 mount），
# 不再起 python http.server :8080。

# ============================================================================
# agent 依赖（Pi Durable）：已并入工作台进程（workbench-server :3456 的 /agent 前缀），
# 不再独立起 :8010 进程。此处只负责装 agent-service/ 的 npm 依赖（server.mjs 的
# @earendil-works/* 裸导入从该目录的 node_modules 解析）；装失败则工作台段会一并告警。
# AGENT_SQLITE / agent-model-config.json 默认仍在 agent-service/ 下，就地沿用。
# ============================================================================
$AgentDir = Join-Path $Root "agent-service"
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not (Test-Path (Join-Path $AgentDir "node_modules"))) {
    Write-Host "==> agent 依赖：首次安装（npm install，可能要一会儿）..." -ForegroundColor Cyan
    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($npmCmd) {
        Push-Location $AgentDir
        try { $r = Invoke-Native -Exe $npmCmd.Source -ArgList @("install", "--no-audit", "--no-fund") -Capture }
        finally { Pop-Location }
        if ($r.Code -ne 0) {
            Write-Host "[WARN] agent 依赖安装失败，工作台内的 /agent 可能不可用。npm 输出：" -ForegroundColor Yellow
            @($r.Text -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 3) |
                ForEach-Object { Write-Host "      $_" -ForegroundColor DarkYellow }
        }
    }
    else { Write-Host "[WARN] npm 不可用，跳过 agent 依赖安装。" -ForegroundColor Yellow }
}

# lshu-workbench 实例（个人工作台，默认 3456）
# 同为增值组件：任何故障只告警跳过，不阻断主应用。
# 有意不用 Assert-PortFree 预检：3456 若被「已在跑的工作台」占用，探活会通过
# → 按「复用外来实例」处理；被别的服务占用则探活失败 → 告警跳过。
# 代码是仓库内 vendored（workbench-app/ + workbench-server/），故本段含
# 「依赖安装 → 前端构建 → 启动」三步，任一步失败都只放弃本组件、不影响主应用。
# ============================================================================
$workbench = $null
$npmCmd = Get-Command npm -ErrorAction SilentlyContinue

function Invoke-WbNpm {
    # npm 是原生命令，必须走 Invoke-Native：否则 stderr 警告会被 Stop 升级成终止错误
    param([string]$WorkDir, [string[]]$ArgList, [string]$What)
    if (-not $npmCmd) {
        Write-Host "[WARN] npm 不可用，$What 无法执行（不影响主应用）。" -ForegroundColor Yellow
        return $false
    }
    Push-Location $WorkDir
    try { $r = Invoke-Native -Exe $npmCmd.Source -ArgList $ArgList -Capture }
    finally { Pop-Location }
    if ($r.Code -ne 0) {
        Write-Host "[WARN] $What 失败，跳过个人工作台（不影响主应用）。npm 输出：" -ForegroundColor Yellow
        @($r.Text -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 3) |
            ForEach-Object { Write-Host "      $_" -ForegroundColor DarkYellow }
        return $false
    }
    return $true
}

if (-not $nodeCmd) {
    Write-Host "[WARN] node 不可用，跳过个人工作台（不影响主应用）。" -ForegroundColor Yellow
}
elseif (-not (Test-Path -LiteralPath $WbEntry)) {
    Write-Host "[WARN] 未找到工作台后端入口 $WbEntry，跳过（该组件为仓库内 workbench-server/）。" -ForegroundColor Yellow
}
else {
    $wbOk = $true
    # 依赖：前后端各自独立 node_modules，两者都不入库，故全新克隆必装。
    if (-not (Test-Path (Join-Path $WbBackendDir "node_modules"))) {
        Write-Host "==> workbench: 安装后端依赖（npm install，可能要一会儿）..." -ForegroundColor Cyan
        $wbOk = Invoke-WbNpm -WorkDir $WbBackendDir -ArgList @("install", "--no-audit", "--no-fund") -What "工作台后端依赖安装"
    }
    if ($wbOk -and -not (Test-Path (Join-Path $WbAppDir "node_modules"))) {
        Write-Host "==> workbench: 安装前端依赖（npm install，可能要一会儿）..." -ForegroundColor Cyan
        $wbOk = Invoke-WbNpm -WorkDir $WbAppDir -ArgList @("install", "--no-audit", "--no-fund") -What "工作台前端依赖安装"
    }
    if ($wbOk -and -not (Test-Path -LiteralPath $WbTsx)) {
        Write-Host "[WARN] 工作台后端缺少 tsx 运行时（$WbTsx），跳过（在该目录跑 npm install 可补齐）。" -ForegroundColor Yellow
        $wbOk = $false
    }
    # 前端产物：Express 只在请求期读 workbench-app/dist，缺了页面就 404。
    # 仅在缺失时构建（构建慢）；源码改过后需自行 npm run build，与「重建无需重启」配套。
    if ($wbOk -and -not (Test-Path -LiteralPath $WbDist)) {
        Write-Host "==> workbench: 构建前端产物（npm run build）..." -ForegroundColor Cyan
        if ((-not (Invoke-WbNpm -WorkDir $WbAppDir -ArgList @("run", "build") -What "工作台前端构建")) -or
            -not (Test-Path -LiteralPath $WbDist)) {
            Write-Host "[WARN] 工作台前端产物不可用（$WbDist），跳过个人工作台（不影响主应用）。" -ForegroundColor Yellow
            $wbOk = $false
        }
    }
    if ($wbOk) {
        # dotenv 不覆盖已存在的 process.env：显式设 PORT 是让「脚本探的端口」与
        # 「服务实际绑的端口」强制一致（脚本从 .env.local 读到的默认值此时无所谓）。
        $env:PORT = "$WbPort"
        # 工作台自有数据库必须落在本项目 outputs\ 下，不得写进仓库外路径（收编要求）。
        # workbench-server/src/db.ts 以 WORKBENCH_DATA_DIR 为根，缺省是包内 data/。
        $env:WORKBENCH_DATA_DIR = $WbDataDir
        # 桌面扫描根目录：缺省扫 E:\工作liam（用户工作目录）。
        # scanner.ts 口径：settings.scanRoot > $env:WORKBENCH_SCAN_ROOT > ~/Desktop。
        # 若曾在设置页改过扫描目录，以设置页为准（DB 里 settings.scanRoot 优先）。
        $env:WORKBENCH_SCAN_ROOT = "E:\工作liam"
        # agent 已并入本进程（/agent）：token 透传（前端面板设置里填同一值；未设置则本地零配置可用）。
        # Start-Process 默认继承父进程环境，这里显式写出以防将来改用 -Environment 启动。
        if ($env:AGENT_API_TOKEN) { $env:AGENT_API_TOKEN = $env:AGENT_API_TOKEN }
        if ($env:BIDPRICING_API_TOKEN) { $env:BIDPRICING_API_TOKEN = $env:BIDPRICING_API_TOKEN }
        # agent 回调后端（工具执行）地址：默认 127.0.0.1:8000，随 BIDPRICING_BACKEND_PORT 走。
        $env:BACKEND_URL = "http://127.0.0.1:$BackendPort"
        Write-Host "==> workbench http://127.0.0.1:$WbPort/api/health  ..."
        $workbench = Start-Process -FilePath $nodeCmd.Source `
            -ArgumentList @("--import", "tsx", "src/index.ts") `
            -WorkingDirectory $WbBackendDir -PassThru -NoNewWindow `
            -RedirectStandardOutput (Join-Path $LogDir "workbench.out.log") `
            -RedirectStandardError (Join-Path $LogDir "workbench.err.log")
        # 子进程已拿到环境快照，立即复原，避免这些泛用名污染后续同级进程
        Remove-Item Env:\PORT -ErrorAction SilentlyContinue
        Remove-Item Env:\WORKBENCH_DATA_DIR -ErrorAction SilentlyContinue
        Remove-Item Env:\WORKBENCH_SCAN_ROOT -ErrorAction SilentlyContinue
        Remove-Item Env:\BACKEND_URL -ErrorAction SilentlyContinue
    }
}

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

function Stop-All {
    # -Id 只能出现一次；多进程传数组。未启动的边车（$workbench）为 $null，过滤掉。
    $ids = @($backend.Id)
    if ($workbench) { $ids = @($ids + $workbench.Id) }
    Stop-Process -Id @($ids) -Force -ErrorAction SilentlyContinue
}

if (-not (Wait-HttpOk "http://127.0.0.1:$BackendPort/api/health" 60)) {
    Write-Host "[ERR] 后端 60s 内未就绪（http://127.0.0.1:$BackendPort/api/health）。" -ForegroundColor Red
    if ($backend.HasExited) { Write-Host ("      后端进程已退出，exit code = " + $backend.ExitCode) -ForegroundColor Red }
    Write-Host "      日志：outputs\logs\backend.err.log" -ForegroundColor Yellow
    Stop-All
    exit 1
}
if ($backend.HasExited) {
    # 探活 200 可能由占用同端口的外来服务答出——自己拉起的进程死了就不许报成功。
    Write-Host "[ERR] /api/health 有 200 应答，但本脚本拉起的后端进程已退出——应答来自占用 $BackendPort 的其他服务（假成功拦截）。" -ForegroundColor Red
    Stop-All
    exit 1
}
# 前端静态与后端同进程（:8000 的 / 挂 frontend/）：/api/health 已证明进程存活，
# 这里只确认静态挂载生效（目录缺失时挂载跳过，/ 会 404）。
if (-not (Wait-HttpOk "http://127.0.0.1:$BackendPort/" 20)) {
    Write-Host "[ERR] 前端静态 20s 内未就绪（http://127.0.0.1:$BackendPort/ 应 200）。" -ForegroundColor Red
    Write-Host "      日志：outputs\logs\backend.err.log" -ForegroundColor Yellow
    Stop-All
    exit 1
}

# agent 已并入工作台进程（/agent）：只做告警级探活，不阻断。
if ($workbench) {
    if (-not (Wait-HttpOk "http://127.0.0.1:$WbPort/agent/health" 15)) {
        Write-Host "[WARN] /agent 15s 内未就绪（agent 挂载失败或依赖缺失），AI 助手不可用，不影响主应用。日志：outputs\logs\workbench.err.log" -ForegroundColor Yellow
    }
}

# workbench（边车）：语义同 agent。注意 3456 上若跑的是「已在用的工作台」，
# 探活会通过——此时不复用也不报错，只是 Ctrl+C 不会停它。
if ($workbench) {
    if (Wait-HttpOk "http://127.0.0.1:$WbPort/api/health" 30) {
        if ($workbench.HasExited) {
            Write-Host "[WARN] :$WbPort/api/health 已有人应答，但本拉起的工作台进程已退出——复用在跑的实例（Ctrl+C 时不会停它）。" -ForegroundColor Yellow
            $workbench = $null
        }
    } else {
        Write-Host "[WARN] 个人工作台 30s 内未就绪，已跳过（不影响主应用）。日志：outputs\logs\workbench.err.log" -ForegroundColor Yellow
        Stop-Process -Id @($workbench.Id) -Force -ErrorAction SilentlyContinue
        $workbench = $null
    }
}

Write-Host ""
Write-Host "  frontend: http://127.0.0.1:$BackendPort  （与后端同进程）" -ForegroundColor Green
Write-Host "  backend:  http://127.0.0.1:$BackendPort/api/health" -ForegroundColor Green
Write-Host "  agent:    http://127.0.0.1:$WbPort/agent/health  （已并入工作台进程）" -ForegroundColor Green
if ($workbench) { Write-Host "  workbench: http://127.0.0.1:$WbPort/  (个人工作台；母项目 #workbench 以 iframe 嵌入本地址)" -ForegroundColor Green }
Write-Host "  logs:     outputs\logs\*.log" -ForegroundColor DarkGray
Write-Host "Press Ctrl+C to stop all services ..." -ForegroundColor DarkGray

try {
    # -Id 只能出现一次；多进程必须传数组。
    # 写成 -Id $a -Id $b 会以「多次指定了参数 Id」参数绑定失败，停止路径直接报错。
    $ids = @($backend.Id)
    if ($workbench) { $ids = @($ids + $workbench.Id) }
    Wait-Process -Id @($ids) -ErrorAction SilentlyContinue
}
catch [System.Management.Automation.PipelineStoppedException] {
    # Ctrl+C：预期路径
}
catch {
    Write-Host ("[WARN] 等待服务时出错：" + $_.Exception.Message) -ForegroundColor Yellow
}
finally {
    Write-Host "==> stopping services"
    Stop-All
}
