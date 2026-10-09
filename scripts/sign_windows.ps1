<#
.SYNOPSIS
    Authenticode Code Signing Script for Windows Executables and Installers.

.DESCRIPTION
    Signs Windows binaries (.exe, .dll) and installers using Authenticode with SHA-256
    and RFC 3161 timestamping. Supports signtool.exe (primary) and PowerShell
    Set-AuthenticodeSignature (universal fallback). Accepts PFX files from
    CI/CD secrets/environment variables or Windows Certificate Stores.
    Strictly validates whether the certificate is self-signed vs publicly trusted.

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
    [string]$TimestampUrl = "http://timestamp.digicert.com",

    [Parameter(Mandatory = $false)]
    [string]$Description = "iHRMS Desktop",

    [Parameter(Mandatory = $false)]
    [string]$AppUrl = "https://indovisionservices.in",

    [Parameter(Mandatory = $false)]
    [switch]$RequireSigning
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Clean target inputs (strips quotes that may be passed by Inno Setup $f or batch scripts)
$resolvedTargets = @()
foreach ($t in $Target) {
    if ($t) {
        $clean = $t.Trim('"', "'").Trim()
        if ($clean -and (Test-Path $clean)) {
            $resolvedTargets += (Resolve-Path $clean).Path
        } elseif ($clean) {
            Write-Warning "Target path not found: $clean"
        }
    }
}

if ($resolvedTargets.Count -eq 0) {
    Write-Warning "No valid target files provided to sign."
    return
}

# Timestamp servers (RFC 3161 SHA-256) with fallbacks
$TimestampServers = @(
    $TimestampUrl,
    "http://timestamp.digicert.com",
    "http://timestamp.sectigo.com",
    "http://tsa.starfieldtech.com",
    "http://timestamp.comodoca.com"
) | Select-Object -Unique

function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

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

$tempCertPath = $null
$effectiveCertPath = $null
$certObj = $null

