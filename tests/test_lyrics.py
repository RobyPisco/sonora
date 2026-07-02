"""Test del parser LRC e della scelta risultati LRCLIB (modalità karaoke)."""

from app.ui_lyrics import parse_lrc, pick_best_lyrics


def test_parse_lrc_basic():
    text = "[00:12.34] Prima riga\n[00:45.60] Seconda riga"
    lines = parse_lrc(text)
    assert lines == [(12.34, "Prima riga"), (45.60, "Seconda riga")]


def test_parse_lrc_no_centesimi():
    assert parse_lrc("[01:05] Riga") == [(65.0, "Riga")]


def test_parse_lrc_millisecondi():
    lines = parse_lrc("[00:10.500] Riga")
    assert lines == [(10.5, "Riga")]


def test_parse_lrc_timestamp_multipli():
    """[t1][t2]testo = stessa riga ripetuta a due tempi (ritornelli)."""
    lines = parse_lrc("[00:10.00][01:20.00] Ritornello")
    assert lines == [(10.0, "Ritornello"), (80.0, "Ritornello")]


def test_parse_lrc_ignora_metadata_e_righe_vuote():
    text = "[ar: Queen]\n[ti: Bohemian Rhapsody]\n\nSenza timestamp\n[00:01.00] Ok"
    assert parse_lrc(text) == [(1.0, "Ok")]


def test_parse_lrc_riga_strumentale_vuota():
    """Timestamp senza testo (pausa strumentale) va tenuto, testo vuoto."""
    assert parse_lrc("[00:30.00]") == [(30.0, "")]


def test_parse_lrc_ordina_per_tempo():
    text = "[01:00.00] Dopo\n[00:10.00] Prima"
    lines = parse_lrc(text)
    assert [t for t, _ in lines] == [10.0, 60.0]


def test_parse_lrc_vuoto():
    assert parse_lrc("") == []
    assert parse_lrc(None) == []


def _item(name, plain="testo", synced="", duration=0):
    return {"trackName": name, "plainLyrics": plain,
            "syncedLyrics": synced, "duration": duration}


def test_pick_best_preferisce_durata_vicina():
    """Brano da 200s: il risultato a 201s vince su quello a 350s anche se
    quest'ultimo è sincronizzato (durata lontana = probabile brano sbagliato)."""
    data = [
        _item("sbagliato", synced="[00:01.00] x", duration=350),
        _item("giusto", duration=201),
    ]
    assert pick_best_lyrics(data, 200)["trackName"] == "giusto"


def test_pick_best_synced_a_parita_di_durata():
    data = [
        _item("plain", duration=200),
        _item("sync", synced="[00:01.00] x", duration=201),
    ]
    assert pick_best_lyrics(data, 200)["trackName"] == "sync"


def test_pick_best_senza_durata_vince_synced():
    data = [
        _item("plain", duration=350),
        _item("sync", synced="[00:01.00] x", duration=350),
    ]
    assert pick_best_lyrics(data, 0)["trackName"] == "sync"


def test_pick_best_scarta_risultati_vuoti():
    data = [
        _item("vuoto", plain="", synced="", duration=200),
        _item("pieno", duration=200),
    ]
    assert pick_best_lyrics(data, 200)["trackName"] == "pieno"
    assert pick_best_lyrics([_item("vuoto", plain="")], 200) is None
    assert pick_best_lyrics([], 200) is None
