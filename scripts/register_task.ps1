param (
    [string]$AppDir
)
if (-not $AppDir) {
    $AppDir = Split-Path -Parent $PSScriptRoot
}
$supExe = Join-Path $AppDir "iHRMS-Supervisor.exe"
if (Test-Path $supExe) {
    $action = New-ScheduledTaskAction -Execute $supExe -Argument '--startup' -WorkingDirectory $AppDir
    $tLogon = New-ScheduledTaskTrigger -AtLogOn
    $tRep = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 0)
    $taskName = "iHRMSDesktopAutoRestart-$env:USERNAME"
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($tLogon, $tRep) -Settings $settings -Force
}
