# 配置开机自启动（apmm版本）

Write-Host "配置 Agent Daemon 开机自启动..." -ForegroundColor Green

# 任务计划参数
$taskName = "AgentDaemon-apmm"
$pythonPath = "pythonw.exe"
$scriptPath = "D:\workspace\apmm\.agents\daemon\agent_daemon.py"
$workDir = "D:\workspace\apmm\.agents\daemon"

# 检查是否已存在
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($existingTask) {
    Write-Host "任务已存在，正在更新..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# 创建任务
$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument $scriptPath `
    -WorkingDirectory $workDir

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Multi-Agent System Daemon (apmm)" `
    -Force

Write-Host "✓ 已配置开机自启动" -ForegroundColor Green

# 测试运行
Write-Host "`n是否立即测试运行？" -ForegroundColor Cyan
$test = Read-Host "输入 'y' 立即启动"

if ($test -eq 'y') {
    Start-ScheduledTask -TaskName $taskName
    Start-Sleep -Seconds 3
    
    $running = Get-Process | Where-Object { $_.ProcessName -eq "pythonw" -and $_.CommandLine -like "*agent_daemon.py*" }
    if ($running) {
        Write-Host "✓ 测试启动成功 (PID: $($running.Id))" -ForegroundColor Green
    } else {
        Write-Host "✗ 测试启动失败，请检查日志" -ForegroundColor Red
    }
}

Write-Host "`n管理命令:" -ForegroundColor Cyan
Write-Host "  启动: Start-ScheduledTask -TaskName $taskName"
Write-Host "  停止: Stop-ScheduledTask -TaskName $taskName"
Write-Host "  状态: Get-ScheduledTask -TaskName $taskName"
Write-Host "  删除: Unregister-ScheduledTask -TaskName $taskName"