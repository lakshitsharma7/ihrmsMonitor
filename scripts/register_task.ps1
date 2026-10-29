param (
    [string]$AppDir
)
if (-not $AppDir) {
    $AppDir = Split-Path -Parent $PSScriptRoot
}
$supExe = Join-Path $AppDir "iHRMS-Supervisor.exe"
if (Test-Path $supExe) {
    try {
        $action = New-ScheduledTaskAction -Execute $supExe -Argument '--startup' -WorkingDirectory $AppDir
        $tLogon = New-ScheduledTaskTrigger -AtLogOn
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 0)
        $taskName = "iHRMSDesktopAutoRestart-$env:USERNAME"
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $tLogon -Settings $settings -Force -ErrorAction Stop
    } catch {
        # Task Scheduler registration is restricted for unprivileged users; HKCU Run key handles startup
        Write-Verbose "Scheduled task registration note: $_"
    }
}
