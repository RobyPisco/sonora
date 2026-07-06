"""Novità per versione, mostrate all'utente («Cosa c'è di nuovo»).

Aggiorna QUESTO file a ogni release: voci in italiano, dal punto di vista
dell'utente (niente dettagli tecnici). Ordine: dalla più recente.
Il dialogo appare al primo avvio dopo un aggiornamento (vedi ui.py) e resta
consultabile dal pulsante «Novità» in Impostazioni → Aggiornamenti.
"""

from __future__ import annotations

import re

# (versione, [novità]) — la più recente in cima.
CHANGELOG: list[tuple[str, list[str]]] = [
    ("1.7.0", [
        "La barra del player in basso ora compare solo dove serve: sempre "
        "nei Testi, altrove solo mentre gira un'operazione lunga (con il "
        "suo progresso).",
        "Nelle separazioni a più passi la barra di avanzamento va da 0 a "
        "100 sul lavoro totale, senza più ripartire da zero a ogni passo.",
        "Meno errori di memoria sulla scheda video: se la GPU non ce la fa, "
        "Sonora riprova da sola con impostazioni più leggere e al limite "
        "usa il processore (più lento ma affidabile).",
    ]),
    ("1.6.0", [
        "Testi tutto nuovo: ricerca molto più efficace — prova più strategie "
        "insieme e ripulisce da sola i titoli YouTube («(Official Video)», "
        "codici tra parentesi…).",
        "Nuova libreria dei testi: col pulsante «Salva» tieni da parte un "
        "testo e lo ritrovi quando vuoi dal pulsante «Libreria», anche senza "
        "il brano caricato.",
        "Rimossa la modalità karaoke: il testo è sempre semplice e leggibile; "
        "i vecchi testi sincronizzati vengono convertiti da soli.",
    ]),
    ("1.5.5", [
        "Risolto: l'analisi BPM/tonalità falliva sulle canzoni con parentesi "
        "quadre nel titolo (es. video YouTube «Titolo [ID]»).",
        "Se l'analisi non trova gli stem ora te lo dice chiaramente, invece "
        "di restare in silenzio.",
    ]),
    ("1.5.2", [
        "Testi: ricerca più precisa con artista e titolo separati, e nuovo "
        "pulsante «Esporta» per salvare il testo.",
        "Ricerca video: puoi ascoltare un'anteprima (~20 secondi) dei "
        "risultati prima di aggiungerli alla coda.",
    ]),
    ("1.5.0", [
        "Interfaccia tutta nuova: barra laterale a icone al posto delle "
        "schede, barra di riproduzione sempre visibile in basso e pagina "
        "Impostazioni dedicata (motore stem, aggiornamenti, licenza).",
        "Avvisi più discreti: piccole notifiche al posto delle finestre "
        "che interrompevano il lavoro.",
        "Nuova finestra «Novità» (questa!): dopo ogni aggiornamento ti "
        "racconta cosa è cambiato. La ritrovi quando vuoi in Impostazioni → "
        "Aggiornamenti.",
    ]),
    ("1.4.0", [
        "Nuovo export «Basi senza una traccia»: un mix completo per ogni "
        "strumento escluso (NO_VOCE, NO_BASSO, …) — perfetto per farci "
        "pratica sopra, anche con click e count-in.",
    ]),
    ("1.3.0", [
        "Export rinnovato: puoi esportare tutti gli stem come file separati, "
        "con velocità e tono attuali applicati, in una cartella dedicata.",
        "Scelta WAV o MP3 direttamente nel dialogo di esportazione.",
        "Nomi file più chiari: esportando un solo stem il file si chiama "
        "«BASSO - titolo», con la trasposizione nel nome (es. +1st).",
        "L'analisi BPM/tonalità non parte più da sola dopo la separazione: "
        "la lanci tu dal Mixer col pulsante «Analizza».",
    ]),
    ("1.2.0", [
        "Menu delle modalità di separazione riorganizzato: si capisce subito "
        "quante tracce ottieni e con quale motore.",
    ]),
    ("1.1.0", [
        "Nuova modalità di separazione «Roformer SW»: batteria, basso, "
        "chitarra e piano molto più puliti, in un solo passaggio.",
        "Pulsanti − / + accanto al cursore del tono nel Mixer per cambiare "
        "di un semitono al volo.",
    ]),
    ("1.0.1", [
        "Pulsante «Attiva» sempre a portata di mano nel footer, per inserire "
        "il codice anche durante la prova.",
    ]),
    ("1.0.0", [
        "Primo rilascio: download da YouTube, separazione stem, Mixer per la "
        "pratica, accordatore e testi. Prova gratuita di 3 giorni.",
    ]),
]


def _parse(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums) or (0,)


def entries_since(last_seen: str) -> list[tuple[str, list[str]]]:
    """Le voci più nuove di last_seen (tutte se last_seen è vuota/ignota)."""
    if not last_seen:
        return list(CHANGELOG)
    ref = _parse(last_seen)
    return [(v, notes) for v, notes in CHANGELOG if _parse(v) > ref]


def as_html(entries: list[tuple[str, list[str]]]) -> str:
    """Rende le voci in HTML per il dialogo «Novità»."""
    parts: list[str] = []
    for ver, notes in entries:
        parts.append(f"<h3 style='margin:10px 0 4px'>Versione {ver}</h3>")
        items = "".join(f"<li style='margin:2px 0'>{n}</li>" for n in notes)
        parts.append(f"<ul style='margin:0 0 6px 18px'>{items}</ul>")
    return "".join(parts)
