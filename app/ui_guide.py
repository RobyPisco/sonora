"""Pagina Guida: manuale d'uso di Sonora, consultabile offline.

Il contenuto è HTML statico renderizzato in un QTextBrowser: niente rete,
niente dipendenze. L'indice in cima usa ancore interne (QTextBrowser le
gestisce da solo); i colori arrivano dai design token di theme.py.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QTextBrowser, QVBoxLayout, QWidget

from . import __version__, theme

CONTENT_MAX_W = 1000


def _css() -> str:
    c = theme.COLORS
    return f"""
        body {{ color: {c['text']}; font-size: 14px; }}
        h1 {{ font-size: 26px; color: {c['text']}; margin-bottom: 2px; }}
        h2 {{ font-size: 20px; color: {c['accent']}; margin-top: 26px; }}
        h3 {{ font-size: 15px; color: {c['text']}; margin-top: 16px; }}
        p, li {{ line-height: 140%; }}
        a {{ color: {c['info']}; text-decoration: none; }}
        b {{ color: {c['text']}; }}
        .muted {{ color: {c['muted']}; }}
        .kbd {{ font-family: 'Cascadia Code', Consolas, monospace;
               color: {c['solo']}; }}
        table {{ margin: 8px 0; }}
        td {{ padding: 3px 14px 3px 0; }}
    """


def _html() -> str:
    c = theme.COLORS
    K = lambda s: f"<span class='kbd'>{s}</span>"  # noqa: E731 — tasto
    return f"""
<h1>Guida di Sonora</h1>
<p class="muted">Versione {__version__} · scarica, separa in stem, suonaci sopra.</p>

<p><b>Indice:</b>
<a href="#flusso">Come funziona</a> ·
<a href="#scarica">Scarica</a> ·
<a href="#stem">Separazione in stem</a> ·
<a href="#mixer">Mixer</a> ·
<a href="#export">Esporta</a> ·
<a href="#testi">Testi</a> ·
<a href="#accordatore">Accordatore</a> ·
<a href="#impostazioni">Impostazioni</a> ·
<a href="#scorciatoie">Scorciatoie</a> ·
<a href="#problemi">Problemi?</a></p>

<h2><a name="flusso"></a>Come funziona Sonora</h2>
<p>Il flusso tipico è in tre mosse:</p>
<ol>
<li><b>Scarica</b> un brano da YouTube (o carica un file audio che hai già).</li>
<li><b>Separalo in stem</b>: voce, batteria, basso, chitarra, piano, altro —
    ogni strumento diventa una traccia indipendente.</li>
<li>Aprilo nel <b>Mixer</b> e fai pratica: togli il tuo strumento e suona tu
    al suo posto, rallenta i passaggi difficili, mettili in loop, trasponi
    nella tua tonalità.</li>
</ol>
<p>In più: <b>Testi</b> scarica e mostra il testo del brano (anche sincronizzato,
stile karaoke) e l'<b>Accordatore</b> ti tiene lo strumento a posto.</p>

<h2><a name="scarica"></a>Scarica</h2>
<p>La pagina principale ha un unico campo: <b>incolla un link</b> YouTube
(video o playlist) oppure <b>scrivi cosa cerchi</b> e premi Invio — appaiono
i risultati con copertina e durata, e puoi ascoltarne un'<b>anteprima</b>
prima di aggiungerli alla coda.</p>
<ul>
<li><b>Formati</b>: mp3, m4a, opus, flac, wav (chip sotto il campo di ricerca).
    Con «Normalizza volume» il file esce a volume uniforme.</li>
<li><b>File locali</b>: trascina un audio nella finestra (o «Carica file»)
    per separarlo in stem senza passare da YouTube.</li>
<li><b>Coda</b>: scarica più brani in sequenza; tasto destro su una riga per
    riprovare, aprire la cartella o separare in stem. «Rimuovi completati»
    pulisce le righe finite (restano in Cronologia).</li>
<li><b>Monitor appunti</b>: se attivo (Impostazioni), copiando un link
    YouTube Sonora lo propone da solo.</li>
</ul>

<h2><a name="stem"></a>Separazione in stem</h2>
<p>Tasto destro su un brano scaricato → <b>«Separa in stem»</b>, oppure
«Separa file…» per un audio qualsiasi. La prima volta Sonora installa il
<b>motore di separazione</b> (~3 GB, una tantum); con una scheda video NVIDIA
la separazione è molto più veloce, altrimenti lavora il processore.</p>
<h3>Quale modalità scegliere?</h3>
<table>
<tr><td><b>Roformer SW — 6 stem</b></td>
    <td>La migliore per gli <b>strumenti</b> (batteria, basso, chitarra,
    piano molto puliti), in un solo passaggio.</td></tr>
<tr><td><b>Roformer — 6 stem</b></td>
    <td>La migliore per la <b>voce</b>; più lenta (più passaggi).</td></tr>
