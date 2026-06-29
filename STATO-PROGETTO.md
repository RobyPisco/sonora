# Sonora — stato progetto (ripresa lavori)

App desktop Windows: **YouTube audio downloader + separazione stem + mixer/studio di pratica + accordatore**.
Path progetto: `C:\xampp\htdocs\sonora`. Python **3.14** + PySide6. Tutto salvato su disco (no git).
Versione corrente: **1.5.2** (allineata in `app/__init__.py` e `installer/sonora.iss`).

## Cosa fa (completo e funzionante)
- **Download**: yt-dlp (libreria), formati mp3/m4a/opus/flac/wav, coda + playlist, anteprima (titolo/durata/cover),
  **ricerca testuale** (scrivi e premi Invio → ytsearch), auto-incolla + drag&drop, **carica file locale**,
  Stop/Riprova/menu contestuale, sottocartella per file, metadata+cover, normalizza volume.
- **Tray + monitor appunti**, **notifica a fine**, **cronologia** (`history.json`), **aggiorna yt-dlp**.
- **Auto-update app**: meccanismo pronto (tray "Controlla aggiornamenti app") ma serve un repo GitHub
  (`update_repo` in settings.json) per funzionare. NON ancora attivo.
- **Separazione stem**: click destro / "Separa file…" / drag. Modalità:
  - **Roformer 6 stem** (rof6) e **Roformer voce/strumentale** (rof, top karaoke) — via audio-separator / BS-RoFormer
  - **6hq** (ensemble Demucs htdemucs_ft+htdemucs_6s), **6**, **4**, **2** (Demucs)
  - Output wav/flac/mp3. "Separa tutti" (salta i già separati).
- **Mixer / studio di pratica** (scheda integrata):
  - play sincronizzato, **volume/mute/solo/pan** per traccia, **EQ a 3 bande** (Bassi/Medi/Alti) per traccia,
    waveform colorate, playhead/seek.
  - **pannello analisi** (BPM, tonalità+scala, LUFS, dynamic range, tempo stability, presenza %).
  - **Velocità** (time-stretch pitch-preserving), **Trasposizione** (±semitoni, mantiene velocità).
  - **Loop A-B**, **loop progressivo "Auto↑"** (parte lento e accelera di X% ogni N giri fino a 100%).
  - **Sezioni / struttura del brano**: pulsanti per saltare o loopare una sezione.
  - **Metronomo** (click ai beat, segue velocità).
  - **Export mix "Esporta…"**: bounce con volumi/mute/solo/pan/EQ + velocità/pitch applicati (wav/flac/mp3,
    opzione di includere il click). Stem mutati esportati con prefisso (es. `NO_BASSO - …`).
  - **Sessione mixer salvata per brano** (fader/pan/mute/solo/velocità/tono): ripristino automatico al ricarico.
  - **scorciatoie** (Spazio/L/Home/A/B/1-6).
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
- Mixer/playback: **numpy + sounddevice + soundfile** nel main app (mix realtime, sync campione-esatto).
- Time-stretch: `app/timestretch.py` (phase vocoder numpy, no librosa).

## File principali (`app/`)
- `main.py` entrypoint · `ui.py` finestra a tab [Scarica|Mixer] + layout responsive · `downloader.py` yt-dlp worker
- `stems.py` install motore + separate (Demucs/Roformer) + analyze · `analyze_script.py` · `roformer_script.py`
  (eseguiti dal venv 3.12)
- `mixer_engine.py` · `timestretch.py` · `waveform.py` · `ui_mixer.py` (mixer + export + sessione + sezioni)
- `tuner.py` (core audio accordatore) · `ui_tuner.py` (TunerDialog)
- `config.py` (settings %APPDATA%/Sonora) · `history.py` · `updater.py` (yt-dlp) · `app_update.py` · `paths.py`
- `bin/` ffmpeg, ffprobe, uv · `resources/` qss, svg, icon · `build.spec` · `installer/sonora.iss`

## Comandi
- Dev: `python run.py`
- Build exe: `python -m PyInstaller build.spec --noconfirm` → `dist/Sonora/Sonora.exe`
- Installer: `"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\sonora.iss` → `dist_installer/SonoraSetup-1.5.2.exe`

## DA FARE (idee proposte, scelta utente)
- **Auto-update app**: creare repo GitHub + release per attivarlo (`update_repo` in settings.json).
- **Firma installer**: senza firma Windows SmartScreen mostra "editore sconosciuto".
- **Qualità time-stretch studio**: bundlare `rubberband` (ora phase vocoder numpy: leggera "phasiness" a velocità basse).
- Rifiniture mixer: auto-analisi a fine separazione; beat grid sulla timeline; zoom waveform.

## Note
- Settings/cronologia/analysis/sessioni mixer in `%APPDATA%/Sonora/`.
- Inno Setup installato in `%LOCALAPPDATA%\Programs\Inno Setup 6\` (non nel path di default).
- Build + installer 1.5.2 rigenerati e deploy testato funzionante (giugno 2026).
