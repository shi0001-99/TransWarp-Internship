# stock-monitor control script (Windows PowerShell)
param(
    [ValidateSet('start', 'stop', 'status', 'logs', 'alerts', 'restart', 'run')]
    [string]$Action = 'status'
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = "$env:USERPROFILE\.stock_monitor"
$PidFile = "$LogDir\monitor.pid"
$LogFile = "$LogDir\monitor.log"
$AlertFile = "$LogDir\alerts.log"
$PythonExe = "python"

function Get-MonitorPid {
    if (Test-Path $PidFile) {
        return (Get-Content $PidFile -Raw).Trim()
    }
    return $null
}

function Get-ProcessStatus {
    $monPid = Get-MonitorPid
    if (-not $monPid) { return @{ Running = $false; Pid = $null } }
    try {
        $proc = Get-Process -Id $monPid -ErrorAction Stop
        return @{ Running = $true; Pid = $monPid; Process = $proc }
    } catch {
        return @{ Running = $false; Pid = $monPid }
    }
}

function Write-Banner {
    param([string]$Text)
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
}

switch ($Action) {
    'start' {
        Write-Banner "Start stock monitor daemon"
        $status = Get-ProcessStatus
        if ($status.Running) {
            Write-Host "Monitor already running (PID: $($status.Pid))" -ForegroundColor Yellow
            break
        }
        if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
        $proc = Start-Process -FilePath $PythonExe -ArgumentList "$ScriptDir\monitor_daemon.py" -WindowStyle Hidden -PassThru
        Start-Sleep -Seconds 2
        if ($proc -and ! $proc.HasExited) {
            $proc.Id | Out-File -FilePath $PidFile -Encoding ascii
            Write-Host "Monitor started (PID: $($proc.Id))" -ForegroundColor Green
            Write-Host "Log file: $LogFile"
            Write-Host "Alert log: $AlertFile"
        } else {
            Write-Host "Start failed, check logs" -ForegroundColor Red
        }
    }

    'stop' {
        Write-Banner "Stop stock monitor"
        $status = Get-ProcessStatus
        if (-not $status.Running) {
            Write-Host "Monitor not running" -ForegroundColor Yellow
            if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
            break
        }
        try {
            Stop-Process -Id $status.Pid -Force -ErrorAction Stop
            Write-Host "Stopped PID: $($status.Pid)" -ForegroundColor Green
        } catch {
            Write-Host "Stop failed: $_" -ForegroundColor Red
        }
        if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
    }

    'status' {
        Write-Banner "Stock monitor status"
        $status = Get-ProcessStatus
        if ($status.Running) {
            Write-Host "Status: Running" -ForegroundColor Green
            Write-Host "PID: $($status.Pid)"
            Write-Host "Process: $($status.Process.ProcessName)"
        } else {
            Write-Host "Status: Stopped" -ForegroundColor Yellow
            if ($status.Pid) {
                Write-Host "(Stale PID: $($status.Pid) - cleaned)" -ForegroundColor DarkGray
                if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
            }
        }
        Write-Host ""
        Write-Host "Log file: $LogFile"
        Write-Host "Alert log: $AlertFile"
        if (Test-Path $LogFile) {
            $logSize = [math]::Round((Get-Item $LogFile).Length / 1KB, 1)
            Write-Host "Log size: $logSize KB"
        }
    }

    'logs' {
        Write-Banner "Recent logs"
        if (Test-Path $LogFile) {
            Get-Content $LogFile -Tail 50
        } else {
            Write-Host "No logs" -ForegroundColor Yellow
        }
    }

    'alerts' {
        Write-Banner "Recent alerts"
        if (Test-Path $AlertFile) {
            Get-Content $AlertFile -Tail 50
        } else {
            Write-Host "No alerts" -ForegroundColor Yellow
        }
    }

    'restart' {
        Write-Banner "Restart stock monitor"
        $status = Get-ProcessStatus
        if ($status.Running) {
            Write-Host "Stopping old process..." -ForegroundColor Yellow
            try { Stop-Process -Id $status.Pid -Force -ErrorAction Stop; Start-Sleep -Seconds 1 } catch {}
        }
        if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
        & "$PSCommandPath" start
    }

    'run' {
        Write-Banner "Foreground run"
        $status = Get-ProcessStatus
        if ($status.Running) {
            Write-Host "Monitor already running (PID: $($status.Pid))" -ForegroundColor Yellow
            break
        }
        if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
        & $PythonExe "$ScriptDir\monitor_daemon.py"
    }
}