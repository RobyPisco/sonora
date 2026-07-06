# Sonora — stato progetto (ripresa lavori)

App desktop Windows: **YouTube audio downloader + separazione stem + mixer/studio di pratica + accordatore + visualizzatore testi**.
Path progetto: `C:\xampp\htdocs\sonora`. Python **3.14** + PySide6. Tutto salvato su disco e allineato su GitHub.
Versione corrente: **1.5.5** (fix: cartelle stem con `[]` nel nome (es. video YouTube "Titolo [ID] - stems") facevano fallire "Analizza" — `glob` in `analyze_script.py` trattava le parentesi quadre come character-class invece che testo letterale, ora `glob.escape()` sulla cartella; 1.5.4: fix "Analizza" non segnalava errore quando l'analisi tornava senza stem trovati — ora `stems.analyze()` solleva se il JSON contiene `error`; 1.5.2: Testi: ricerca artista/titolo separati su LRCLIB, cancellazione ricerca senza freeze, pulsante Esporta; ricerca video: anteprima audio (~20s) sui risultati prima di aggiungerli alla coda; 1.5.1: fix icone SVG mancanti nel pacchetto PyInstaller; 1.5.0: redesign completo UI, vedi sotto; 1.4.0: basi «senza una traccia»; 1.3.0: export stem separati/WAV-MP3 + niente auto-analisi; 1.2.0: menu modalità stem riorganizzato; 1.1.0: Roformer SW 6 stem + pulsanti ±semitono nel Mixer; allineata in `app/__init__.py`, `installer/sonora.iss` e GitHub).

**Redesign UI 1.5.0** (luglio 2026): shell nuova — rail laterale a icone (`app/ui_shell.py`)
al posto delle tab, **playbar globale** in basso (`app/ui_playbar.py`: brano, play/pausa, seek,
chip attività per stem/motore/update), pagina **Impostazioni** (`app/ui_settings.py`: Download /
Motore stem / Aggiornamenti / Licenza — motore e yt-dlp spostati qui dal tab Scarica).
Design token centralizzati in `app/theme.py` (COLORS/STEM_COLORS/FONT_SIZES; il QSS
`resources/style.qss` è templato con `@tok(nome)` risolti da `theme.load_qss()`); icone SVG
tintabili in `resources/icons/` via `app/icons.py`; stati attivi dei bottoni via dynamic
property `accent` + `:checked` nel QSS (niente più `setStyleSheet` runtime). Popup informativi
sostituiti da **toast/banner** (`app/toast.py`); attivazione licenza **non bloccante** (QThread
in `app/ui_license.py`, con auto-formattazione del codice). Scarica ridisegnata: hero centrale
con campo unico cerca/incolla + chip opzioni (formato/stem/normalizza/altre opzioni a
scomparsa), log in disclosure; trasporto Mixer a **gruppi etichettati** su FlowLayout (va a
capo su finestre strette), play tondo 46px con icona play/pausa.

**Licenza/attivazione (dalla 1.0.0)**: prova 3 giorni, poi codice per cliente. Anti-condivisione un-codice-un-PC
via Worker Cloudflare (`worker/`, live su `sonora-license.piscofactory.workers.dev`), che firma un token Ed25519
verificato offline dall'app. Core in `app/licensing.py`, dialog `app/ui_license.py`, gate in `app/main.py`.
Gestione codici via `POST /admin/*` (vedi `worker/README.md`). Segreti solo sul Worker, mai nel repo.

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
  - **Roformer SW 6 stem** (sw6, BS-Roformer-SW: 6 stem in un passaggio, top per gli strumenti),
    **Roformer 6 stem** (rof6, cascade: top voce) e **Roformer voce/strumentale** (rof, top karaoke) — via audio-separator / BS-RoFormer
  - **6hq** (ensemble Demucs htdemucs_ft+htdemucs_6s), **6**, **4**, **2** (Demucs)
  - Output wav/flac/mp3. "Separa tutti" (salta i già separati).
  - NB: l'opzione "voce asciutta" (de-reverb `deverb_bs_roformer` post-separazione) è stata
    provata e SCARTATA: il modello taglia la voce in alcuni punti. Non riproporla.
  - Niente auto-analisi a fine separazione (rimossa su richiesta): BPM/key/beat si
    calcolano dal Mixer col pulsante «Analizza», a discrezione dell'utente.
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
  - **Export "Esporta…"** (dialogo unico con scelta WAV/MP3 a pulsante):
    - **Mix unico**: bounce con volumi/mute/solo/pan/EQ + velocità/pitch applicati (opzione click
      e count-in). Stem mutati nel prefisso (es. `NO_BASSO - …`); se è udibile UN solo stem il
      nome diventa `BASSO - titolo (+1st).wav`.
    - **Tutti gli stem**: un file per traccia, PURI (solo velocità/tono applicati, niente
      volume/pan/EQ), in sottocartella automatica `stems +1st [75%]/` con nomi `VOCE - titolo.ext`.
    - **Basi «senza una traccia» (minus one)**: un mix COMPLETO per ogni stem escluso
      (ignora mute/solo, conserva volumi/pan/EQ/velocità/tono; click/count-in opzionali),
      in sottocartella `basi senza una traccia [+1st]/` con nomi `NO_VOCE - titolo.ext`.
      Render pigro nel worker (un mix alla volta in RAM).
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
- Installer: `"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\sonora.iss` → `dist_installer/SonoraSetup-1.0.0.exe`

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
