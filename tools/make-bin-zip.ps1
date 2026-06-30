# OPZIONALE — impacchetta rubberband per la CI.
#
# La CI scarica da sola ffmpeg/ffprobe/uv da fonti ufficiali, quindi NON servono.
# rubberband/sndfile.dll sono opzionali: senza, l'app usa il phase-vocoder numpy
# (qualità di time-stretch più bassa). Se vuoi rubberband nelle build CI, crea
# questo zip e caricalo in una release con tag "deps":
#
#   pwsh tools/make-bin-zip.ps1
#   gh release create deps rubberband-win64.zip -t "binari opzionali" -n "rubberband per la CI"
#   # aggiornamenti successivi:
#   gh release upload deps rubberband-win64.zip --clobber

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $root "bin"
$zip = Join-Path $root "rubberband-win64.zip"

$files = @("rubberband.exe", "rubberband-r3.exe", "sndfile.dll")
$present = $files | Where-Object { Test-Path (Join-Path $bin $_) }
if (-not $present) {
    Write-Error "Nessun file rubberband trovato in bin/ ($($files -join ', '))."
    exit 1
}

if (Test-Path $zip) { Remove-Item $zip -Force }

# Zippa i CONTENUTI (file alla radice dell'archivio): in CI Expand-Archive
# -DestinationPath bin li mette direttamente in bin/.
$paths = $present | ForEach-Object { Join-Path $bin $_ }
Compress-Archive -Path $paths -DestinationPath $zip -CompressionLevel Optimal
Write-Host "Creato $zip con: $($present -join ', ')"
