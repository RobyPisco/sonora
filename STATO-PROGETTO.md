# Sonora — stato progetto (ripresa lavori)

App desktop Windows: **YouTube audio downloader + separazione stem + mixer/studio di pratica + accordatore + visualizzatore testi**.
Path progetto: `C:\xampp\htdocs\sonora`. Python **3.14** + PySide6. Tutto salvato su disco e allineato su GitHub.
Versione corrente: **1.5.4** (allineata in `app/__init__.py`, `installer/sonora.iss` e GitHub).

## Cosa fa (completo e funzionante)
- **Download**: yt-dlp (libreria), formati mp3/m4a/opus/flac/wav, coda + playlist, anteprima (titolo/durata/cover),
  **ricerca testuale** (scrivi e premi Invio → ytsearch), auto-incolla + drag&drop, **carica file locale**,
  Stop/Riprova/menu contestuale, sottocartella per file, metadata+cover, normalizza volume.
- **Tray + monitor appunti**, **notifica a fine**, **cronologia** (`history.json`), **aggiorna yt-dlp**.
- **Auto-update app ATTIVO**: `update_repo` predefinito = `RobyPisco/sonora`. All'avvio controlla in
  background le GitHub Releases; se c'è una versione più nuova propone "scarica e installa" (1 click),
  scarica l'installer in `%APPDATA%/Sonora/updates/`, lo lancia e chiude l'app (l'installer Inno Setup
  chiude l'istanza con `CloseApplications=yes`). Anche manuale da tray "Controlla aggiornamenti app".
  Disattivabile con `auto_check_updates: false` in settings.json.
- **CI release** (`.github/workflows/release.yml`): al push di un tag `vX.Y.Z` builda exe+installer su
  runner Windows e pubblica la Release. **Autosufficiente**: scarica ffmpeg/ffprobe/uv da fonti ufficiali
  (BtbN, astral), nessun `bin/` da fornire. rubberband/sndfile opzionali (fallback numpy); per includerli
  carica `rubberband-win64.zip` in una release tag `deps` (vedi `tools/make-bin-zip.ps1`). Il tag deve
  combaciare con `__version__` in `app/__init__.py`. Avvio manuale (`workflow_dispatch`) = build di prova
  senza pubblicare, con l'installer caricato come artifact.
- **Separazione stem**: click destro / "Separa file…" / drag. Modalità:
  - **Roformer 6 stem** (rof6) e **Roformer voce/strumentale** (rof, top karaoke) — via audio-separator / BS-RoFormer
  - **6hq** (ensemble Demucs htdemucs_ft+htdemucs_6s), **6**, **4**, **2** (Demucs)
  - Output wav/flac/mp3. "Separa tutti" (salta i già separati).
  - **Auto-analisi a fine separazione**: calcolo immediato di BPM, key e beat grid.
- **Mixer / studio di pratica** (scheda integrata):
  - play sincronizzato, **volume/mute/solo/pan** per traccia, **EQ a 3 bande** (Bassi/Medi/Alti) per traccia.
  - **Waveform premium**: stile rounded a barre verticali discrete con sfumatura gradiente e indicazione visiva dello stato di riproduzione (colorate a sinistra del playhead, grigie/semi-trasparenti a destra).
  - **Zoom delle waveform**: zoom fluido avanti/indietro (pulsanti +/– o Ctrl+rotella del mouse) e **barra di scorrimento orizzontale** coordinata che segue il playhead.
  - **Timeline con Beat Grid**: righello superiore allineato alle waveform. Mostra misure e tempi (es. `1`, `.2`, `.3`, `.4`, `2`...) in base allo zoom se il brano è analizzato, oppure la timeline dei secondi. Supporta il Click & Drag per effettuare il seek (navigazione) del brano.
  - **pannello analisi** (BPM, tonalità+scala, LUFS, dynamic range, tempo stability, presenza %).
  - **Velocità (time-stretch)** e **Trasposizione (pitch-shift)** in tempo reale.
  - **Loop A-B**, **loop progressivo "Auto↑"** (parte lento e accelera di X% ogni N giri fino a 100%).
  - **Sezioni / struttura del brano**: pulsanti per saltare o loopare una sezione.
  - **Metronomo** (click ai beat, segue velocità).
  - **Export mix "Esporta…"**: bounce con volumi/mute/solo/pan/EQ + velocità/pitch applicati (wav/flac/mp3,
    opzione di includere il click). Stem mutati esportati con prefisso (es. `NO_BASSO - …`).
  - **Sessione mixer salvata per brano** (fader/pan/mute/solo/velocità/tono): ripristino automatico al ricarico.
  - **scorciatoie** (Spazio/L/Home/A/B/1-6).
- **Scheda "Testi" (Lyrics Finder)**:
  - Download automatico in background dei testi da **LRCLIB** (API aperta e gratuita) al caricamento dei brani.
  - Salvataggio locale in `lyrics.txt` per il caricamento offline immediato.
  - Visualizzazione formattata e centrata (sezioni come `[Chorus]` evidenziate in arancione).
  - Ricerca manuale dei testi e editor integrato per modificare/salvare correzioni locali.
- **Accordatore** (dialog dal pulsante "🎼 Accordatore" nel mixer): tono di riferimento A440 / corde
  chitarra+basso e **accordatore dal microfono** (pitch via autocorrelazione FFT, niente Qt nel core).
- **UI responsive**: la scheda Scarica passa da due colonne (largo) a colonna unica impilata (< 900 px),
  niente più sovrapposizioni su monitor piccoli (vedi `MainWindow._apply_layout`).

## Architettura chiave
- Main app gira su **Python 3.14** (PyInstaller onedir → `dist/Sonora/Sonora.exe`).
- **Motore stem isolato**: PyTorch non ha CUDA su 3.14 → venv **Python 3.12 + torch cu124 + demucs +
  audio-separator + librosa + pyloudnorm** in `%APPDATA%/Sonora/stem-engine/`, creato con `bin/uv.exe`,
  richiamato come subprocess. GPU: RTX 3060 6GB.
- Analisi (BPM/key) gira nel venv 3.12 via `app/analyze_script.py` → scrive `<stems>/analysis.json`.
- Roformer gira nel venv 3.12 via `app/roformer_script.py` (audio-separator).
- Playback/Mix: **numpy + sounddevice + soundfile** nel main app (mix realtime, sync campione-esatto).
- **Time-stretch studio (Rubberband)**: `app/timestretch.py` esegue in background Rubberband R3 (`bin/rubberband.exe` ed `sndfile.dll`) in un'unica operazione combinata di stretch+pitch. Include fallback automatico all'algoritmo numpy originale in caso di assenza dei binari.

## File principali (`app/`)
- `main.py` entrypoint · `ui.py` finestra a tab [Scarica|Mixer|Testi] + layout responsive · `downloader.py` yt-dlp worker
- `stems.py` install motore + separate (Demucs/Roformer) + analyze · `analyze_script.py` · `roformer_script.py`
  (eseguiti dal venv 3.12)
- `mixer_engine.py` · `timestretch.py` · `waveform.py` · `ui_mixer.py` (mixer + timeline + export + sessione)
- `ui_lyrics.py` (Scheda Testi e LyricsWorker)
- `tuner.py` (core audio accordatore) · `ui_tuner.py` (TunerDialog)
- `config.py` (settings %APPDATA%/Sonora) · `history.py` · `updater.py` (yt-dlp) · `app_update.py` · `paths.py`
- `bin/` ffmpeg, ffprobe, uv, rubberband.exe, rubberband-r3.exe, sndfile.dll
- `resources/` qss, svg, icon · `build.spec` · `installer/sonora.iss`

## Test
- `pip install -r requirements-dev.txt` poi `python -m pytest` (22 test, moduli a logica pura:
  app_update versioni/asset, timestretch, mixer_engine, analyze_script detect_key). Girano anche in CI
  (`.github/workflows/tests.yml`) su push/PR a main. Niente GUI/rubberband richiesti.

## Comandi
- Dev: `python run.py`
- Build exe: `python -m PyInstaller build.spec --noconfirm` → `dist/Sonora/Sonora.exe`
- Installer: `"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\sonora.iss` → `dist_installer/SonoraSetup-1.5.4.exe`

## DA FARE (idee proposte, scelta utente)
- **Rubberband in CI (opzionale)**: senza, le build CI usano il fallback numpy (time-stretch meno fine).
  Per includerlo: `pwsh tools/make-bin-zip.ps1` + carica `rubberband-win64.zip` nella release `deps`.
- **Firma installer**: senza firma Windows SmartScreen mostra "editore sconosciuto" (anche durante
  l'auto-update). Certificato OV ~100-400€/anno.

## Note
- Settings/cronologia/analysis/sessioni mixer in `%APPDATA%/Sonora/`.
- Inno Setup installato in `%LOCALAPPDATA%\Programs\Inno Setup 6\` (non nel path di default).
- Build + installer 1.5.4 rigenerati e deploy testato funzionante (giugno 2026).
