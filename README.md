# Sonora

**Italiano** · [English](#english)

![windows](https://img.shields.io/badge/Windows-10%2F11-blue) ![gui](https://img.shields.io/badge/GUI-PySide6-green) ![prezzo](https://img.shields.io/badge/prezzo-gratuito-orange)

App desktop per Windows che **separa un brano nei suoi strumenti** e ti fa **esercitare** sopra: mixer di pratica, visualizzatore di testi e accordatore. Tutto in locale, sul tuo PC.

### ⬇️ [Scarica l'ultima versione](https://github.com/RobyPisco/sonora/releases/latest)

Apri l'installer e vai: al primo uso Sonora prepara da sola il motore di separazione.

---

## Cosa fa

**Separazione in stem**
- Carica un file audio che hai già (mp3, wav, flac, m4a, opus) e ottieni tracce separate: **voce, batteria, basso, chitarra, piano, altro**.
- Motori **Demucs** (2 / 4 / 6 stem e 6 HQ) e **Roformer** (voce/strumentale per il karaoke, oppure 6 stem in cascata).
- Accelerazione su **GPU NVIDIA** quando c'è; altrimenti lavora il processore.

**Mixer — lo studio di pratica**
- Volume, mute, solo, pan ed **EQ a 3 bande** per ogni traccia, con forme d'onda colorate.
- **Velocità 50–150%** senza alterare l'intonazione e **trasposizione ±6 semitoni**, in tempo reale (Rubberband R3).
- **Loop A-B** e **loop progressivo**: parte lento e accelera da solo finché il passaggio non ti riesce.
- **Punti del brano** con nome, **preset** di mix (karaoke, senza basso, senza batteria…) e **scalette** per le prove.
- **Analisi**: BPM, tonalità, LUFS, beat, accordi e sezioni del brano; poi timeline a misure, metronomo e pre-conteggio.
- Il mix si salva da solo per ogni brano: riapri il pezzo e ritrovi tutto com'era.

**Esporta**
- Mix unico, tutti gli stem separati, oppure **basi «senza una traccia»** (NO_VOCE, NO_BASSO…) su cui suonare.

**Testi e accordatore**
- Testi cercati in automatico (database libero LRCLIB), anche **sincronizzati**: la riga corrente si illumina, click su una riga per saltarci.
- Toni di riferimento (A440, corde di chitarra e basso) e **accordatore dal microfono**.

## Requisiti

- Windows 10 o 11 (64 bit).
- Al primo uso Sonora scarica il motore di separazione: **~3 GB**, una volta sola.
- GPU NVIDIA consigliata ma non necessaria.

## Privacy

Tutto il lavoro avviene **sul tuo computer**: i file non vengono caricati da nessuna parte. Sonora esce su internet solo per scaricare il motore al primo uso, cercare i testi e controllare gli aggiornamenti.

## Prezzo

Sonora è **gratuito**, senza funzioni a pagamento e senza scadenze. Se ti è utile puoi [offrire una donazione](https://www.paypal.com/cgi-bin/webscr?cmd=_donations&business=roberto.pisconti%40gmail.com&item_name=Sostieni%20Sonora&currency_code=EUR&amount=10&no_shipping=1): sostiene lo sviluppo e, se vuoi, ti dà un codice facoltativo che toglie il messaggio di benvenuto.

## Problemi o idee

Scrivi a **roberto.pisconti@gmail.com** — dall'app: Impostazioni → Motore stem → «Esporta diagnostica» crea uno zip da allegare.

---

<a name="english"></a>

# Sonora (English)

Windows desktop app that **splits a song into its instruments** and lets you **practice** over them: a practice mixer, a lyrics viewer and a tuner. Everything runs locally on your PC.

### ⬇️ [Download the latest version](https://github.com/RobyPisco/sonora/releases/latest)

Run the installer and you're set: on first use Sonora sets up the separation engine by itself.

## What it does

**Stem separation**
- Load an audio file you already have (mp3, wav, flac, m4a, opus) and get separate tracks: **vocals, drums, bass, guitar, piano, other**.
- **Demucs** (2 / 4 / 6 stems and 6 HQ) and **Roformer** (vocals/instrumental for karaoke, or 6 stems in cascade) engines.
- **NVIDIA GPU** accelerated when available; otherwise the CPU does the work.

**Mixer — the practice studio**
- Volume, mute, solo, pan and a **3-band EQ** per track, with colored waveforms.
- **Speed 50–150%** without changing pitch and **±6 semitone transpose**, in real time (Rubberband R3).
- **A-B loop** and **progressive loop**: starts slow and speeds up on its own until the passage clicks.
- Named **song points**, mix **presets** (karaoke, no bass, no drums…) and **setlists** for rehearsals.
- **Analysis**: BPM, key, LUFS, beats, chords and song sections; then a bars/beats timeline, metronome and count-in.
- The mix saves itself per song: reopen the track and everything is as you left it.

**Export**
- A single mix, all stems separately, or **"minus one" backing tracks** (NO_VOCE, NO_BASSO…) to play along with.

**Lyrics and tuner**
- Lyrics fetched automatically (the free LRCLIB database), **synced** when available: the current line lights up, click a line to jump there.
- Reference tones (A440, guitar and bass strings) and a **microphone tuner**.

## Requirements

- Windows 10 or 11 (64-bit).
- On first use Sonora downloads the separation engine: **~3 GB**, once.
- An NVIDIA GPU is recommended but not required.

## Privacy

Everything happens **on your computer**: your files are never uploaded. Sonora only goes online to fetch the engine on first use, look up lyrics and check for updates.

## Price

Sonora is **free**, with no paid features and no expiry. If you find it useful you can [donate](https://www.paypal.com/cgi-bin/webscr?cmd=_donations&business=roberto.pisconti%40gmail.com&item_name=Sostieni%20Sonora&currency_code=EUR&amount=10&no_shipping=1): it supports development and, if you like, gives you an optional code that hides the welcome message.

## Problems or ideas

Write to **roberto.pisconti@gmail.com** — in the app: Settings → Stem engine → "Export diagnostics" creates a zip to attach.
