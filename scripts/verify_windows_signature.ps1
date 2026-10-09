<#
.SYNOPSIS
    Verifies Authenticode digital signatures of Windows executables and installers.

.DESCRIPTION
    Checks whether specified files have valid Authenticode signatures, prints
    publisher/signer details, certificate thumbprint, and timestamp information.
    Specifically checks whether the signature chains to a trusted root authority
    or terminates at an untrusted self-signed root.

.PARAMETER Target
    One or more file paths to verify.

.PARAMETER RequireValid
    If set, throws an error if signature status is anything other than 'Valid'.
#>

param (
    [string[]]$Target = @(),
    [switch]$RequireValid
)

$allValid = $true
$hasUntrustedRoots = $false
$summary = @()

$rawList = @($Target) + @($args)

$flattenedTargets = @()
foreach ($entry in $rawList) {
    if (-not $entry) { continue }
    $parts = $entry -split "[;,]"
    foreach ($p in $parts) {
        $clean = $p.Trim('"', "'", " ").Trim()
        if ($clean -and $clean -notmatch "^-") {
            $flattenedTargets += $clean
        }
    }
}

if ($flattenedTargets.Count -eq 0) {
    Write-Warning "No target files specified for signature verification."
    exit 0
}

foreach ($cleanPath in $flattenedTargets) {
    if (-not (Test-Path $cleanPath)) {
        Write-Error "Verification target does not exist: $cleanPath"
        $allValid = $false
        continue
    }

    $file = (Resolve-Path $cleanPath).Path
    $fileInfo = Get-Item $file
    $sig = Get-AuthenticodeSignature -FilePath $file

    Write-Host "---------------------------------------------------"
    Write-Host "Target: $($fileInfo.Name) ($([Math]::Round($fileInfo.Length / 1MB, 2)) MB)"
    Write-Host "Path:   $file"

    if (-not $sig.SignerCertificate) {
        Write-Error "  [FAILED] File is NOT signed! (Status: $($sig.Status))"
        $allValid = $false
        continue
    }

    $signer = $sig.SignerCertificate
    $publisherName = $signer.Subject
    if ($publisherName -match "CN=([^,]+)") {
        $publisherName = $Matches[1]
    }

    $isSelfSigned = ($signer.Subject -eq $signer.Issuer)

    Write-Host "  Signature Status: $($sig.Status)"
    Write-Host "  Publisher:        $publisherName"
    Write-Host "  Full Subject:     $($signer.Subject)"
    Write-Host "  Issuer:           $($signer.Issuer)"
    Write-Host "  Self-Signed:      $isSelfSigned"
    Write-Host "  Valid Dates:      $($signer.NotBefore.ToString('yyyy-MM-dd')) to $($signer.NotAfter.ToString('yyyy-MM-dd'))"
    Write-Host "  Thumbprint:       $($signer.Thumbprint)"

    if ($sig.TimeStamperCertificate) {
        Write-Host "  Timestamp By:     $($sig.TimeStamperCertificate.Subject)"
    } else {
        Write-Warning "  Timestamp:       No timestamp found on signature."
    }

    if ($sig.Status -eq "Valid") {
        Write-Host "  [TRUSTED] Signature is VALID and chains to a trusted Microsoft Root CA."
    } elseif ($sig.Status -eq "UnknownError" -or $isSelfSigned) {
        $hasUntrustedRoots = $true
        Write-Warning "  [UNTRUSTED ROOT] Signature terminates at a root not trusted by Windows Trust Provider."
        Write-Warning "  -> Windows SmartScreen will display 'Windows protected your PC' and 'Publisher: Unknown publisher'."
        Write-Warning "  -> A publicly trusted Authenticode certificate (e.g. DigiCert, Sectigo, GlobalSign) is required."
        if ($RequireValid -or ($env:REQUIRE_VALID_SIGNATURE -eq "1")) {
            Write-Error "  [FAILED] Signature status is '$($sig.Status)' (Required: Valid)."
            $allValid = $false
        }
    } else {
        Write-Error "  [FAILED] Unexpected signature status: $($sig.Status)"
        $allValid = $false
    }

    $summary += [PSCustomObject]@{
        Name       = $fileInfo.Name
        Publisher  = $publisherName
        Status     = $sig.Status
        Trusted    = ($sig.Status -eq "Valid")
        Thumbprint = $signer.Thumbprint
        Timestamp  = ($sig.TimeStamperCertificate -ne $null)
    }
}

Write-Host "---------------------------------------------------"
if (-not $allValid) {
    Write-Error "One or more target files failed signature verification."
    exit 1
}

if ($hasUntrustedRoots -and -not $RequireValid) {
    Write-Warning "Notice: Binaries are signed, but certificate is NOT publicly trusted."
    Write-Warning "Windows SmartScreen warning will PERSIST until a legitimate public CA certificate is used."
} else {
    Write-Host "All specified targets verified successfully."
}

exit 0
