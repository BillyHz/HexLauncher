param(
    [Parameter(Mandatory = $true)][string]$CertificateThumbprint,
    [string]$Executable = (Join-Path $PSScriptRoot '..\dist\HexLauncher.exe'),
    [string]$TimestampUrl = 'http://timestamp.digicert.com'
)
$ErrorActionPreference = 'Stop'
$Executable = (Resolve-Path -LiteralPath $Executable).Path
if ($CertificateThumbprint -notmatch '^[a-fA-F0-9]{40}$') {
    throw 'Specify the SHA-1 thumbprint of your trusted code-signing certificate.'
}
$tool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if ($tool) {
    $toolPath = $tool.Source
} else {
    $sdkPath = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
    $toolPath = Get-ChildItem -Path "$sdkPath\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $toolPath) { throw 'Install the Windows SDK signing tools or put signtool.exe on PATH.' }
& $toolPath sign /sha1 $CertificateThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $Executable
if ($LASTEXITCODE -ne 0) { throw "Signing failed ($LASTEXITCODE)." }
& $toolPath verify /pa /all /v $Executable
if ($LASTEXITCODE -ne 0) { throw "Signature verification failed ($LASTEXITCODE)." }
$signature = Get-AuthenticodeSignature -LiteralPath $Executable
if ($signature.Status -ne 'Valid' -or -not $signature.TimeStamperCertificate) {
    throw 'A trusted, timestamped Authenticode signature is required.'
}
Write-Host "Verified publisher: $($signature.SignerCertificate.Subject)"
