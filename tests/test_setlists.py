"""Test di app/setlists.py: CRUD scalette e persistenza."""

from __future__ import annotations

from app import setlists


def test_create_rename_delete():
    sl = []
    assert setlists.create(sl, "Prove")
    assert not setlists.create(sl, "Prove")      # duplicato
    assert not setlists.create(sl, "   ")        # nome vuoto
    assert setlists.rename(sl, "Prove", "Prove martedì")
    assert setlists.find(sl, "Prove") is None
    assert not setlists.rename(sl, "inesistente", "X")
    assert setlists.delete(sl, "Prove martedì")
    assert sl == []


def test_rename_su_nome_esistente_rifiutato():
    sl = []
    setlists.create(sl, "A")
    setlists.create(sl, "B")
    assert not setlists.rename(sl, "A", "B")
    assert setlists.rename(sl, "A", "A")         # stesso nome: ok (no-op)


def test_add_remove_folder():
    sl = []
    setlists.create(sl, "Prove")
    assert setlists.add_folder(sl, "Prove", "C:/brano1")
    assert setlists.add_folder(sl, "Prove", "C:/brano2")
    assert not setlists.add_folder(sl, "Prove", "C:/brano1")   # duplicato
    assert not setlists.add_folder(sl, "altra", "C:/x")        # scaletta ignota
    assert setlists.find(sl, "Prove")["folders"] == ["C:/brano1", "C:/brano2"]
    assert setlists.remove_folder(sl, "Prove", "C:/brano1")
    assert not setlists.remove_folder(sl, "Prove", "C:/brano1")
    assert setlists.find(sl, "Prove")["folders"] == ["C:/brano2"]


def test_load_save_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(setlists.config, "config_dir", lambda: tmp_path)
    assert setlists.load() == []
    data = [{"name": "Prove", "folders": ["C:/brano1"]}]
    setlists.save(data)
    assert setlists.load() == data


def test_load_scarta_voci_malformate(tmp_path, monkeypatch):
    monkeypatch.setattr(setlists.config, "config_dir", lambda: tmp_path)
    (tmp_path / "setlists.json").write_text(
        '[{"name": "Ok", "folders": ["a", 3]}, {"folders": []}, "x"]',
        encoding="utf-8")
    assert setlists.load() == [{"name": "Ok", "folders": ["a"]}]
