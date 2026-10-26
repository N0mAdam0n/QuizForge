<#
  百炼 QuizForge 便携版发布脚本
  用法:  powershell -ExecutionPolicy Bypass -File backend\scripts\publish-release.ps1 -Version 0.1.1 [-SkipBuild]
  流程: 写入版本号 → 构建 → 备份元数据 → 签名(逐个询问密钥密码) → 上传 → 服务器校验
  密码只在签名进程里读取，不会被本脚本记录或写入日志。
#>
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [switch]$SkipBuild,
    [switch]$MakeRelease,         # 上线成功后顺便生成 D:\Release\v<ver> 发布包
    [string]$Server = "root@120.26.57.15",
    [string]$RemoteDir = "/srv/updates",
    [string]$PublicBase = "https://120.26.57.15/updates",
    [string]$RepoDir = "D:\qb-update-repo",
    [string]$KeysDir = "D:\qb-keys"
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
if (Test-Path "D:\tools\uv\bin") { $env:Path = "D:\tools\uv\bin;$env:Path" }

$AppName = "QuizForge-Portable"
$Backend = Split-Path -Parent $PSScriptRoot
$Root = Split-Path -Parent $Backend
$Bundle = Join-Path $Backend "dist\$AppName"
$LogDir = "D:\qb-publish-logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null
$Log = Join-Path $LogDir "publish-$Version-$(Get-Date -Format yyyyMMdd-HHmmss).log"
$script:StepNo = 0

function Log($m) { Add-Content -Path $Log -Value "$(Get-Date -Format o) $m" -Encoding UTF8 }
function Step($title) {
    $script:StepNo++
    Write-Host ""
    Write-Host "==== 第 $script:StepNo 步：$title ====" -ForegroundColor Cyan
    Log "STEP $script:StepNo $title"
}
function Info($m) { Write-Host "  $m"; Log $m }
function Fail($m) { throw $m }
function Run-Scp([string[]]$files, [string]$dest) {
    # BatchMode 只禁止交互式密码提示，不影响进度条（控制台为 TTY 时 scp 会显示进度）
    & scp -o BatchMode=yes @files "${Server}:$dest"
    if ($LASTEXITCODE -ne 0) { Fail "scp 上传失败（退出码 $LASTEXITCODE）：$dest" }
}

