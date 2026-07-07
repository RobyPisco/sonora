# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Progetto

Sonora: app desktop Windows (Python 3.14 + PySide6) per scaricare audio da YouTube, separarlo in stem e fare pratica con un mixer (velocità/tono/loop A-B), visualizzatore testi e accordatore. Lingua del progetto: **italiano** (UI, commit, documentazione). Lo stato dettagliato e la cronologia delle release sono in `STATO-PROGETTO.md` — va aggiornato a ogni release.

## Comandi

- Avvio dev: `python run.py` (servono `bin/ffmpeg.exe` e `bin/ffprobe.exe`; `bin/uv.exe` per installare il motore stem)
- Test: `python -m pytest` (suite veloce, solo logica pura — niente GUI né rubberband)
- Singolo test: `python -m pytest tests/test_stems.py -k nome_test`
- Build exe: `python -m PyInstaller build.spec --noconfirm` → `dist/Sonora/Sonora.exe`
- Installer: `& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\sonora.iss` → `dist_installer/SonoraSetup-X.Y.Z.exe`

## Release

Push di un tag `vX.Y.Z` su main → GitHub Actions (`.github/workflows/release.yml`) builda exe+installer e pubblica la Release (autosufficiente: scarica ffmpeg/uv/rubberband da fonti ufficiali). Il tag DEVE combaciare con `__version__` in `app/__init__.py`. Checklist di bump versione:

1. `app/__init__.py` → `__version__`
2. `app/changelog.py` → nuova voce (`test_changelog.py` fallisce se manca)
3. `installer/sonora.iss` → versione
4. `STATO-PROGETTO.md` → riassunto delle modifiche
5. Commit convenzionale in italiano (es. `feat(mixer): …`), tag `vX.Y.Z`, push con tag

`workflow_dispatch` sul workflow Release = build di prova senza pubblicare.

## Architettura

**Due Python.** L'app principale gira su Python 3.14; PyTorch non ha wheel CUDA per 3.14, quindi separazione stem e analisi girano in un venv isolato Python 3.12 (torch CUDA + demucs + audio-separator + librosa) in `%APPDATA%/Sonora/stem-engine/` (personalizzabile via `stem_engine_dir`), creato al primo uso con `bin/uv.exe`. `app/stems.py` orchestra installazione, verifica/riparazione e i subprocess; `app/analyze_script.py` e `app/roformer_script.py` sono script **eseguiti dentro il venv 3.12** (non importarli dal main app). I subprocess vanno lanciati con `cwd` sicuro e `PYTHONPATH`/`PYTHONHOME` puliti (vedi `_stream`/`_env` in `stems.py`): mescolare i due Python causa conflitti di DLL.

**Mixer realtime in-process**: `mixer_engine.py` mixa gli stem con numpy + sounddevice + soundfile (sync campione-esatto). `timestretch.py` usa Rubberband R3 (`bin/rubberband.exe` + `sndfile.dll`) con fallback automatico sul phase-vocoder numpy se i binari mancano. I lavori pesanti (EQ, trasformazioni, export) girano su QThread dedicati (`EqWorker`, `TransformWorker`), mai sul thread UI.

**UI**: shell a rail laterale (`app/ui_shell.py`) + playbar globale (`app/ui_playbar.py`); pagine in `ui.py` (Scarica), `ui_mixer.py`, `ui_lyrics.py`, `ui_settings.py`. Design token centralizzati in `app/theme.py` (COLORS/STEM_COLORS/FONT_SIZES); il QSS `resources/style.qss` è templato con `@tok(nome)` risolti da `theme.load_qss()`; icone SVG tintabili via `app/icons.py`. Niente `setStyleSheet` a runtime: stati attivi via dynamic property + selettori QSS. Notifiche con toast/banner (`app/toast.py`), non popup modali.

**Licenze**: prova 3 giorni + codice di attivazione un-codice-un-PC. `app/licensing.py` verifica offline un token Ed25519 firmato dal Worker Cloudflare (`worker/`, live su workers.dev). Segreti solo sul Worker, mai nel repo.

## Vincoli e decisioni già prese

- `dist/`, `build/`, `dist_installer/` sono output generati: non modificarli e non cercarci codice sorgente.
- De-reverb «voce asciutta» (deverb_bs_roformer) provato e **scartato** (taglia la voce): non riproporlo.
- Niente auto-analisi a fine separazione (rimossa su richiesta): l'analisi parte solo dal pulsante «Analizza» nel Mixer.
- I test devono restare eseguibili senza GUI né binari esterni (girano in CI su runner Windows nudo).
