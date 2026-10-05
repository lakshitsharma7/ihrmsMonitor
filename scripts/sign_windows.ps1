<#
.SYNOPSIS
    Authenticode Code Signing Script for Windows Executables and Installers.

.DESCRIPTION
    Signs Windows binaries (.exe, .dll) and installers using signtool.exe with SHA-256
    and RFC 3161 timestamping. Supports PFX files from environment variables/secrets
    or Windows Certificate Store.

.PARAMETER Target
    Path to the executable or installer file(s) to sign.

.PARAMETER CertBase64
    Optional Base64-encoded PFX certificate data. Defaults to $env:WINDOWS_CERTIFICATE_BASE64 or $env:WINDOWS_CERTIFICATE.

.PARAMETER CertPath
    Optional path to a .pfx / .p12 certificate file. Defaults to $env:WINDOWS_CERTIFICATE_PATH.

.PARAMETER CertPassword
    Optional certificate password. Defaults to $env:WINDOWS_CERTIFICATE_PASSWORD.

.PARAMETER CertThumbprint
    Optional SHA-1 thumbprint for certificate located in the Windows Certificate Store. Defaults to $env:WINDOWS_CERT_THUMBPRINT.
#>

[CmdletBinding()]
param (
    [Parameter(Mandatory = $true, Position = 0, ValueFromPipeline = $true)]
    [string[]]$Target,

    [Parameter(Mandatory = $false)]
    [string]$CertBase64 = "",

    [Parameter(Mandatory = $false)]
    [string]$CertPath = "",

    [Parameter(Mandatory = $false)]
    [string]$CertPassword = "",

    [Parameter(Mandatory = $false)]
    [string]$CertThumbprint = "",

    [Parameter(Mandatory = $false)]
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Fallback timestamp servers in case primary is temporarily rate-limited / unreachable
$TimestampServers = @(
    $TimestampUrl,
    "http://timestamp.digicert.com",
    "http://timestamp.sectigo.com",
    "http://tsa.starfieldtech.com",
    "http://timestamp.comodoca.com"
) | Select-Object -Unique

function Find-SignTool {
    # Check PATH first
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    # Search Windows SDK installation directories
    $sdkRoots = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
        "${env:ProgramFiles}\Windows Kits\10\bin",
        "${env:ProgramFiles(x86)}\Windows Kits\8.1\bin",
        "${env:ProgramFiles}\Windows Kits\8.1\bin",
        "${env:ProgramFiles(x86)}\Microsoft SDKs\Windows"
    )

    foreach ($root in $sdkRoots) {
        if (Test-Path $root) {
            $found = Get-ChildItem -Path $root -Filter "signtool.exe" -Recurse -File -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match "x64|x86" } |
                Sort-Object FullName -Descending |
                Select-Object -First 1

            if ($found) {
                return $found.FullName
            }
        }
    }

    return $null
}

# Resolve Certificate Settings from Arguments or Environment Variables
if (-not $CertBase64) {
    if ($env:WINDOWS_CERTIFICATE_BASE64) {
        $CertBase64 = $env:WINDOWS_CERTIFICATE_BASE64
    } elseif ($env:WINDOWS_CERTIFICATE) {
        $CertBase64 = $env:WINDOWS_CERTIFICATE
    }
}

if (-not $CertPath -and $env:WINDOWS_CERTIFICATE_PATH) {
    $CertPath = $env:WINDOWS_CERTIFICATE_PATH
}

if (-not $CertPassword -and $env:WINDOWS_CERTIFICATE_PASSWORD) {
    $CertPassword = $env:WINDOWS_CERTIFICATE_PASSWORD
}

if (-not $CertThumbprint -and $env:WINDOWS_CERT_THUMBPRINT) {
    $CertThumbprint = $env:WINDOWS_CERT_THUMBPRINT
}

$SignToolPath = Find-SignTool

if (-not $SignToolPath) {
    Write-Warning "signtool.exe was not found on this system. Please install Windows SDK or Visual Studio Build Tools."
    if ($env:CI -or $env:GITHUB_ACTIONS) {
        throw "Build failed: signtool.exe is required in CI environment."
    }
    return
}