<tr><td><b>Roformer — voce/strumentale</b></td>
    <td>Solo 2 tracce, perfetta per il <b>karaoke</b>.</td></tr>
<tr><td><b>Demucs 6 HQ / 6 / 4 / 2</b></td>
    <td>Alternative classiche, dal massimo dettaglio (6 HQ, lenta) alla
    più rapida (2 stem).</td></tr>
</table>
<p>«Separa tutti» elabora in fila tutti i brani della coda <b>non ancora
separati</b> (i già fatti vengono saltati). L'output può essere wav, flac
o mp3.</p>

<h2><a name="mixer"></a>Mixer — lo studio di pratica</h2>
<p>Apri una cartella di stem (pulsante «Recenti» o dal tasto destro sulla
coda) e ogni strumento diventa una <b>striscia</b> con la sua forma d'onda.</p>
<h3>Tracce</h3>
<ul>
<li><b>Volume, Mute, Solo, Pan</b> per ogni traccia — {K('1')}…{K('6')}
    silenziano la traccia, {K('Shift+1')}…{K('6')} la mettono in solo.</li>
<li><b>EQ a 3 bande</b> (Bassi/Medi/Alti) per traccia.</li>
<li>Il mix (fader, pan, velocità, tono…) si <b>salva da solo per brano</b>:
    riapri il pezzo e ritrovi tutto com'era.</li>
</ul>
<h3>Velocità e tono</h3>
<ul>
<li><b>Velocità</b> 50–150% senza cambiare l'intonazione: rallenta i passaggi
    difficili e riportali a tempo un po' alla volta.</li>
<li><b>Trasposizione</b> ±6 semitoni (pulsanti −/+) per suonare nella tua
    tonalità senza riaccordare lo strumento.</li>
</ul>
<h3>Loop A-B e loop progressivo</h3>
<ul>
<li>{K('A')} e {K('B')} fissano l'inizio e la fine del passaggio,
    {K('L')} attiva il loop.</li>
<li><b>«Auto↑»</b> è il loop progressivo: parte lento (es. 60%) e accelera
    di qualche punto percentuale ogni N ripetizioni, fino al 100%. Il modo
    più efficace di imparare un passaggio veloce.</li>
</ul>
<h3>Punti del brano</h3>
<p>Il gruppo <b>«PUNTI»</b> salva marcatori con nome («assolo», «bridge
difficile»…) o interi loop A-B: appaiono come bandierine sulla timeline e
si richiamano con un click o con {K('Ctrl+1')}…{K('9')}. Restano salvati
per brano.</p>
<h3>Preset e scalette</h3>
<ul>
<li><b>«Preset»</b>: mix pronti (Karaoke, Senza basso, Senza batteria, Solo
    ritmica, Voce guida) più i tuoi preset personali, validi su ogni brano.</li>
<li><b>«Scalette»</b>: raggruppa i brani per le prove o il repertorio e
    scorrili con {K('Ctrl+→')} / {K('Ctrl+←')}; ogni brano si apre già
    con il suo mix.</li>
</ul>
<h3>Analisi, timeline e metronomo</h3>
<ul>
<li><b>«Analizza»</b> calcola BPM, tonalità e scala, volume percepito (LUFS),
    gamma dinamica, stabilità del tempo e presenza di ogni strumento.</li>
<li>Dopo l'analisi la <b>timeline</b> mostra misure e beat, il
    <b>metronomo</b> fa il click sui beat (segue anche la velocità) e le
    <b>sezioni del brano</b> (strofa, ritornello…) diventano pulsanti per
    saltare o loopare una sezione.</li>
<li><b>«Conteggio»</b> (pre-conteggio): al Play parte una battuta di click a
    tempo e poi entra il brano, così arrivi pronto sull'attacco. Scegli quante
    battute e, volendo, fallo ripetere a ogni giro del loop.</li>
<li><b>Zoom</b> delle forme d'onda con +/− o {K('Ctrl+rotella')};
    trascina sulla timeline per spostarti nel brano.</li>
</ul>

<h2><a name="export"></a>Esporta</h2>
<p>Il pulsante <b>«Esporta…»</b> (WAV o MP3) offre tre uscite:</p>
<table>
<tr><td><b>Mix unico</b></td>
    <td>Il mix così come lo senti: volumi, mute, pan, EQ, velocità e tono
    applicati. Opzionali click del metronomo e count-in. Se resta udibile
    un solo stem il file si chiama es. <i>BASSO - titolo (+1st)</i>.</td></tr>
<tr><td><b>Tutti gli stem</b></td>
    <td>Un file per traccia, puliti (solo velocità/tono applicati), in una
    sottocartella dedicata.</td></tr>
<tr><td><b>Basi «senza una traccia»</b></td>
    <td>Un mix completo per ogni strumento escluso (<i>NO_VOCE</i>,
    <i>NO_BASSO</i>, …): le basi su cui fare pratica, anche con click e
    count-in.</td></tr>
</table>

