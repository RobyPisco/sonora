"""Test del tab Testi: parser LRC, pulizia titoli, ricerca LRCLIB e libreria."""

from app import config, lyrics_store
from app.ui_lyrics import (
    build_lrclib_url,
    clean_title,
    lrc_to_plain,
    parse_lrc,
    pick_best_lyrics,
    plain_text_of,
    search_plan,
    split_artist_track,
)


def test_parse_lrc_basic():
    text = "[00:12.34] Prima riga\n[00:45.60] Seconda riga"
    lines = parse_lrc(text)
    assert lines == [(12.34, "Prima riga"), (45.60, "Seconda riga")]


def test_parse_lrc_no_centesimi():
    assert parse_lrc("[01:05] Riga") == [(65.0, "Riga")]


def test_parse_lrc_timestamp_multipli():
    """[t1][t2]testo = stessa riga ripetuta a due tempi (ritornelli)."""
    lines = parse_lrc("[00:10.00][01:20.00] Ritornello")
    assert lines == [(10.0, "Ritornello"), (80.0, "Ritornello")]


def test_parse_lrc_ignora_metadata_e_righe_vuote():
    text = "[ar: Queen]\n[ti: Bohemian Rhapsody]\n\nSenza timestamp\n[00:01.00] Ok"
    assert parse_lrc(text) == [(1.0, "Ok")]


def test_parse_lrc_vuoto():
    assert parse_lrc("") == []
    assert parse_lrc(None) == []


def test_lrc_to_plain():
    text = "[ar: Queen]\n[00:45.60] Seconda\n[00:12.34] Prima"
    assert lrc_to_plain(text) == "Prima\nSeconda"
    assert lrc_to_plain("") == ""


# ---------------- pulizia titoli YouTube ----------------

def test_clean_title_rimuove_rumore():
    assert clean_title("Bohemian Rhapsody (Official Video)") == "Bohemian Rhapsody"
    assert clean_title("Titolo [Official Lyric Video] (HD)") == "Titolo"


def test_clean_title_rimuove_id_youtube():
    assert clean_title("Titolo [dQw4w9WgXcQ]") == "Titolo"


def test_clean_title_rimuove_feat():
    assert clean_title("Song (feat. Someone)") == "Song"
    assert clean_title("Song ft. Someone Else") == "Song"


def test_clean_title_lascia_titoli_puliti():
    assert clean_title("Bohemian Rhapsody") == "Bohemian Rhapsody"
    assert clean_title("") == ""


# ---------------- scelta risultato migliore ----------------

def _item(name, plain="testo", synced="", duration=0):
    return {"trackName": name, "plainLyrics": plain,
            "syncedLyrics": synced, "duration": duration}


def test_pick_best_preferisce_durata_vicina():
    """Brano da 200s: il risultato a 201s vince su quello a 350s (durata
    lontana = probabile brano sbagliato)."""
    data = [
        _item("sbagliato", synced="[00:01.00] x", duration=350),
        _item("giusto", duration=201),
    ]
    assert pick_best_lyrics(data, 200)["trackName"] == "giusto"


def test_pick_best_durata_piu_vicina_vince():
    data = [
        _item("vicino", duration=200),
        _item("meno", synced="[00:01.00] x", duration=201),
    ]
    assert pick_best_lyrics(data, 200)["trackName"] == "vicino"


def test_pick_best_senza_durata_preferisce_plain():
    """Senza durata di riferimento vince chi ha già il testo semplice
    (quello solo sincronizzato andrebbe convertito)."""
    data = [
        _item("solo-sync", plain="", synced="[00:01.00] x", duration=350),
        _item("plain", duration=350),
    ]
    assert pick_best_lyrics(data, 0)["trackName"] == "plain"


def test_pick_best_scarta_risultati_vuoti():
    data = [
        _item("vuoto", plain="", synced="", duration=200),
        _item("pieno", duration=200),
    ]
    assert pick_best_lyrics(data, 200)["trackName"] == "pieno"
    assert pick_best_lyrics([_item("vuoto", plain="")], 200) is None
    assert pick_best_lyrics([], 200) is None


def test_plain_text_of_converte_synced():
    assert plain_text_of(_item("x", plain="", synced="[00:01.00] Riga")) == "Riga"
    assert plain_text_of(_item("x", plain="Diretto")) == "Diretto"
    assert plain_text_of(None) == ""


# ---------------- URL e piano di ricerca ----------------

def test_build_lrclib_url_con_artista_e_titolo():
    url = build_lrclib_url("", artist="Queen", track="Bohemian Rhapsody")
    assert "artist_name=Queen" in url
    assert "track_name=Bohemian" in url
    assert "q=" not in url


def test_build_lrclib_url_con_duration():
    url = build_lrclib_url("", artist="Queen", track="Bohemian Rhapsody", duration=354.6)
    assert "duration=355" in url


def test_build_lrclib_url_solo_titolo_ripiega_su_q():
    url = build_lrclib_url("", artist="", track="Bohemian Rhapsody")
    assert "q=Bohemian" in url
    assert "artist_name" not in url


def test_search_plan_strutturata_poi_libere():
    urls = search_plan("Queen", "Bohemian Rhapsody (Official Video)")
    # strutturata col titolo pulito per prima
    assert "artist_name=Queen" in urls[0]
    assert "Official" not in urls[0]
    # poi la query libera com'è e quella ripulita, senza doppioni
    assert any("q=" in u and "Official" in u for u in urls[1:])
    assert len(urls) == len(set(urls))


def test_search_plan_solo_titolo():
    urls = search_plan("", "Bohemian Rhapsody")
    assert all("artist_name" not in u for u in urls)
    assert len(urls) == 1   # query com'è == query pulita: niente doppione


def test_split_artist_track_con_trattino():
    assert split_artist_track("Queen - Bohemian Rhapsody") == ("Queen", "Bohemian Rhapsody")


def test_split_artist_track_senza_trattino():
    assert split_artist_track("Bohemian Rhapsody") == ("", "Bohemian Rhapsody")


# ---------------- libreria locale ----------------

def _fake_store(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)


def test_store_save_load_delete(monkeypatch, tmp_path):
    _fake_store(monkeypatch, tmp_path)
    p = lyrics_store.save("Queen - Bohemian Rhapsody", "Is this the real life?")
    assert p.exists()
    assert lyrics_store.list_all() == ["Queen - Bohemian Rhapsody"]
    assert lyrics_store.load("Queen - Bohemian Rhapsody") == "Is this the real life?"
    lyrics_store.delete("Queen - Bohemian Rhapsody")
    assert lyrics_store.list_all() == []


def test_store_nome_sanificato(monkeypatch, tmp_path):
    _fake_store(monkeypatch, tmp_path)
    p = lyrics_store.save('AC/DC: "Back in Black"?', "testo")
    assert p.name == "AC DC Back in Black.txt"
    assert lyrics_store.safe_name("") == "testo"


def test_store_sovrascrive_stesso_nome(monkeypatch, tmp_path):
    _fake_store(monkeypatch, tmp_path)
    lyrics_store.save("Brano", "vecchio")
    lyrics_store.save("Brano", "nuovo")
    assert lyrics_store.list_all() == ["Brano"]
    assert lyrics_store.load("Brano") == "nuovo"


def test_store_delete_inesistente_non_esplode(monkeypatch, tmp_path):
    _fake_store(monkeypatch, tmp_path)
    lyrics_store.delete("non esiste")