$ok = $false
try {
    Write-Host "百炼 QuizForge 发布 v$Version" -ForegroundColor White
    Info "日志：$Log"

    Step "检查环境与版本号"
    foreach ($cmd in "uv", "scp", "ssh", "curl.exe") {
        if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { Fail "找不到命令 $cmd" }
    }
    if (-not (Test-Path (Join-Path $RepoDir ".tufup-repo-config"))) { Fail "签名仓库未初始化：$RepoDir" }
    $cfg = Get-Content (Join-Path $RepoDir ".tufup-repo-config") -Raw | ConvertFrom-Json
    if ($cfg.app_name -ne $AppName) { Fail "签名仓库 app_name 为 '$($cfg.app_name)'，应为 '$AppName'（请先迁移仓库配置）" }
    & ssh -o BatchMode=yes -o ConnectTimeout=10 $Server "test -d $RemoteDir/targets && test -d $RemoteDir/metadata"
    if ($LASTEXITCODE -ne 0) { Fail "无法通过 SSH 密钥连接服务器或目录不存在：$Server`:$RemoteDir" }
    Info "服务器连接正常"
    $verFile = Join-Path $Backend "app\_version.py"
    $cur = (Select-String $verFile -Pattern '^__version__ = "(.+)"').Matches[0].Groups[1].Value
    if ($cur -ne $Version) {
        [IO.File]::WriteAllText($verFile, "__version__ = `"$Version`"`n", (New-Object Text.UTF8Encoding($false)))
        Info "_version.py：$cur → $Version"
    } else { Info "_version.py 已是 $Version" }
    if (Get-ChildItem (Join-Path $RepoDir "targets") -Filter "$AppName-$Version.*" -ErrorAction SilentlyContinue) {
        Fail "签名仓库中已存在 v$Version，版本号必须递增"
    }

    if ($SkipBuild) { Step "构建（已跳过）" } else {
        Step "构建便携版"
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "build-portable.ps1")
        if ($LASTEXITCODE -ne 0) { Fail "构建失败（退出码 $LASTEXITCODE）" }
    }
    if (-not (Test-Path "$Bundle\QuizForge.exe")) { Fail "构建产物缺失：$Bundle\QuizForge.exe" }
    if ((Test-Path "$Bundle\data") -or (Test-Path "$Bundle\updates")) { Fail "构建产物中不应包含 data/updates 目录" }
    if (-not (Test-Path "$Bundle\_internal\update\installer.ps1")) { Fail "构建产物缺少 update\installer.ps1" }

    Step "备份签名元数据"
    $bak = "D:\qb-update-repo-backup\metadata-before-$Version-$(Get-Date -Format yyyyMMddHHmmss)"
    New-Item -ItemType Directory -Force $bak | Out-Null
    Copy-Item "$RepoDir\metadata\*" $bak
    Info "已备份到 $bak"

    Step "签名（将逐个询问所需密钥的密码，输入显示为 *）"
    Push-Location $Backend
    try {
        & uv run python scripts/manage_portable_updates.py publish --repo-dir $RepoDir --keys-dir $KeysDir --bundle-dir $Bundle
        if ($LASTEXITCODE -ne 0) { Fail "签名失败（退出码 $LASTEXITCODE）" }
    } finally { Pop-Location }
    $new = @(Get-ChildItem "$RepoDir\targets" -Filter "$AppName-$Version.*")
    if ($new.Count -eq 0) { Fail "签名后未找到 v$Version 的目标文件" }
    $new | ForEach-Object { Info ("新目标：{0}（{1:N1} MB）" -f $_.Name, ($_.Length / 1MB)) }

    Step "上传目标文件"
    Run-Scp ($new | ForEach-Object FullName) "$RemoteDir/targets/"

    Step "上传元数据"
    Run-Scp @(Get-ChildItem "$RepoDir\metadata" -Filter "*.json" | ForEach-Object FullName) "$RemoteDir/metadata/"

    Step "服务器校验"
    foreach ($f in $new) {
        $remoteSize = (& ssh -o BatchMode=yes $Server "stat -c %s $RemoteDir/targets/$($f.Name)").Trim()
        if ($remoteSize -ne "$($f.Length)") { Fail "服务器文件大小不一致：$($f.Name)（本地 $($f.Length)，服务器 $remoteSize）" }
        Info "✓ $($f.Name) 大小一致"
    }
    # 服务器 targets.json 可能比上传稍晚生效（CDN/缓存），重试几次再判定
    $pending = @($new | ForEach-Object Name)
    for ($try = 1; $try -le 8 -and $pending.Count -gt 0; $try++) {
        $served = (& curl.exe -sk -H "Cache-Control: no-cache" "$PublicBase/metadata/targets.json?t=$(Get-Date -Format yyyyMMddHHmmssfff)") -join "`n"
        $pending = @($pending | Where-Object { $served -notmatch ('"' + [regex]::Escape($_) + '"') })
        if ($pending.Count -gt 0) { Info "线上 targets.json 尚未包含 $($pending -join ', ')，第 $try/8 次，5 秒后重试"; Start-Sleep -Seconds 5 }
    }
    if ($pending.Count -gt 0) { Fail "线上 targets.json 中未出现：$($pending -join ', ')" }
    Info "✓ 线上 targets.json 已包含 v$Version"
    $ok = $true
} catch {
    Log "ERROR $($_.Exception.Message)"
    Write-Host ""
    Write-Host "发布失败 ✗：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "日志：$Log" -ForegroundColor Red
}
if ($ok) {
    Write-Host ""
    Write-Host "发布完成 ✓  百炼 QuizForge v$Version 已上线" -ForegroundColor Green
    Write-Host "  目标文件：$(($new | ForEach-Object Name) -join ', ')" -ForegroundColor Green
    Write-Host "  元数据备份：$bak" -ForegroundColor Green
    Write-Host "  日志：$Log" -ForegroundColor Green
    Log "DONE"
    if ($MakeRelease) {
        Step "生成本地发布包 D:\Release\v$Version"
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "make-release.ps1") -Version $Version -SkipPortableBuild
        if ($LASTEXITCODE -ne 0) { Write-Host "发布包生成失败（不影响已上线的更新）" -ForegroundColor Yellow }
    }
}
Read-Host "按回车关闭"
if (-not $ok) { exit 1 }
