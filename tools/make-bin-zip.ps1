# Crea bin.zip con i binari bundlati (per la CI) a partire dalla cartella bin/.
# bin/ è gitignorato (troppo grande), quindi la CI li recupera da una release
# fissa con tag "deps".
#
# Uso (una tantum, dalla root del progetto):
#   pwsh tools/make-bin-zip.ps1
#   gh release create deps bin.zip -t "binari bundlati" -n "binari per la build CI"
#
# Quando aggiorni un binario (es. nuovo ffmpeg), rigenera e ricarica:
#   pwsh tools/make-bin-zip.ps1
#   gh release upload deps bin.zip --clobber

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $root "bin"
$zip = Join-Path $root "bin.zip"

$required = @(
    "ffmpeg.exe", "ffprobe.exe", "uv.exe",
    "rubberband.exe", "rubberband-r3.exe", "sndfile.dll"
)

$missing = $required | Where-Object { -not (Test-Path (Join-Path $bin $_)) }
if ($missing) {
    Write-Error "Mancano in bin/: $($missing -join ', ')"
    exit 1
}

if (Test-Path $zip) { Remove-Item $zip -Force }

# Zippa i CONTENUTI di bin/ (file alla radice dell'archivio, niente sottocartella
# bin/), così in CI Expand-Archive -DestinationPath bin li mette al posto giusto.
Compress-Archive -Path (Join-Path $bin "*") -DestinationPath $zip -CompressionLevel Optimal
Write-Host "Creato $zip"
Get-ChildItem $zip | Format-List Name, Length
