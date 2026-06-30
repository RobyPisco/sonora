# Sonora

**Italiano** · [English](#english)

![python](https://img.shields.io/badge/python-3.14-blue) ![gui](https://img.shields.io/badge/GUI-PySide6-green) ![version](https://img.shields.io/badge/versione-1.5.8-orange)

App desktop Windows per **scaricare audio da YouTube**, **separarlo in stem** e **esercitarsi** sui brani con un mixer di pratica, visualizzatore di testi e un accordatore. Tutto in locale.

## Funzioni

**Download**
- Scarica **solo audio**: `mp3` / `m4a` / `opus` (bitrate 128/192/320), `flac` / `wav` (lossless).
- **Ricerca testuale**: scrivi cosa cercare e premi Invio (niente link → ytsearch).
- **Coda** di più link e supporto **playlist** YouTube; **anteprima** (titolo, durata, miniatura).
- **Auto-incolla** dagli appunti + **drag & drop** di link e file audio locali.
- **Stop**, **Riprova** falliti, **menu contestuale** (apri file/cartella, riprova, rimuovi).
- Opzioni: cartella destinazione, sottocartella per file, template nome file, formato/bitrate, embed **metadata** e **copertina**, **normalizza volume** (loudnorm).
- **Aggiorna yt-dlp** dall'app; **tray + monitor appunti**, **notifica a fine**, **cronologia**.

**Separazione stem**
- **Demucs**: 2 / 4 / 6 stem e **6hq** (ensemble htdemucs_ft + htdemucs_6s, qualità massima), accelerato su **GPU NVIDIA**.
- **Roformer** (BS-RoFormer via audio-separator): *voce/strumentale* (karaoke al top) e *6 stem in cascade* (voce da Roformer, strumenti da Demucs).
- Click destro su un download → **Separa in stem**, oppure **Separa file…** / trascina un audio. Output in `<nome> - stems/`.
- **Auto-analisi a fine separazione**: BPM, tonalità, LUFS, beat e accordi vengono calcolati subito.

**Mixer / studio di pratica**
- Riproduce gli stem sincronizzati; **volume / mute / solo / pan** ed **EQ a 3 bande** per traccia.
- **Waveform premium**: stile rounded a barre verticali discrete con sfumatura gradiente e indicazione del progresso di riproduzione (attiva a sinistra del playhead, semi-trasparente a destra).
- **Zoom waveform**: zoom fluido della vista (pulsanti +/- o Ctrl+rotella del mouse) e **barra di scorrimento orizzontale** coordinata che segue il playhead.
- **Timeline con Beat Grid**: righello superiore allineato alle waveform che mostra misure e tempi (es. `1`, `.2`, `.3`, `.4`...) o secondi. Supporta **Click & Drag** per saltare (seek) in qualsiasi punto del brano.
- **Time-stretch studio**: time-stretch e pitch-shift ad alta fedeltà integrando **Rubberband R3** in background (con fallback automatico al phase vocoder numpy originale).
- **Velocità** (time-stretch a tono invariato) e **trasposizione** (±semitoni a velocità invariata).
- **Loop A-B** e **loop progressivo "Auto↑"** (parte lento e accelera ad ogni giro fino al 100%).
- **Sezioni / struttura del brano** (salta o loopa una sezione), **metronomo** (segue la velocità).
- **Analisi**: BPM, tonalità + scala, LUFS, dynamic range, stabilità del tempo, presenza per stem, accordi.
- **Export del mix**: salva la combinazione corrente (mute/solo/volume/pan/EQ/velocità/tono) in WAV/FLAC/MP3 → basi karaoke / minus-one. La **sessione** del mixer si salva e ricarica per ogni brano.

**Visualizzatore testi (Lyrics Finder)**
- Cerca e scarica in background i testi da **LRCLIB** (API aperta senza chiavi) al caricamento dei brani.
- **Caching locale** in `lyrics.txt` per caricamento immediato offline.
- Formattazione centrata con evidenziazione grafica delle intestazioni di sezione (es. `[Chorus]`).
- Barra di ricerca manuale per trovare i testi digitando autore e titolo, con editor di testo integrato per modificare e salvare correzioni locali.

**Accordatore**
- Tono di riferimento **A440** e per **corde di chitarra/basso**, più **accordatore dal microfono** (rilevamento del pitch in tempo reale).

**Interfaccia**
- Layout **responsive**: due colonne su schermi larghi, colonna unica su monitor piccoli.

## Avvio in sviluppo
```powershell
pip install -r requirements.txt
python run.py
```
> `ffmpeg.exe` / `ffprobe.exe` vanno in `bin/` (inclusi nella build; per lo sviluppo scarica una build statica Windows). `bin/uv.exe` serve a creare il motore stem.

## Build .exe
```powershell
pip install pyinstaller
pyinstaller build.spec --noconfirm
```
Output: `dist/Sonora/Sonora.exe` (distribuisci l'intera cartella `dist/Sonora/`).

## Installer .exe (opzionale)
1. Installa [Inno Setup 6](https://jrsoftware.org/isdl.php).
2. Fai la build PyInstaller (sopra).
3. Compila: `ISCC.exe installer\sonora.iss`
4. Output: `dist_installer\SonoraSetup-1.5.8.exe`

## Motore stem (isolato)
PyTorch non ha wheel CUDA per Python 3.14, quindi al primo uso Sonora crea un motore isolato (**Python 3.12 + PyTorch CUDA + Demucs + audio-separator + librosa**) in `%APPDATA%/Sonora/stem-engine/` via `bin/uv.exe`. Download una-tantum **~3 GB**. Su PC senza GPU usa la CPU (più lento). I modelli Roformer (~centinaia di MB) si scaricano al primo uso in `%APPDATA%/Sonora/separator-models/`.

## Struttura
```
app/
  main.py          entrypoint QApplication
  ui.py            finestra a tab [Scarica|Mixer|Testi] + layout responsive
  ui_lyrics.py     Scheda Testi e LyricsWorker (download testi da LRCLIB)
  downloader.py    wrapper yt-dlp in QThread + coda + ricerca
  stems.py         install motore + separazione (Demucs/Roformer) + analisi
  analyze_script.py / roformer_script.py   eseguiti nel venv 3.12 del motore
  mixer_engine.py  mix realtime (numpy/sounddevice/soundfile)
  ui_mixer.py      mixer: strisce, timeline, export, sessione, sezioni, beat grid
  timestretch.py   time-stretch (Rubberband R3 con fallback su numpy)
  waveform.py      widget waveform (rounded bars, gradienti, playhead, zoom)
  tuner.py / ui_tuner.py   accordatore (tono di riferimento + pitch dal mic)
  config.py history.py updater.py app_update.py paths.py
bin/               ffmpeg.exe, ffprobe.exe, uv.exe, rubberband.exe, rubberband-r3.exe, sndfile.dll (non versionati)
resources/         style.qss, icon.ico, svg
build.spec         config PyInstaller (onedir)
installer/         sonora.iss (Inno Setup)
```

## Note
- **Aggiorna yt-dlp** periodicamente: YouTube cambia spesso.
- Impostazioni, cronologia, sessioni e analisi in `%APPDATA%/Sonora/`.
- Uso personale e responsabile: separa ed elabora solo contenuti di cui detieni i diritti.

---

# English

[Italiano](#sonora) · **English**

Windows desktop app to **download audio from YouTube**, **split it into stems** and **practice** songs with a practice mixer, a lyrics viewer, and a tuner. Fully local.

## Features

**Download**
- **Audio only**: `mp3` / `m4a` / `opus` (128/192/320), `flac` / `wav` (lossless).
- **Text search** (type and press Enter → ytsearch), **queue** + YouTube **playlists**, in-queue **preview** (title, duration, thumbnail).
- **Auto-paste** from clipboard + **drag & drop** of links and local audio files.
- **Stop**, **retry failed**, **context menu** (open file/folder, retry, remove).
- Options: destination folder, per-file subfolder, filename template, format/bitrate, embed **metadata** & **cover**, **volume normalize** (loudnorm).
- **Update yt-dlp** in-app; **tray + clipboard watch**, **finish notification**, **history**.

**Stem separation**
- **Demucs**: 2 / 4 / 6 stems and **6hq** (htdemucs_ft + htdemucs_6s ensemble, top quality), **NVIDIA GPU** accelerated.
- **Roformer** (BS-RoFormer via audio-separator): *vocals/instrumental* (top karaoke) and *6-stem cascade*.
- Right-click a download → **Separate to stems**, or **Separate file…** / drag an audio file. Output in `<name> - stems/`.
- **Auto-analysis after separation**: BPM, key, LUFS, beats and chords computed right away.

**Mixer / practice studio**
- Synced stem playback; per-track **volume / mute / solo / pan** and **3-band EQ**; colored waveforms.
- **Premium Waveforms**: discrete rounded vertical bars with a vertical linear gradient and playhead-aware coloring (active on the left of the playhead, semi-transparent on the right).
- **Zoom controls**: smooth zoom (buttons +/- or Ctrl+mouse wheel) and **horizontal scrollbar** coordinated with the playhead.
- **Timeline with Beat Grid**: top ruler showing bars & beats (e.g. `1`, `.2`, `.3`, `.4`...) or seconds. Supports **Click & Drag** seeking.
- **Studio time-stretch**: high-quality time-stretch and pitch-shift via **Rubberband R3** integration (with automatic fallback to the original numpy phase vocoder).
- **Speed** (pitch-preserving time-stretch) and **transpose** (±semitones at constant speed).
- **A-B loop** and **progressive loop "Auto↑"** (starts slow, speeds up each pass up to 100%).
- **Song sections** (jump to / loop a section), **metronome** (follows speed).
- **Analysis**: BPM, key + scale, LUFS, dynamic range, tempo stability, per-stem presence, chords.
- **Mix export**: bounce the current mix (mute/solo/volume/pan/EQ/speed/pitch) to WAV/FLAC/MP3 → karaoke / minus-one tracks. Mixer **session** auto-saved per song.

**Lyrics Finder**
- Automatically searches and downloads song lyrics from **LRCLIB** (public, keyless API) when stems are loaded.
- **Local caching** in `lyrics.txt` for instant offline loading.
- Centered layout with section titles (e.g. `[Chorus]`) highlighted in orange.
- Manual search bar to query lyrics by artist/title, with an integrated text editor to modify and save local corrections.

**Tuner**
- **A440** and **guitar/bass string** reference tones, plus a **microphone tuner** (real-time pitch detection).

**UI**
- **Responsive** layout: two columns on wide screens, single column on small monitors.

## Run from source
```powershell
pip install -r requirements.txt
python run.py
```
> Put `ffmpeg.exe` / `ffprobe.exe` in `bin/` (bundled in builds; for source dev grab a static Windows build). `bin/uv.exe` is used to create the stem engine.

## Build .exe
```powershell
pip install pyinstaller
pyinstaller build.spec --noconfirm
```
Output: `dist/Sonora/Sonora.exe` (ship the whole `dist/Sonora/` folder).

## Installer (optional)
1. Install [Inno Setup 6](https://jrsoftware.org/isdl.php).
2. Run the PyInstaller build (above).
3. Compile: `ISCC.exe installer\sonora.iss` → `dist_installer\SonoraSetup-1.5.8.exe`.

## Stem engine (isolated)
PyTorch has no CUDA wheel for Python 3.14, so on first use Sonora builds an isolated engine (**Python 3.12 + PyTorch CUDA + Demucs + audio-separator + librosa**) in `%APPDATA%/Sonora/stem-engine/` via `bin/uv.exe`. One-time **~3 GB** download. Falls back to CPU without a GPU. Roformer models download on first use to `%APPDATA%/Sonora/separator-models/`.

## Notes
- **Update yt-dlp** regularly: YouTube changes often.
- Settings, history, sessions and analysis live in `%APPDATA%/Sonora/`.
- Personal, responsible use: only process content you have the rights to.
