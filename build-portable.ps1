# 一键构建 百炼 QuizForge 便携版
# 用法（放在项目根目录运行）：
#   powershell -ExecutionPolicy Bypass -File .\build-portable.ps1
#   powershell -ExecutionPolicy Bypass -File .\build-portable.ps1 -TestDir D:\qb-test -SkipFrontend
param(
    [string]$TestDir = "",        # 填了就把构建结果复制到这个测试目录
    [switch]$SkipFrontend         # 前端没改时可跳过，节省时间
)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Dist = Join-Path $Backend "dist\QuizForge-Portable"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Run($exe, [string[]]$argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { throw "$exe $($argv -join ' ') 失败 (exit $LASTEXITCODE)" }
}

$rootJson = Join-Path $Backend "deploy\windows\update\root.json"
if (Test-Path $rootJson) {
    Write-Host "root.json: $((Get-Item $rootJson).LastWriteTime)" -ForegroundColor Green
} else {
    Write-Warning "未找到 $rootJson，构建出的客户端将无法热更新（先运行 manage_portable_updates.py init）"
}

if (-not $SkipFrontend) {
    Step "构建前端"
    Push-Location $Frontend
    try { Run "pnpm" @("install"); Run "pnpm" @("generate") } finally { Pop-Location }
}

Step "构建后端便携版"
Push-Location $Backend
try {
    Run "uv" @("sync")
    Run "uv" @("run", "--with", "pyinstaller", "pyinstaller", "run-portable.spec", "--clean", "--noconfirm")
    Run "uv" @("run", "python", "scripts/package_portable.py")
} finally { Pop-Location }

$found = Get-ChildItem -Path $Dist -Recurse -Filter root.json -ErrorAction SilentlyContinue
if ($found) { Write-Host "包内 root.json: $($found[0].FullName)" -ForegroundColor Green }
else { Write-Warning "构建结果中没有 root.json" }

if ($TestDir) {
    Step "复制到测试目录 $TestDir"
    $target = Join-Path $TestDir "QuizForge-Portable"
    if (Test-Path $target) {
        $dataDir = Join-Path $target "data"
        if (Test-Path $dataDir) {
            throw "$target 已存在且含 data\，为防误删测试数据请手动处理后重试"
        }
        Remove-Item -Recurse -Force $target
    }
    New-Item -ItemType Directory -Force $TestDir | Out-Null
    Copy-Item -Recurse $Dist $target
    Write-Host "测试版位于 $target\QuizForge.exe" -ForegroundColor Green
}

Step "完成"
Get-ChildItem (Join-Path $Backend "dist") -Filter "QuizForge-Portable-*.zip" | Sort-Object LastWriteTime | Select-Object -Last 1 | ForEach-Object { Write-Host "ZIP: $($_.FullName)" }
