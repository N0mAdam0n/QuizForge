<#
  百炼 QuizForge 本地发布包生成脚本
  用法:  powershell -ExecutionPolicy Bypass -File backend\scripts\make-release.ps1 -Version 0.2.1
         [-SourceDir <历史版本 worktree>] [-SkipPortableBuild] [-SkipFrontend] [-OutRoot D:\Release] [-Force]
  产物（D:\Release\v<ver>\）:
    QuizForge-Setup-<ver>.exe     Inno Setup 安装程序（单文件桌面版，装到 Program Files）
    QuizForge-Portable-<ver>.zip  便携版（与热更新发布的目录完全一致，解压即用）
    QuizForge-Lite-<ver>.zip      轻量版（同便携版内容，沿用 package_to_output 的 Lite 命名）
    SHA256SUMS.txt                以上文件的 SHA-256
    发布说明.md                   本版本的提交记录（来自 git log）
  不读取、不复制任何签名密钥；不上传、不推送。
  注意：用完历史版本 worktree 后请用 `git worktree remove` 清理，切勿对其 rd /s（pnpm 的目录联接可能指回主仓库）。
#>
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [string]$SourceDir = "",          # 项目根目录，默认是本脚本所在仓库；可指向某个历史版本的 git worktree
    [string]$OutRoot = "D:\Release",
    [string]$Iscc = "",               # ISCC.exe 路径，默认自动查找（D:\tools\InnoSetup 优先）
    [switch]$SkipPortableBuild,       # 复用 backend\dist\QuizForge-Portable（例如刚由 publish-release.ps1 构建并发布的那份）
    [switch]$SkipFrontend,            # 前端已生成时跳过 pnpm generate
    [switch]$Force                    # 输出目录已存在时覆盖（会删除旧的 v<ver> 目录）
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
if (Test-Path "D:\tools\uv\bin") { $env:Path = "D:\tools\uv\bin;$env:Path" }

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Run($exe, [string[]]$argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { throw "$exe $($argv -join ' ') 失败 (exit $LASTEXITCODE)" }
}

if (-not $SourceDir) { $SourceDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path }
$SourceDir = (Resolve-Path $SourceDir).Path
$Backend = Join-Path $SourceDir "backend"
$Frontend = Join-Path $SourceDir "frontend"
$Dist = Join-Path $Backend "dist"
$Out = Join-Path $OutRoot "v$Version"

# 1. 版本号必须和源码一致，避免打出“名不副实”的包
$verFile = Get-Content (Join-Path $Backend "app\_version.py") -Raw
if ($verFile -notmatch '__version__\s*=\s*"([^"]+)"') { throw "无法解析 _version.py" }
if ($Matches[1] -ne $Version) { throw "源码版本为 $($Matches[1])，与 -Version $Version 不一致（$SourceDir）" }

if (-not $Iscc) {
    $Iscc = @("D:\tools\InnoSetup\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Iscc) { $c = Get-Command iscc -ErrorAction SilentlyContinue; if ($c) { $Iscc = $c.Source } }
}
if (-not $Iscc -or -not (Test-Path $Iscc)) { throw "未找到 ISCC.exe（Inno Setup），请安装到 D:\tools\InnoSetup" }

if (Test-Path $Out) {
    if (-not $Force) { throw "$Out 已存在（加 -Force 覆盖）" }
    Remove-Item $Out -Recurse -Force
}

# 2. 便携版（onedir）+ ZIP
$portableZip = Join-Path $Dist "QuizForge-Portable-$Version.zip"
if ($SkipPortableBuild) {
    Step "复用已有便携版构建"
    if (-not (Test-Path (Join-Path $Dist "QuizForge-Portable\QuizForge.exe"))) { throw "缺少 $Dist\QuizForge-Portable" }
    if (-not (Test-Path $portableZip)) {
        Push-Location $Backend; try { Run "uv" @("run", "python", "scripts/package_portable.py") } finally { Pop-Location }
    }
} else {
    Step "构建便携版"
    $bp = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $SourceDir "build-portable.ps1"))
    if ($SkipFrontend) { $bp += "-SkipFrontend" }
    Run "powershell" $bp
}
if (-not (Test-Path $portableZip)) { throw "便携版 ZIP 未生成：$portableZip" }

