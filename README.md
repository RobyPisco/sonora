# Sonora

YouTube **audio** downloader desktop per Windows. Incolla un link, scegli il formato (mp3 / m4a / opus / flac / wav), premi Scarica.

![stack](https://img.shields.io/badge/python-3.14-blue) ![gui](https://img.shields.io/badge/GUI-PySide6-green)

## Funzioni
- Scarica **solo audio**: `mp3` / `m4a` / `opus` (bitrate 128/192/320), `flac` / `wav` (lossless).
- **Coda** di piu link e supporto **playlist** YouTube.
- **Anteprima** in coda: titolo, durata, miniatura.
- **Auto-incolla** link dagli appunti all'avvio + **drag & drop** dei link nella finestra.
- **Stop** download in corso, **Riprova** falliti, **menu click destro** (apri file/cartella, riprova, rimuovi).
- Opzioni: **cartella destinazione**, **sottocartella per file**, **template nome file**, **formato/bitrate**.
- Embed **metadata** (titolo/artista) e **copertina** (cover); **normalizza volume** (loudnorm).
- **Aggiorna yt-dlp** dall'app.
- **Separazione in stem** (Demucs): click destro su un brano o trascina un file audio → voce/batteria/basso/chitarra/piano/resto.
- **Qualità top con Roformer** (BS-Roformer via audio-separator): modalità *voce/strumentale* (karaoke al top) e *6 stem* in cascade (voce da Roformer, strumenti da Demucs sullo strumentale).
- **Mixer** (scheda dedicata): riproduce gli stem sincronizzati, mute/solo/**volume**/**pan** per traccia, **velocità** e **trasposizione** (semitoni), loop A-B, metronomo, waveform colorate, e analisi **BPM/tonalità/LUFS/presenza**.
- **Export del mix** dal mixer: salva la combinazione corrente (mute/solo/volume/pan/velocità/tono) in WAV/MP3 → basi karaoke / minus-one. La **sessione** del mixer si salva e si ricarica automaticamente.
- **Tray + monitor appunti**, **notifica a fine**, **cronologia** dei download.
- yt-dlp + ffmpeg **inclusi**: nessuna installazione esterna richiesta.
- Impostazioni salvate in `%APPDATA%/Sonora/settings.json`.

## Separazione stem
Separa un brano nelle sue tracce (2/4/6 stem) con **Demucs** (htdemucs_ft / htdemucs_6s), accelerato su **GPU NVIDIA**.
- Click destro su un download → **Separa in stem**, oppure **Separa file…** / trascina un audio locale.
- Output in `<nome> - stems/` (wav/flac/mp3).
- **Primo uso**: scarica un motore isolato (Python 3.12 + PyTorch CUDA + Demucs) in `%APPDATA%/Sonora/stem-engine/`
  via `bin/uv.exe`. Download una-tantum **~3 GB** (serve connessione). Su PC senza GPU usa la CPU (più lento).
- Perché isolato: PyTorch non ha wheel CUDA per Python 3.14, quindi il motore usa un proprio Python 3.12 con torch GPU.
- **Roformer**: le modalità *Roformer* installano al primo uso `audio-separator` nel venv del motore e scaricano il modello (BS-Roformer, ~centinaia di MB una-tantum) in `%APPDATA%/Sonora/separator-models/`. Qualità superiore su voce/strumentale, ma più lente e con più richiesta di VRAM.

## Avvio in sviluppo
```powershell
pip install -r requirements.txt
python run.py
```
> ffmpeg/ffprobe vanno presenti in `bin/`. Sono inclusi nella build; per lo sviluppo da sorgente scaricali (build statica Windows) e mettili in `bin/ffmpeg.exe` e `bin/ffprobe.exe`.

## Build .exe
```powershell
pip install pyinstaller
pyinstaller build.spec --noconfirm
```
Output: `dist/Sonora/Sonora.exe`. Distribuisci l'**intera cartella** `dist/Sonora/` (es. zippata). Avvio con doppio click, niente Python richiesto.

## Installer .exe (opzionale)
Crea un installer che mette l'app in Programmi con collegamenti desktop/menu.
1. Installa [Inno Setup 6](https://jrsoftware.org/isdl.php) (gratuito).
2. Fai la build PyInstaller (sopra).
3. Compila: `ISCC.exe installer\sonora.iss`
4. Output: `dist_installer\SonoraSetup-1.0.0.exe`

## Struttura
```
app/
  main.py        entrypoint QApplication
  ui.py          finestra, widget, stile
  downloader.py  wrapper yt-dlp in QThread + coda
  config.py      settings JSON (%APPDATA%)
  paths.py       risoluzione path bin/ (dev + PyInstaller)
bin/             ffmpeg.exe, ffprobe.exe
resources/       style.qss, icon.ico
build.spec       config PyInstaller (onedir)
run.py           launcher
```

## Note
- **Aggiornare yt-dlp** periodicamente (`pip install -U yt-dlp` e rifare la build): YouTube cambia spesso e versioni vecchie smettono di funzionare.
- Uso personale. Rispetta i termini di servizio di YouTube e il copyright dei contenuti.
