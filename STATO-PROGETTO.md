# Sonora — stato progetto (ripresa lavori)

App desktop Windows: **YouTube audio downloader + separazione stem + mixer/studio di pratica + accordatore + visualizzatore testi**.
Path progetto: `C:\xampp\htdocs\sonora`. Python **3.14** + PySide6. Tutto salvato su disco e allineato su GitHub.
Versione corrente: **1.6.5** (allineata in `app/__init__.py`, `installer/sonora.iss` e GitHub).

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
  **Verifica integrità**: la CI pubblica `SonoraSetup-X.Y.Z.exe.sha256` accanto all'installer; l'updater
  calcola l'hash SHA256 durante il download e lo confronta prima di lanciare l'installer (mismatch →
  file scartato, errore). Release senza `.sha256` (≤ 1.6.3): procede senza verifica, warning nel log.
- **CI release** (`.github/workflows/release.yml`): al push di un tag `vX.Y.Z` builda exe+installer su
  runner Windows e pubblica la Release. **Autosufficiente**: scarica ffmpeg/ffprobe/uv da fonti ufficiali
  (BtbN, astral), nessun `bin/` da fornire. **rubberband/sndfile inclusi di default** (scaricati da
  Breakfast Quay + libsndfile ufficiali, con smoke test `--version`: se l'exe non parte viene escluso e
  l'app usa il fallback numpy); una release tag `deps` con `rubberband-win64.zip` fa da override manuale
  (vedi `tools/make-bin-zip.ps1`). Il tag deve
  combaciare con `__version__` in `app/__init__.py`. Avvio manuale (`workflow_dispatch`) = build di prova
  senza pubblicare, con l'installer caricato come artifact.
- **Separazione stem**: click destro / "Separa file…" / drag. Modalità:
  - **Roformer 6 stem** (rof6) e **Roformer voce/strumentale** (rof, top karaoke) — via audio-separator / BS-RoFormer
  - **6hq** (ensemble Demucs htdemucs_ft+htdemucs_6s), **6**, **4**, **2** (Demucs)
  - Output wav/flac/mp3. "Separa tutti" (salta i già separati).
  - **Auto-analisi a fine separazione**: calcolo immediato di BPM, key e beat grid.
  - **Gestione motore** (menu "Opzioni ▾" accanto a Installa motore):
    - **Verifica / Ripara motore**: diagnostica e ripara solo il necessario (se torch non
      si carica reinstalla il solo torch ~2.5 GB; se il venv è rotto reinstalla tutto).
    - **Disinstalla motore**: rimozione robusta (file read-only + junction uv), libera ~3 GB.
    - **Cartella di installazione**: scegli dove installare il motore (config `stem_engine_dir`;
      es. su un altro disco). Offre di rimuovere il vecchio motore per liberare spazio.
    - Il venv 3.12 si crea con lo **stdlib `venv`** del Python scaricato da uv (niente trampolino
      uv → niente os error 2/448 sui sistemi con "redirection trust"). Installazione idempotente
      con auto-riparazione di torch corrotto (WinError 127).
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
  - **Karaoke / testi sincronizzati**: se LRCLIB fornisce `syncedLyrics` (formato LRC) viene salvato in
    `lyrics.lrc` e la scheda evidenzia la riga corrente (arancione, centrata con auto-scroll) seguendo la
    riproduzione del mixer (segnale `MixerTab.position_changed`, emesso dal `_tick` a ~40ms; l'highlight
    lavora solo al cambio riga e con scheda visibile). Nei risultati di ricerca manuale i brani
    sincronizzati sono marcati con 🎤. Parser LRC in `app/ui_lyrics.py::parse_lrc` (testato).
    **Click su una riga karaoke = seek** a quel punto del brano (segnale `seek_requested` →
    `MixerTab.seek_seconds`; cursore a manina in modalità karaoke).
  - **Match LRCLIB per durata**: `song_loaded` ora porta anche la durata del brano; tra i risultati
    di ricerca vince quello con durata vicina (±3s, poi ±15s), a parità il sincronizzato
    (`pick_best_lyrics`, testato). Evita di scaricare il testo del brano sbagliato.
  - Salvataggio locale in `lyrics.txt` (+ `lyrics.lrc` se sincronizzato) per il caricamento offline immediato.
  - Visualizzazione formattata e centrata (sezioni come `[Chorus]` evidenziate in arancione).
  - Ricerca manuale dei testi e editor integrato per modificare/salvare correzioni locali
    (in modalità karaoke l'editor lavora sul file LRC grezzo, timestamp inclusi).
- **Accordatore** (dialog dal pulsante "🎼 Accordatore" nel mixer): tono di riferimento A440 / corde
  chitarra+basso e **accordatore dal microfono** (pitch via autocorrelazione FFT, niente Qt nel core).
- **UI responsive**: la scheda Scarica passa da due colonne (largo) a colonna unica impilata (< 900 px),
  niente più sovrapposizioni su monitor piccoli (vedi `MainWindow._apply_layout`). Il **mixer** usa
  `FlowLayout` (`app/flowlayout.py`) su toolbar, card analisi, presenza e barra controlli: i blocchi
  vanno a capo da soli su schermi stretti (testato fino a 560 px, niente sforamento orizzontale).

## Architettura chiave
- Main app gira su **Python 3.14** (PyInstaller onedir → `dist/Sonora/Sonora.exe`).
- **Motore stem isolato**: PyTorch non ha CUDA su 3.14 → venv **Python 3.12 + torch cu124 + demucs +
  audio-separator + librosa + pyloudnorm**, di default in `%APPDATA%/Sonora/stem-engine/` (cartella
  personalizzabile via `stem_engine_dir`). uv (`bin/uv.exe`) scarica solo il Python 3.12; il venv si
  crea con lo stdlib `venv` (niente trampolino uv). Richiamato come subprocess. GPU: RTX 3060 6GB.
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
- `pip install -r requirements-dev.txt` poi `python -m pytest` (23 test, moduli a logica pura:
  app_update versioni/asset, timestretch, mixer_engine, analyze_script detect_key, logging). Girano anche in CI
  (`.github/workflows/tests.yml`) su push/PR a main. Niente GUI/rubberband richiesti.

## Comandi
- Dev: `python run.py`
- Build exe: `python -m PyInstaller build.spec --noconfirm` → `dist/Sonora/Sonora.exe`
- Installer: `"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\sonora.iss` → `dist_installer/SonoraSetup-1.6.3.exe`

## DA FARE (idee proposte, scelta utente)
- **Firma installer**: senza firma Windows SmartScreen mostra "editore sconosciuto" (anche durante
  l'auto-update). Certificato OV ~100-400€/anno. (Rimandato: nessuna firma per ora.)

## Fatto di recente
- **Fix stem "demucs codice 1" (1.6.5)**: il subprocess del motore veniva lanciato senza `cwd`
  esplicito → se la working-dir era la cartella del bundle PyInstaller (piena di `.pyd` di
  Python 3.14), `python -m demucs` avvelenava `sys.path` e il venv 3.12 crashava all'import di torch
  («Module use of python314.dll conflicts», exit 1 in ~2s). Ora `_stream` forza `cwd=engine_dir`
  (`_safe_cwd`) e `_env` ripulisce `PYTHONPATH`/`PYTHONHOME` e toglie `sys._MEIPASS` dal `PATH`.
  Inoltre: `_run_demucs`/`_run_roformer` **catturano e mostrano il vero errore** (basta "codice 1"
  muto) e il retry ora riduce davvero la VRAM (`--segment 4`, niente `--shifts`) con **fallback su
  CPU** come ultima spiaggia (utile su GPU con poca memoria, es. GTX 1660 6 GB). Include anche il
  fix `update_repo` vuoto nei settings vecchi (era post-1.6.4, non arrivava alla build installata).
- **Rubberband nelle build CI**: caricato `rubberband-win64.zip` nella release `deps` → la CI lo include
  automaticamente (le build dalla 1.6.2 in poi usano Rubberband R3, non il fallback numpy).
- **Gestione motore stem** (1.6.0→1.6.2): Verifica/Ripara, Disinstalla, Cartella personalizzata,
  fix creazione venv (stdlib venv, niente trampolino uv), auto-riparazione torch.
- **Fix freeze EQ mixer**: `_apply_eq` (ui_mixer.py) ora calcola l'EQ (FFT full-file) su `QThread`
  dedicato (`EqWorker`, stesso pattern di `TransformWorker`) invece che sul thread UI al rilascio
  slider — niente più freeze 100-300ms su brani lunghi.
- **Test coverage stems.py**: nuovo `tests/test_stems.py` (29 test) su path motore, fix junction 448
  (`_normalize_pyvenv_home`), disinstallazione robusta, escalation `repair_engine`, path/file stem.
- **Disinstaller con pulizia dati opzionale**: `installer/sonora.iss` mostra un dialog custom
  (checkbox) prima della disinstallazione — se spuntato rimuove anche `%APPDATA%/Sonora` (config,
  cronologia, sessioni) e il motore stem, anche se installato in una cartella personalizzata
  (`stem_engine_dir` letto da `settings.json`). Nessun dialog in disinstallazione silenziosa
  (`/VERYSILENT`): di default i dati restano.

## Note
- **Log**: `%APPDATA%/Sonora/sonora.log` (rotante, 1MB×4) — crash non gestiti (excepthook),
  download/separazioni fallite, errori auto-update. Inizializzato in `main.py` via `app/logging_setup.py`.
- Settings/cronologia/analysis/sessioni mixer in `%APPDATA%/Sonora/`.
- Inno Setup installato in `%LOCALAPPDATA%\Programs\Inno Setup 6\` (non nel path di default).
- Build + installer 1.5.5 rigenerati e deploy testato funzionante (giugno 2026).
