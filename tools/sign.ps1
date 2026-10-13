<#
  Signs one or more files with Authenticode (SHA-256 + RFC 3161 timestamp).

  Pick ONE certificate source (environment variables):
    SIGN_CERT_SHA1   thumbprint of a code-signing certificate in your Windows certificate store
                     (works for hardware tokens / EV certificates too; the token prompts for its PIN)
    SIGN_PFX         path to a .pfx file          (+ SIGN_PFX_PASSWORD)
  Optional:
    SIGN_TIMESTAMP   timestamp server URL (default http://timestamp.digicert.com)

  With none set, files are left unsigned and the script exits 0, so local builds still work.
  Usage: powershell -File tools\sign.ps1 file1.exe [file2.exe ...]
#>
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Files)
$ErrorActionPreference = "Stop"

$thumb = $env:SIGN_CERT_SHA1; $pfx = $env:SIGN_PFX
if (-not $thumb -and -not $pfx) { Write-Host "[unsigned] no SIGN_CERT_SHA1 / SIGN_PFX set: $($Files -join ', ')"; exit 0 }

$signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
if (-not $signtool) {
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
        Where-Object FullName -like "*\x64\*" | Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $signtool) { throw "signtool.exe not found. Install the Windows SDK (Signing Tools for Desktop Apps)." }

$ts = if ($env:SIGN_TIMESTAMP) { $env:SIGN_TIMESTAMP } else { "http://timestamp.digicert.com" }
foreach ($f in $Files) {
    if (-not (Test-Path $f)) { throw "File not found: $f" }
    $args = @("sign", "/fd", "SHA256", "/tr", $ts, "/td", "SHA256", "/d", "Lavati Downloader")
    if ($thumb) { $args += @("/sha1", $thumb) } else { $args += @("/f", $pfx); if ($env:SIGN_PFX_PASSWORD) { $args += @("/p", $env:SIGN_PFX_PASSWORD) } }
    & $signtool @args $f
    if ($LASTEXITCODE -ne 0) { throw "signtool failed for $f" }
    $sig = Get-AuthenticodeSignature $f
    Write-Host "[signed] $f  status=$($sig.Status)  signer=$($sig.SignerCertificate.Subject)"
}
