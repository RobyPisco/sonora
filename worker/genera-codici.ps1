<#
Genera codici di attivazione Sonora chiamando il Worker (/admin/new).

Uso (dalla cartella worker/):
    .\genera-codici.ps1                    # 1 codice
    .\genera-codici.ps1 5                  # 5 codici
    .\genera-codici.ps1 3 "Mario Rossi"    # 3 codici con nota (a chi li vendi)

La password admin viene letta, in ordine, da:
    1) variabile d'ambiente  $env:SONORA_ADMIN_SECRET
    2) file  .admin-secret   nella stessa cartella (una riga; è gitignorato)
#>
param(
    [int]$Quantita = 1,
    [string]$Nota = ""
)

$ErrorActionPreference = "Stop"
$Api = "https://sonora-license.piscofactory.workers.dev"

$secret = $env:SONORA_ADMIN_SECRET
if (-not $secret) {
    $f = Join-Path $PSScriptRoot ".admin-secret"
    if (Test-Path $f) { $secret = (Get-Content $f -Raw).Trim() }
}
if (-not $secret) {
    Write-Error "Password admin mancante: imposta `$env:SONORA_ADMIN_SECRET oppure crea il file .admin-secret nella cartella worker/."
    exit 1
}

$body = @{ count = $Quantita; note = $Nota } | ConvertTo-Json
try {
    $resp = Invoke-RestMethod -Uri "$Api/admin/new" -Method Post -ContentType "application/json" `
        -Headers @{ "X-Admin-Secret" = $secret } -Body $body
} catch {
    Write-Error "Errore dal server: $_"
    exit 1
}

Write-Host ""
Write-Host ("Generati {0} codici" -f $resp.codes.Count) -ForegroundColor Green
if ($Nota) { Write-Host ("Nota: {0}" -f $Nota) -ForegroundColor DarkGray }
Write-Host ""
$resp.codes | ForEach-Object { Write-Host "  $_" -ForegroundColor Cyan }
Write-Host ""
Write-Host "Consegna un codice per cliente. Ogni codice si attiva su UN solo PC." -ForegroundColor DarkGray
