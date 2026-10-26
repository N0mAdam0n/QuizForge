# QuizForge portable update installer (standalone).
# Usage:  powershell -ExecutionPolicy Bypass -File installer.ps1 -ParamsFile <json>
#    or:  pass the parameters directly.
param(
    [string]$ParamsFile = "",
    [string]$InstallDir,
    [string]$StagingDir,
    [string]$BackupDir,
    [int[]]$WaitPids = @(),
    [string]$OldVersion,
    [string]$NewVersion,
    [string]$HealthUrl,
    [int]$WaitTimeoutSec = 60,
    [int]$HealthTimeoutSec = 90,
    [string]$LogPath,
    [string]$StatePath,
    [string]$ExeName = "QuizForge.exe",
    [string[]]$Names = @("QuizForge.exe", "_internal", "portable.mode", "README.txt"),
    [string]$DatabasePath = "",
    [string]$DatabaseBackup = "",
    [string[]]$LaunchArgs = @(),
    [switch]$NoSelfDelete
)

$ErrorActionPreference = "Stop"

if ($ParamsFile) {
    $p = Get-Content -LiteralPath $ParamsFile -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($prop in $p.PSObject.Properties) {
        $v = $prop.Value
        if ($v -is [System.Array]) { $v = @($v) }
        Set-Variable -Name $prop.Name -Value $v -Scope Script
    }
}

# Never touch user data, whatever the caller passes.
$Protected = @("data", "updates")
$Names = @($Names | Where-Object { $_ -and ($Protected -notcontains $_.ToLowerInvariant()) })

function Move-Atomic([string]$src, [string]$dst) {
    # Same-volume rename: either fully succeeds or leaves nothing behind
    # (Move-Item on a directory can fall back to a partial per-file move).
    if (Test-Path -LiteralPath $dst) { throw "destination already exists: $dst" }
    if ([IO.Directory]::Exists($src)) { [IO.Directory]::Move($src, $dst) }
    else { [IO.File]::Move($src, $dst) }
}

function Log([string]$msg) {
    $msg = ($msg -replace '\s+$', '') -replace "[\r\n]+", ' '
    $line = "$(Get-Date -Format o) $msg"
    for ($i = 0; $i -lt 5; $i++) {
        try { Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8; return } catch { Start-Sleep -Milliseconds 200 }
    }
}

function Write-State([hashtable]$s) {
    try {
        $tmp = "$StatePath.tmp"
        $s | ConvertTo-Json | Set-Content -LiteralPath $tmp -Encoding UTF8
        Move-Item -LiteralPath $tmp -Destination $StatePath -Force
    } catch { Log "WARN could not write state: $($_.Exception.Message)" }
}

function Get-InstallProcs {
    $root = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\') + '\'
    $exe = [IO.Path]::GetFileNameWithoutExtension($ExeName)
    @(Get-Process -Name $exe -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -and $_.Path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) } catch { $false }
    })
}

