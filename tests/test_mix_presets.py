"""Test di app/mix_presets.py: stati derivati dai preset e persistenza."""

from __future__ import annotations

from app import mix_presets


def test_states_for_applica_override_e_neutro():
    st = mix_presets.states_for({"vocals": {"mute": True}},
                                ["vocals", "drums", "bass"])
    assert st["vocals"]["mute"] is True
    assert st["drums"] == mix_presets.neutral_state()
    assert st["bass"]["gain"] == 0 and st["bass"]["solo"] is False


def test_states_for_eq_parziale_e_chiavi_ignote():
    st = mix_presets.states_for(
        {"bass": {"eq": {"low": 6}, "sconosciuta": 1}}, ["bass"])
    assert st["bass"]["eq"] == {"low": 6, "mid": 0, "high": 0}
    assert "sconosciuta" not in st["bass"]


def test_states_for_stem_non_presenti_nel_brano():
    # preset con override su uno stem che il brano non ha: nessun errore
    st = mix_presets.states_for({"piano": {"mute": True}}, ["vocals", "other"])
    assert set(st) == {"vocals", "other"}


def test_builtin_overrides():
    assert mix_presets.builtin_overrides("Karaoke (senza voce)") == {
        "vocals": {"mute": True}}
    assert mix_presets.builtin_overrides("inesistente") is None
    assert len(mix_presets.builtin_names()) == len(mix_presets.BUILTINS)


def test_load_save_user_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(mix_presets.config, "config_dir", lambda: tmp_path)
    assert mix_presets.load_user() == {}
    data = {"Mio preset": {"drums": {"gain": -6}}}
    mix_presets.save_user(data)
    assert mix_presets.load_user() == data


def test_load_user_file_corrotto(tmp_path, monkeypatch):
    monkeypatch.setattr(mix_presets.config, "config_dir", lambda: tmp_path)
    (tmp_path / "mix_presets.json").write_text("{rotto", encoding="utf-8")
    assert mix_presets.load_user() == {}