# 3. 单文件桌面版（安装程序的载荷）
Step "构建单文件桌面版 (run.spec)"
if (-not (Test-Path (Join-Path $Frontend ".output\public\index.html"))) {
    Push-Location $Frontend; try { Run "pnpm" @("install"); Run "pnpm" @("generate") } finally { Pop-Location }
}
Push-Location $Backend
try { Run "uv" @("run", "--with", "pyinstaller", "pyinstaller", "run.spec", "--clean", "--noconfirm") } finally { Pop-Location }
$desktopExe = Join-Path $Dist "QuizForge.exe"
if (-not (Test-Path $desktopExe)) { throw "单文件桌面版未生成：$desktopExe" }

# 4. Inno Setup 安装程序
Step "编译安装程序 (Inno Setup)"
$payload = Join-Path $Backend "build\release-payload"
if (Test-Path $payload) { Remove-Item $payload -Recurse -Force }
New-Item -ItemType Directory -Force $payload, $Out | Out-Null
Copy-Item $desktopExe (Join-Path $payload "QuizForge.exe")
$readme = Join-Path $Backend "deploy\windows\README.txt"
if (Test-Path $readme) { Copy-Item $readme $payload }
Run $Iscc @("/Q", "/DMyAppVersion=$Version", "/DPayloadDir=$payload", "/O$Out", (Join-Path $Backend "deploy\windows\installer.iss"))
if (-not (Test-Path (Join-Path $Out "QuizForge-Setup-$Version.exe"))) { throw "安装程序未生成" }

# 5. 便携版 / Lite 压缩包
Step "复制压缩包"
Copy-Item $portableZip (Join-Path $Out "QuizForge-Portable-$Version.zip")
Copy-Item $portableZip (Join-Path $Out "QuizForge-Lite-$Version.zip")

# 6. 发布说明（git log：从上一次改动版本号的提交之后到 HEAD）
Step "生成发布说明"
$head = (& git -C $SourceDir rev-parse --short HEAD).Trim()
$prev = $null
$ErrorActionPreference = "Continue"
foreach ($c in (& git -C $SourceDir log --format=%H -- backend/app/_version.py)) {
    $v = (& git -C $SourceDir show "${c}:backend/app/_version.py" 2>$null) -join "`n"
    if ($v -match '__version__\s*=\s*"([^"]+)"' -and $Matches[1] -ne $Version) { $prev = $c; $prevVer = $Matches[1]; break }
}
$ErrorActionPreference = "Stop"
$range = if ($prev) { "$prev..HEAD" } else { "HEAD" }
$log = @(& git -C $SourceDir log --no-merges --format="- %s（%h，%ad）" --date=short $range | Select-Object -First 80)
$notes = @(
    "# 百炼 QuizForge v$Version",
    "",
    "- 构建时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm')（UTC+8）",
    "- 源码提交：$head",
    $(if ($prev) { "- 变更范围：v$prevVer 之后（$($prev.Substring(0,7))..$head）" } else { "- 变更范围：全部历史" }),
    "",
    "## 文件说明",
    "",
    "| 文件 | 用途 |",
    "| --- | --- |",
    "| QuizForge-Setup-$Version.exe | 安装程序：双击安装到 Program Files，可选开机自启、桌面快捷方式 |",
    "| QuizForge-Portable-$Version.zip | 便携版：解压后运行 QuizForge-Portable\QuizForge.exe，支持在线热更新 |",
    "| QuizForge-Lite-$Version.zip | 轻量版：与便携版内容相同（沿用旧的 Lite 命名） |",
    "| SHA256SUMS.txt | 校验值，可用 ``Get-FileHash 文件名`` 核对 |",
    "",
    "## 更新内容",
    ""
) + $log
[IO.File]::WriteAllText((Join-Path $Out "发布说明.md"), ($notes -join "`r`n") + "`r`n", (New-Object Text.UTF8Encoding $false))

# 7. 校验值
Step "计算 SHA256"
$sums = Get-ChildItem $Out -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" } | Sort-Object Name |
    ForEach-Object { "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name }
[IO.File]::WriteAllText((Join-Path $Out "SHA256SUMS.txt"), ($sums -join "`n") + "`n", (New-Object Text.UTF8Encoding $false))

Write-Host "`n发布包已生成：$Out" -ForegroundColor Green
Get-ChildItem $Out | ForEach-Object { Write-Host ("  {0,-36} {1,10:N1} MB" -f $_.Name, ($_.Length / 1MB)) }