Write-Host "Using signtool: $SignToolPath"

# Prepare temporary PFX file if provided via Base64
$tempCertPath = $null
$effectiveCertPath = $null

try {
    if ($CertBase64) {
        $tempCertPath = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "workpulse_cert_$([System.Guid]::NewGuid().ToString('N')).pfx")
        $certBytes = [System.Convert]::FromBase64String($CertBase64.Trim())
        [System.IO.File]::WriteAllBytes($tempCertPath, $certBytes)
        $effectiveCertPath = $tempCertPath
    } elseif ($CertPath -and (Test-Path $CertPath)) {
        $effectiveCertPath = (Resolve-Path $CertPath).Path
    }

    if (-not $effectiveCertPath -and -not $CertThumbprint) {
        Write-Warning "No Windows Authenticode certificate configured (WINDOWS_CERTIFICATE_BASE64 / WINDOWS_CERTIFICATE_PATH / WINDOWS_CERT_THUMBPRINT)."
        Write-Warning "Skipping code signing for local unsigned build. For official releases, configure valid certificate secrets."
        if ($env:REQUIRE_SIGNING -eq "1" -or ($env:CI -eq "true" -and $env:RELEASE_BUILD -eq "1")) {
            throw "Official release build requires valid Windows Authenticode certificate."
        }
        return
    }

    foreach ($file in $Target) {
        if (-not (Test-Path $file)) {
            throw "Target file to sign does not exist: $file"
        }

        $resolvedTarget = (Resolve-Path $file).Path
        Write-Host "Signing $resolvedTarget with SHA-256 Authenticode signature..."

        $signedSuccessfully = $false
        $lastError = ""

        foreach ($ts in $TimestampServers) {
            Write-Host "  -> Attempting timestamp server: $ts"
            
            $signArgs = @("sign", "/fd", "SHA256", "/tr", $ts, "/td", "SHA256", "/v")

            if ($effectiveCertPath) {
                $signArgs += @("/f", $effectiveCertPath)
                if ($CertPassword) {
                    $signArgs += @("/p", $CertPassword)
                }
            } elseif ($CertThumbprint) {
                $signArgs += @("/sha1", $CertThumbprint, "/sm")
            }

            $signArgs += $resolvedTarget

            $proc = Start-Process -FilePath $SignToolPath -ArgumentList $signArgs -NoNewWindow -Wait -PassThru

            if ($proc.ExitCode -eq 0) {
                $signedSuccessfully = $true
                Write-Host "  [OK] Successfully signed and timestamped using $ts"
                break
            } else {
                $lastError = "signtool exited with code $($proc.ExitCode)"
                Write-Warning "  Timestamp attempt failed with $ts, trying fallback server..."
            }
        }

        if (-not $signedSuccessfully) {
            throw "Failed to sign $resolvedTarget. $lastError"
        }

        # Verify signature integrity
        Write-Host "Verifying signature for $resolvedTarget..."
        $verifyProc = Start-Process -FilePath $SignToolPath -ArgumentList @("verify", "/pa", "/v", $resolvedTarget) -NoNewWindow -Wait -PassThru
        if ($verifyProc.ExitCode -ne 0) {
            throw "Signature verification failed for $resolvedTarget (signtool verify exit code: $($verifyProc.ExitCode))"
        }

        $sig = Get-AuthenticodeSignature -FilePath $resolvedTarget
        Write-Host "Authenticode Status: $($sig.Status) | Signer: $($sig.SignerCertificate.Subject)"

        if ($sig.Status -ne "Valid") {
            throw "Authenticode signature status is '$($sig.Status)' (Expected: Valid) for $resolvedTarget"
        }
    }
}
finally {
    # Ensure temporary decrypted certificate file is securely deleted from disk
    if ($tempCertPath -and (Test-Path $tempCertPath)) {
        Remove-Item -Path $tempCertPath -Force -ErrorAction SilentlyContinue
    }
}