try {
    # 1. Base64 Certificate
    if ($CertBase64) {
        $tempCertPath = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "ihrms_cert_$([System.Guid]::NewGuid().ToString('N')).pfx")
        $certBytes = [System.Convert]::FromBase64String($CertBase64.Trim())
        [System.IO.File]::WriteAllBytes($tempCertPath, $certBytes)
        $effectiveCertPath = $tempCertPath

        $certObj = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2
        if ($CertPassword) {
            $certObj.Import($effectiveCertPath, $CertPassword, [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable)
        } else {
            $certObj.Import($effectiveCertPath)
        }
    }
    # 2. File Path Certificate
    elseif ($CertPath -and (Test-Path $CertPath)) {
        $effectiveCertPath = (Resolve-Path $CertPath).Path
        $certObj = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2
        if ($CertPassword) {
            $certObj.Import($effectiveCertPath, $CertPassword, [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable)
        } else {
            $certObj.Import($effectiveCertPath)
        }
    }
    # 3. Store Certificate by Thumbprint
    elseif ($CertThumbprint) {
        $storeCerts = Get-ChildItem Cert:\CurrentUser\My, Cert:\LocalMachine\My -ErrorAction SilentlyContinue |
            Where-Object { $_.Thumbprint -eq $CertThumbprint -and $_.HasPrivateKey }
        if ($storeCerts) {
            $certObj = $storeCerts[0]
        }
    }
    # 4. Auto-discover Code Signing Certificate in Local Stores
    else {
        $discovered = Get-ChildItem Cert:\CurrentUser\My, Cert:\LocalMachine\My -ErrorAction SilentlyContinue |
            Where-Object {
                $_.HasPrivateKey -and
                ($_.EnhancedKeyUsageList | Where-Object { $_.FriendlyName -match 'Code Signing' -or $_.ObjectId.Value -eq '1.3.6.1.5.5.7.3.3' }) -and
                ($_.NotAfter -gt [DateTime]::UtcNow)
            } |
            Sort-Object { if ($_.Subject -match 'Indovision') { 0 } else { 1 } }

        if ($discovered) {
            $certObj = $discovered[0]
            $CertThumbprint = $certObj.Thumbprint
            Write-Host "Auto-discovered local code signing certificate: $($certObj.Subject)"
        }
    }

    if (-not $certObj) {
        Write-Warning "No Windows Authenticode certificate configured or found in certificate stores."
        Write-Warning "Set WINDOWS_CERTIFICATE_BASE64, WINDOWS_CERTIFICATE_PATH, or WINDOWS_CERT_THUMBPRINT to enable signing."
        if ($RequireSigning -or ($env:REQUIRE_SIGNING -eq "1") -or ($env:CI -eq "true" -and $env:RELEASE_BUILD -eq "1")) {
            throw "Production release build requires a valid Windows Authenticode certificate."
        }
        return
    }

    $isSelfSigned = ($certObj.Subject -eq $certObj.Issuer)

    Write-Host "==================================================="
    Write-Host "Authenticode Certificate Details:"
    Write-Host "  Subject:     $($certObj.Subject)"
    Write-Host "  Issuer:      $($certObj.Issuer)"
    Write-Host "  Valid From:  $($certObj.NotBefore)"
    Write-Host "  Valid To:    $($certObj.NotAfter)"
    Write-Host "  Thumbprint:  $($certObj.Thumbprint)"
    Write-Host "  Self-Signed: $isSelfSigned"
    Write-Host "==================================================="

    if ($certObj.NotAfter -lt [DateTime]::UtcNow) {
        throw "Code signing certificate EXPIRED on $($certObj.NotAfter)!"
    }

    if ($isSelfSigned) {
        Write-Warning "=================================================================="
        Write-Warning "WARNING: The detected certificate is SELF-SIGNED (Issuer == Subject)."
        Write-Warning "This certificate will trigger 'Windows protected your PC' / Unknown Publisher"
        Write-Warning "on end-user machines because it is not trusted by the Microsoft Trusted Root Program."
        Write-Warning "For production release, configure WINDOWS_CERTIFICATE_BASE64 with a valid"
        Write-Warning "commercial certificate issued by DigiCert, Sectigo, GlobalSign, Certum, etc."
        Write-Warning "=================================================================="

        if ($env:REQUIRE_VALID_SIGNATURE -eq "1") {
            throw "Production release requires a publicly trusted certificate, but only a self-signed certificate was found."
        }
    }

    $SignToolPath = Find-SignTool
    if ($SignToolPath) {
        Write-Host "Using Windows SDK signtool: $SignToolPath"
    } else {
        Write-Host "signtool.exe not found on PATH/SDK. Using PowerShell native Set-AuthenticodeSignature (universal fallback)."
    }

    foreach ($file in $resolvedTargets) {
        Write-Host "Signing: $file"
        $signedSuccessfully = $false
        $lastError = ""

        foreach ($ts in $TimestampServers) {
            Write-Host "  -> Attempting timestamp server: $ts"

            if ($SignToolPath) {
                # Method A: signtool.exe
                $signArgs = @("sign", "/fd", "SHA256", "/tr", $ts, "/td", "SHA256", "/v")
                if ($Description) { $signArgs += @("/d", $Description) }
                if ($AppUrl) { $signArgs += @("/du", $AppUrl) }

                if ($effectiveCertPath) {
                    $signArgs += @("/f", $effectiveCertPath)
                    if ($CertPassword) { $signArgs += @("/p", $CertPassword) }
                } elseif ($CertThumbprint) {
                    $signArgs += @("/sha1", $CertThumbprint, "/s", "My")
                }

                $signArgs += $file
                $proc = Start-Process -FilePath $SignToolPath -ArgumentList $signArgs -NoNewWindow -Wait -PassThru

                if ($proc.ExitCode -eq 0) {
                    $signedSuccessfully = $true
                    Write-Host "  [OK] Successfully signed using signtool and timestamped via $ts"
                    break
                } else {
                    $lastError = "signtool exited with code $($proc.ExitCode)"
                    Write-Warning "  Timestamp attempt failed with $ts, trying fallback server..."
                }
            } else {
                # Method B: PowerShell Set-AuthenticodeSignature
                try {
                    $sig = Set-AuthenticodeSignature -FilePath $file -Certificate $certObj -TimestampServer $ts -HashAlgorithm SHA256
                    if ($sig -and $sig.SignerCertificate) {
                        $signedSuccessfully = $true
                        Write-Host "  [OK] Successfully signed using Set-AuthenticodeSignature and timestamped via $ts"
                        break
                    } else {
                        $lastError = "Set-AuthenticodeSignature status: $($sig.StatusMessage)"
                    }
                } catch {
                    $lastError = $_.ToString()
                }
                Write-Warning "  Timestamp attempt failed with $ts, trying fallback server..."
            }
        }

        if (-not $signedSuccessfully) {
            throw "Failed to sign $file. Reason: $lastError"
        }

        # Verification of digital signature
        $sigResult = Get-AuthenticodeSignature -FilePath $file
        if (-not $sigResult.SignerCertificate) {
            throw "Signature verification failed: File $file is not signed."
        }

        Write-Host "  Verification Status: $($sigResult.Status)"
        Write-Host "  Publisher:           $($sigResult.SignerCertificate.Subject)"
        if ($sigResult.TimeStamperCertificate) {
            Write-Host "  Timestamped By:      $($sigResult.TimeStamperCertificate.Subject)"
        }
    }
}
finally {
    if ($tempCertPath -and (Test-Path $tempCertPath)) {
        Remove-Item -Path $tempCertPath -Force -ErrorAction SilentlyContinue
    }
}