<h2><a name="testi"></a>Testi</h2>
<ul>
<li>Al caricamento di un brano nel Mixer, Sonora cerca il testo <b>da sola</b>
    (database libero LRCLIB) scegliendo il risultato con la durata giusta.</li>
<li>Se esiste il testo <b>sincronizzato</b>, la riga corrente si illumina e
    scorre da sola seguendo la riproduzione; <b>click su una riga = salti</b>
    a quel punto del brano.</li>
<li>Ricerca manuale (artista e titolo separati), <b>editor</b> integrato per
    correggere il testo e <b>libreria</b> locale: i testi salvati restano
    disponibili anche offline.</li>
</ul>

<h2><a name="accordatore"></a>Accordatore</h2>
<p>Dal pulsante «Accordatore» nel Mixer: <b>toni di riferimento</b> (A440 e
corde di chitarra e basso) oppure <b>accordatore dal microfono</b>, con nota
rilevata e scostamento in cent.</p>

<h2><a name="impostazioni"></a>Impostazioni</h2>
<ul>
<li><b>Download</b>: cartella di destinazione, sottocartella per brano,
    metadata e copertina, monitor appunti, notifiche.</li>
<li><b>Motore stem</b>: installa/verifica/ripara/disinstalla il motore,
    scegli la cartella (anche su un altro disco), aggiorna yt-dlp ed
    <b>esporta la diagnostica</b> (zip sul Desktop da allegare quando
    chiedi assistenza).</li>
<li><b>Aspetto</b>: «Dimensione interfaccia» per ingrandire testi e pulsanti
    (effetto al riavvio).</li>
<li><b>Aggiornamenti</b>: Sonora controlla da sola le nuove versioni e
    aggiorna con un click; qui trovi anche il pulsante «Novità».</li>
<li><b>Licenza</b>: stato della prova (3 giorni) e attivazione del codice.
    Un codice vale per un PC.</li>
</ul>

<h2><a name="scorciatoie"></a>Scorciatoie da tastiera (Mixer)</h2>
<table>
<tr><td>{K('Spazio')}</td><td>Riproduci / pausa</td></tr>
<tr><td>{K('Home')}</td><td>Torna all'inizio</td></tr>
<tr><td>{K('←')} / {K('→')}</td><td>Indietro/avanti di 1 secondo
    (tieni premuto per scorrere)</td></tr>
<tr><td>{K('Shift+←')} / {K('Shift+→')}</td><td>Indietro/avanti di 5 secondi</td></tr>
<tr><td>{K('A')} / {K('B')}</td><td>Fissa il punto A / B del loop</td></tr>
<tr><td>{K('L')}</td><td>Attiva/disattiva il loop A-B</td></tr>
<tr><td>{K('1')}…{K('6')}</td><td>Mute della traccia 1…6</td></tr>
<tr><td>{K('Shift+1')}…{K('6')}</td><td>Solo della traccia 1…6</td></tr>
<tr><td>{K('Ctrl+1')}…{K('9')}</td><td>Richiama il punto salvato 1…9</td></tr>
<tr><td>{K('Ctrl+→')} / {K('Ctrl+←')}</td><td>Brano successivo/precedente
    della scaletta</td></tr>
<tr><td>{K('Ctrl+rotella')}</td><td>Zoom delle forme d'onda</td></tr>
</table>

<h2><a name="problemi"></a>Qualcosa non va?</h2>
<ul>
<li><b>La separazione fallisce o il motore non parte</b>: Impostazioni →
    Motore stem → «Verifica / Ripara motore» sistema da solo la maggior
    parte dei problemi.</li>
<li><b>Metronomo o griglia beat non si accendono</b>: serve prima
    l'analisi del brano (pulsante «Analizza» nel Mixer).</li>
<li><b>Il download fallisce</b>: prova «Aggiorna yt-dlp» in Impostazioni →
    Motore stem (YouTube cambia spesso).</li>
<li><b>Per chiedere aiuto</b>: Impostazioni → Motore stem →
    «Esporta diagnostica» crea uno zip sul Desktop con le informazioni
    utili all'assistenza — allegalo alla richiesta.</li>
</ul>
<p class="muted" style="margin-top:20px">Sonora v{__version__} — buona musica! 🎸</p>
"""


class GuidePage(QWidget):
    """Pagina «Guida»: manuale utente renderizzato in un QTextBrowser."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Root")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        container = QWidget()
        container.setMaximumWidth(CONTENT_MAX_W)
        outer.addWidget(container, 20)
        outer.addStretch(1)

        lay = QVBoxLayout(container)
        lay.setContentsMargins(32, 24, 32, 16)

        view = QTextBrowser()
        view.setObjectName("GuideView")
        view.setOpenExternalLinks(False)   # solo ancore interne
        view.setFrameShape(QTextBrowser.Shape.NoFrame)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.document().setDefaultStyleSheet(_css())
        view.setHtml(_html())
        lay.addWidget(view, 1)