function Wait-AppExit([int]$timeoutSec, [int[]]$pids) {
    $deadline = [DateTime]::UtcNow.AddSeconds($timeoutSec)
    while ([DateTime]::UtcNow -lt $deadline) {
        $alive = @($pids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
        $procs = Get-InstallProcs
        if ($alive.Count -eq 0 -and $procs.Count -eq 0) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Stop-AppHard([int[]]$pids) {
    $all = @($pids) + @(Get-InstallProcs | ForEach-Object { $_.Id })
    foreach ($id in ($all | Select-Object -Unique)) {
        if (Get-Process -Id $id -ErrorAction SilentlyContinue) {
            Log "taskkill /T /F pid $id"
            & "$env:SystemRoot\System32\taskkill.exe" /PID $id /T /F 2>&1 | Out-Null
        }
    }
    $ok = Wait-AppExit 30 $pids
    if (-not $ok) { Log "WARN processes still alive after kill: $((Get-InstallProcs | ForEach-Object Id) -join ',')" }
    return $ok
}

function Retry([string]$what, [scriptblock]$action, [int]$tries = 20, [int]$delayMs = 500) {
    for ($i = 1; $i -le $tries; $i++) {
        try { & $action; return } catch {
            if ($i -eq $tries) { Log "FAIL $what after $tries tries: $($_.Exception.Message)"; throw }
            if ($i -eq 1 -or $i % 5 -eq 0) { Log "retry $i/$tries $what : $($_.Exception.Message)" }
            Start-Sleep -Milliseconds $delayMs
        }
    }
}

$state = @{ status = "pending"; previous_version = $OldVersion; latest_version = $NewVersion; backup_dir = $BackupDir }
$backedUp = New-Object System.Collections.Generic.List[string]
$installed = New-Object System.Collections.Generic.List[string]
$newProc = $null
$exitCode = 0

try {
    Log "installer started (pid $PID) $OldVersion -> $NewVersion; waiting for pids [$($WaitPids -join ',')] and app processes under $InstallDir"
    Write-State $state
    if (-not (Wait-AppExit $WaitTimeoutSec $WaitPids)) {
        Log "old app did not exit within ${WaitTimeoutSec}s; aborting without changes (alive: $((Get-InstallProcs | ForEach-Object Id) -join ','))"
        $state.status = "failed"; $state.error = "old process did not exit in time"
        Write-State $state
        $exitCode = 10
        exit 10
    }
    Log "old app exited"

    $programBackup = Join-Path $BackupDir "program"
    New-Item -ItemType Directory -Path $programBackup -Force | Out-Null
    foreach ($name in $Names) {
        if (-not (Test-Path -LiteralPath (Join-Path $StagingDir $name))) {
            if ($name -eq "README.txt") { continue }
            throw "staging is missing $name"
        }
    }

    $state.status = "installing"; Write-State $state
    try {
        foreach ($name in $Names) {
            $source = Join-Path $StagingDir $name
            if (-not (Test-Path -LiteralPath $source)) { continue }
            $dest = Join-Path $InstallDir $name
            $saved = Join-Path $programBackup $name
            if (Test-Path -LiteralPath $dest) {
                Retry "backup $name" { Move-Atomic $dest $saved }
                $backedUp.Add($name)
                Log "backed up $name"
            }
            $installed.Add($name)   # mark before trying: rollback clears anything at $dest
            Retry "install $name" { Move-Atomic $source $dest }
            Log "installed $name"
        }

        $exe = Join-Path $InstallDir $ExeName
        Log "launching $exe $($LaunchArgs -join ' ')"
        if ($LaunchArgs.Count -gt 0) {
            $newProc = Start-Process -FilePath $exe -ArgumentList $LaunchArgs -WorkingDirectory $InstallDir -PassThru
        } else {
            $newProc = Start-Process -FilePath $exe -WorkingDirectory $InstallDir -PassThru
        }
        Log "new app pid $($newProc.Id); polling $HealthUrl for ${HealthTimeoutSec}s"

        $healthy = $false; $last = "no response"
        $deadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSec)
        while ([DateTime]::UtcNow -lt $deadline) {
            try {
                $h = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3
                $last = ($h | ConvertTo-Json -Compress)
                $configured = $true
                if ($h.PSObject.Properties.Name -contains "configured") { $configured = [bool]$h.configured }
                if ($h.version -eq $NewVersion -and ($h.migrations_ok -eq $true -or -not $configured)) { $healthy = $true; break }
            } catch { $last = "error: $($_.Exception.Message)" }
            if ($newProc.HasExited -and -not (Get-InstallProcs)) { $last = "new app exited with code $($newProc.ExitCode); last: $last"; break }
            Start-Sleep -Seconds 1
        }
        if (-not $healthy) {
            Log "health check failed; last response: $last"
            throw "New version did not pass its health check ($last)"
        }
        Log "health ok: $last"
        $state.status = "succeeded"; Write-State $state
        Log "update succeeded"
    } catch {
        $err = $_.Exception.Message
        Log "ERROR $err; rolling back"
        $state.status = "rolling_back"; $state.error = $err.Trim(); Write-State $state
        $rollbackOk = $true
        try {
            [void](Stop-AppHard @(if ($newProc) { $newProc.Id }))
            foreach ($name in $Names) {
                if (-not ($installed.Contains($name) -or $backedUp.Contains($name))) { continue }
                $dest = Join-Path $InstallDir $name
                $saved = Join-Path $programBackup $name
                try {
                    if ($installed.Contains($name) -and (Test-Path -LiteralPath $dest)) {
                        Retry "remove new $name" { Remove-Item -LiteralPath $dest -Recurse -Force }
                    }
                    if ($backedUp.Contains($name) -and (Test-Path -LiteralPath $saved)) {
                        Retry "restore $name" { Move-Atomic $saved $dest }
                        Log "restored $name"
                    }
                } catch { $rollbackOk = $false; Log "ERROR restoring ${name}: $($_.Exception.Message)" }
            }
            if ($DatabaseBackup -and $DatabasePath -and (Test-Path -LiteralPath $DatabaseBackup)) {
                try {
                    Remove-Item -LiteralPath ($DatabasePath + "-wal"), ($DatabasePath + "-shm") -Force -ErrorAction SilentlyContinue
                    Retry "restore database" { Copy-Item -LiteralPath $DatabaseBackup -Destination $DatabasePath -Force }
                    Log "database restored"
                } catch { $rollbackOk = $false; Log "ERROR restoring database: $($_.Exception.Message)" }
            }
        } catch { $rollbackOk = $false; Log "ERROR during rollback: $($_.Exception.Message)" }
        finally {
            $state.status = if ($rollbackOk) { "rolled_back" } else { "rollback_failed" }
            Write-State $state
            Log "rollback finished: $($state.status)"
        }
        $oldExe = Join-Path $InstallDir $ExeName
        if (Test-Path -LiteralPath $oldExe) {
            try {
                Start-Process -FilePath $oldExe -ArgumentList @("--post-update-failed", $NewVersion) -WorkingDirectory $InstallDir | Out-Null
                Log "relaunched old version"
            } catch { Log "ERROR relaunching old version: $($_.Exception.Message)" }
        }
        $exitCode = 11
    }
} catch {
    Log "FATAL $($_.Exception.Message)"
    $state.status = "failed"; $state.error = $_.Exception.Message; Write-State $state
    $exitCode = 12
} finally {
    Log "installer finished (exit $exitCode)"
    if (-not $NoSelfDelete) {
        if ($ParamsFile) { Remove-Item -LiteralPath $ParamsFile -Force -ErrorAction SilentlyContinue }
        Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
    }
}
exit $exitCode
