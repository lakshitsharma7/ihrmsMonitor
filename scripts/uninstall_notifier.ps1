# iHRMS Monitor - Standalone Uninstall Notifier & Offline Delivery Script
# Executed during application uninstall or triggered by Scheduled Task when internet becomes available.

[CmdletBinding()]
param(
    [switch]$ProcessPendingOnly
)

$appName = "iHRMS Monitor"
$localAppData = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::LocalApplicationData)
$appDataDir = Join-Path $localAppData $appName
$pendingFile = Join-Path $appDataDir "pending_uninstall.json"
$taskName = "iHRMS_Monitor_Uninstall_Notifier"
$supportEmail = "support-hrms@indovisionservices.in"
$defaultBaseUrl = "https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api"

function Write-Log {
    param([string]$Message)
    $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    Write-Host "[$ts] $Message"
}

# 1. Collect / Load Context
$payload = $null

if (Test-Path $pendingFile) {
    try {
        $jsonContent = Get-Content -Path $pendingFile -Raw -Encoding UTF8
        $payload = ConvertFrom-Json $jsonContent
        Write-Log "Loaded pending uninstall payload from $pendingFile"
    } catch {
        Write-Log "Failed to parse $pendingFile"
    }
}

if ($null -eq $payload -and -not $ProcessPendingOnly) {
    # Dynamically build context if uninstaller called directly without pre-created file
    $hostname = $env:COMPUTERNAME
    $username = $env:USERNAME
    $osName = (Get-CimInstance Win32_OperatingSystem).Caption
    $osVersion = (Get-CimInstance Win32_OperatingSystem).Version
    $nowUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $nowLocal = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")

    # Resolve Machine GUID
    $devId = "Unknown-Device"
    try {
        $regGuid = (Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Cryptography" -Name "MachineGuid" -ErrorAction SilentlyContinue).MachineGuid
        if ($regGuid) { $devId = $regGuid }
    } catch {}

    # Extract user details from registry if available
    $empId = "N/A"
    $compCode = "N/A"
    $regUser = $username
    try {
        $regRoot = Get-ItemProperty -Path "HKCU:\Software\Indovision\iHRMSMonitor" -ErrorAction SilentlyContinue
        if ($regRoot) {
            if ($regRoot."session\employee_id") { $empId = $regRoot."session\employee_id" }
            elseif ($regRoot.last_employee_id) { $empId = $regRoot.last_employee_id }

            if ($regRoot."session\company_code") { $compCode = $regRoot."session\company_code" }
            elseif ($regRoot.last_company_code) { $compCode = $regRoot.last_company_code }

            if ($regRoot."session\username") { $regUser = $regRoot."session\username" }
            elseif ($regRoot.last_username) { $regUser = $regRoot.last_username }

            if ($regRoot."session\base_url") { $defaultBaseUrl = $regRoot."session\base_url" }
        }
    } catch {}

    # Dynamically resolve app version
    $appVer = "2.0.1"
    try {
        $exePath = Join-Path $PSScriptRoot "..\iHRMS Monitor.exe"
        if (Test-Path $exePath) {
            $verInfo = (Get-Item $exePath).VersionInfo.ProductVersion
            if ($verInfo) { $appVer = $verInfo.Trim() }
        }
    } catch {}

    $arch = if ($env:PROCESSOR_ARCHITECTURE) { $env:PROCESSOR_ARCHITECTURE } else { "AMD64" }

    $payload = [PSCustomObject]@{
        event_type = "APPLICATION_UNINSTALLED"
        app_name = $appName
        app_version = $appVer
        employee_id = $empId
        username = $regUser
        company_code = $compCode
        device_id = $devId
        hostname = $hostname
        os_user = $username
        os = "$osName ($osVersion)"
        platform = "Windows"
        architecture = $arch
        uninstall_time_local = $nowLocal
        uninstall_time_utc = $nowUtc
    }

    # Save to pending file
    if (-not (Test-Path $appDataDir)) {
        New-Item -ItemType Directory -Path $appDataDir -Force | Out-Null
    }
    $payload | ConvertTo-Json -Depth 5 | Set-Content -Path $pendingFile -Encoding UTF8 -Force
}

if ($null -eq $payload) {
    Write-Log "No pending uninstall report to process. Exiting."
    exit 0
}

# 2. Test Connection and Deliver to Backend
$targetUrl = "$defaultBaseUrl/tracking/report_error"
$delivered = $false

$errorMsg = "iHRMS Monitor UNINSTALLED by user '$($payload.username)' (Employee ID: $($payload.employee_id), Company: $($payload.company_code)) on device '$($payload.hostname)' ($($payload.device_id)) running $($payload.os)."

$bodyData = @{
    support_email = $supportEmail
    from_address = "noreply-ihrms@indovisionservices.in"
    app_name = $appName
    app_version = "$($payload.app_version)"
    error_type = "APPLICATION_UNINSTALLED"
    error_message = $errorMsg
    timestamp_local = "$($payload.uninstall_time_local)"
    timestamp_utc = "$($payload.uninstall_time_utc)"
    user_details = (@{
        username = "$($payload.username)"
        employee_id = "$($payload.employee_id)"
        company_code = "$($payload.company_code)"
    } | ConvertTo-Json -Compress)
    device_details = (@{
        device_id = "$($payload.device_id)"
        hostname = "$($payload.hostname)"
        os = "$($payload.os)"
        installed_version = "$($payload.app_version)"
        uninstall_time = "$($payload.uninstall_time_utc)"
    } | ConvertTo-Json -Compress)
    operation = "Application Uninstallation"
}

try {
    Write-Log "Attempting to POST uninstall report to $targetUrl..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $response = Invoke-WebRequest -Uri $targetUrl -Method Post -Body $bodyData -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
    $delivered = $true
    Write-Log "Uninstall report successfully accepted by backend."
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -lt 500) {
        Write-Log "Backend server reached (HTTP $([int]$_.Exception.Response.StatusCode)). Report delivered."
        $delivered = $true
    } else {
        Write-Log "Backend report delivery failed or offline: $_"
        $delivered = $false
    }
}

# 3. Handle Delivery Outcome
if ($delivered) {
    # Remove pending queue file to guarantee EXACTLY ONE email
    if (Test-Path $pendingFile) {
        Remove-Item -Path $pendingFile -Force -ErrorAction SilentlyContinue
    }
    # Unregister scheduled task if present
    try {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    } catch {}
    Write-Log "Uninstall reporting complete. Cleanup successful."
    exit 0
} else {
    # Ensure background scheduled task is registered to retry when internet is back
    Write-Log "Internet is unavailable. Scheduling background retry task..."
    try {
        $scriptPath = $MyInvocation.MyCommand.Path
        if (-not $scriptPath) {
            $scriptPath = Join-Path $PSScriptRoot "uninstall_notifier.ps1"
        }
        
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -ProcessPendingOnly"
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 7)
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
        
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force -ErrorAction SilentlyContinue | Out-Null
        Write-Log "Background retry task registered successfully."
    } catch {
        Write-Log "Could not register scheduled task: $_"
    }
    exit 1
}
