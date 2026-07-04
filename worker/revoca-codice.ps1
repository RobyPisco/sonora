<#
Revoca un codice di attivazione Sonora (o lo sgancia da un PC).

Uso (dalla cartella worker/):
    .\revoca-codice.ps1 ABCD-EFGH-JKLM-NPQR           # REVOCA (blocca entro ~7 giorni)
    .\revoca-codice.ps1 ABCD-EFGH-JKLM-NPQR -Reset    # SGANCIA dal PC (cliente cambia computer)
    .\revoca-codice.ps1 ABCD-EFGH-JKLM-NPQR -Info     # mostra solo lo stato

Password admin: come genera-codici.ps1 (env SONORA_ADMIN_SECRET o file .admin-secret).
#>
param(
    [Parameter(Mandatory = $true)][string]$Codice,
    [switch]$Reset,
    [switch]$Info
)

$ErrorActionPreference = "Stop"
$Api = "https://sonora-license.piscofactory.workers.dev"

$secret = $env:SONORA_ADMIN_SECRET
if (-not $secret) {
    $f = Join-Path $PSScriptRoot ".admin-secret"
    if (Test-Path $f) { $secret = (Get-Content $f -Raw).Trim() }
}
if (-not $secret) {
    Write-Error "Password admin mancante: imposta `$env:SONORA_ADMIN_SECRET oppure crea il file .admin-secret."
    exit 1
}

$path = if ($Info) { "/admin/get" } elseif ($Reset) { "/admin/reset" } else { "/admin/revoke" }
$body = @{ code = $Codice } | ConvertTo-Json
$resp = Invoke-RestMethod -Uri "$Api$path" -Method Post -ContentType "application/json" `
    -Headers @{ "X-Admin-Secret" = $secret } -Body $body

if ($Info) {
    Write-Host "Stato di $Codice :" -ForegroundColor Green
    $resp.record | ConvertTo-Json
} elseif ($Reset) {
    Write-Host "Codice $Codice sganciato dal PC: ora è ri-attivabile su un altro computer." -ForegroundColor Green
} else {
    Write-Host "Codice $Codice REVOCATO: il PC si bloccherà entro ~7 giorni (anche offline)." -ForegroundColor Yellow
}
