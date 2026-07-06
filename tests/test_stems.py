"""Test del motore stem (logica pura: path, junction fix, escalation riparazione).

Niente venv/rete reali: subprocess e pip sono monkeypatchati dove serve.
"""

import os
import stat

import pytest

from app import stems


# ---------------- percorsi motore ----------------

def test_engine_dir_default_uses_config_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(stems.config, "load", lambda: {})
    monkeypatch.setattr(stems.config, "config_dir", lambda: tmp_path)
    assert stems.engine_dir() == tmp_path / "stem-engine"


def test_engine_dir_custom_stem_engine_dir(monkeypatch, tmp_path):
    custom = tmp_path / "altro-disco"
    monkeypatch.setattr(stems.config, "load", lambda: {"stem_engine_dir": str(custom)})
    assert stems.engine_dir() == custom / "stem-engine"


def test_engine_dir_falls_back_when_config_load_raises(monkeypatch, tmp_path):
    def boom():
        raise RuntimeError("config rotta")
    monkeypatch.setattr(stems.config, "load", boom)
    monkeypatch.setattr(stems.config, "config_dir", lambda: tmp_path)
    assert stems.engine_dir() == tmp_path / "stem-engine"


def test_venv_python_windows_layout(monkeypatch, tmp_path):
    monkeypatch.setattr(stems, "engine_dir", lambda: tmp_path)
    monkeypatch.setattr(os, "name", "nt")
    assert stems.venv_python() == tmp_path / ".venv" / "Scripts" / "python.exe"


def test_torch_index_gpu_vs_cpu():
    assert "cu124" in stems._torch_index(True)
    assert "cpu" in stems._torch_index(False)


# ---------------- ready flags ----------------

def test_engine_ready_requires_marker_and_python(monkeypatch, tmp_path):
    monkeypatch.setattr(stems, "engine_dir", lambda: tmp_path)
    assert not stems.engine_ready()
    (tmp_path / "engine.ok").write_text("ok")
    assert not stems.engine_ready()   # manca ancora venv_python
    venv_py = tmp_path / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    venv_py.mkdir(parents=True)
    (venv_py / ("python.exe" if os.name == "nt" else "python")).write_text("x")
    assert stems.engine_ready()


def test_roformer_ready_requires_engine_and_marker(monkeypatch, tmp_path):
    monkeypatch.setattr(stems, "engine_dir", lambda: tmp_path)
    monkeypatch.setattr(stems, "engine_ready", lambda: True)
    assert not stems.roformer_ready()
    (tmp_path / "roformer.ok").write_text("ok")
    assert stems.roformer_ready()


# ---------------- normalizzazione pyvenv.cfg (fix junction 448) ----------------

def _make_managed_py312(engine_dir, version="3.12.7"):
    d = engine_dir / "python" / f"cpython-{version}-windows-x86_64-none"
    d.mkdir(parents=True)
    (d / "python.exe").write_text("fake exe")
    return d


def test_normalize_pyvenv_home_rewrites_junction_path(monkeypatch, tmp_path):
    engine_dir = tmp_path / "engine"
    concrete = _make_managed_py312(engine_dir)
    monkeypatch.setattr(stems, "engine_dir", lambda: engine_dir)

    venv = tmp_path / "venv"
    venv.mkdir()
    cfg = venv / "pyvenv.cfg"
    cfg.write_text(f"home = {engine_dir / 'python' / 'cpython-3.12-windows-x86_64-none'}\n"
                    "include-system-site-packages = false\n")

    changed = stems._normalize_pyvenv_home(venv)
    assert changed is True
    text = cfg.read_text()
    assert f"home = {concrete}" in text


def test_normalize_pyvenv_home_noop_if_already_concrete(monkeypatch, tmp_path):
    engine_dir = tmp_path / "engine"
    concrete = _make_managed_py312(engine_dir)
    monkeypatch.setattr(stems, "engine_dir", lambda: engine_dir)

    venv = tmp_path / "venv"
    venv.mkdir()
    cfg = venv / "pyvenv.cfg"
    cfg.write_text(f"home = {concrete}\n")

    assert stems._normalize_pyvenv_home(venv) is False


def test_normalize_pyvenv_home_missing_cfg_returns_false(tmp_path):
    venv = tmp_path / "novenv"
    venv.mkdir()
    assert stems._normalize_pyvenv_home(venv) is False


def test_managed_py312_picks_highest_version(monkeypatch, tmp_path):
    engine_dir = tmp_path / "engine"
    pydir = engine_dir / "python"
    pydir.mkdir(parents=True)
    for v in ("3.12.4", "3.12.10", "3.12.7"):
        d = pydir / f"cpython-{v}-windows-x86_64-none"
        d.mkdir()
        (d / "python.exe").write_text("x")
    monkeypatch.setattr(stems, "engine_dir", lambda: engine_dir)
    exe = stems._managed_py312()
    assert exe is not None and "3.12.7" in str(exe)   # ordine lessicografico inverso: "3.12.7" > "3.12.10" > "3.12.4"


def test_managed_py312_none_when_no_python_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(stems, "engine_dir", lambda: tmp_path / "engine")
    assert stems._managed_py312() is None


# ---------------- rimozione robusta (disinstallazione) ----------------

def test_rmtree_robust_removes_normal_dir(tmp_path):
    d = tmp_path / "to_remove"
    d.mkdir()
    (d / "f.txt").write_text("x")
    assert stems._rmtree_robust(d) is True
    assert not d.exists()


def test_rmtree_robust_handles_readonly_files(tmp_path):
    d = tmp_path / "to_remove"
    d.mkdir()
    f = d / "readonly.txt"
    f.write_text("x")
    os.chmod(f, stat.S_IREAD)
    assert stems._rmtree_robust(d) is True
    assert not d.exists()


def test_rmtree_robust_missing_path_is_ok(tmp_path):
    assert stems._rmtree_robust(tmp_path / "nope") is True


def test_uninstall_engine_calls_rmtree_robust(monkeypatch, tmp_path):
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    monkeypatch.setattr(stems, "engine_dir", lambda: engine_dir)
    assert stems.uninstall_engine() is True
    assert not engine_dir.exists()


# ---------------- path stem / analisi ----------------

def test_stems_dir_for():
    assert stems.stems_dir_for("/x/song.mp3") == __import__("pathlib").Path("/x/song - stems")


def test_already_separated_false_when_missing(tmp_path):
    assert not stems.already_separated(str(tmp_path / "song.mp3"))


def test_already_separated_true_with_audio_file(tmp_path):
    src = tmp_path / "song.mp3"
    stems_dir = tmp_path / "song - stems"
    stems_dir.mkdir()
    (stems_dir / "vocals.wav").write_text("x")
    assert stems.already_separated(str(src))


def test_already_separated_false_with_only_non_audio(tmp_path):
    src = tmp_path / "song.mp3"
    stems_dir = tmp_path / "song - stems"
    stems_dir.mkdir()
    (stems_dir / "analysis.json").write_text("{}")
    assert not stems.already_separated(str(src))


def test_load_analysis_roundtrip(tmp_path):
    (tmp_path / "analysis.json").write_text('{"bpm": 120}')
    assert stems.load_analysis(str(tmp_path)) == {"bpm": 120}


def test_load_analysis_missing_returns_none(tmp_path):
    assert stems.load_analysis(str(tmp_path)) is None


def test_load_analysis_corrupt_returns_none(tmp_path):
    (tmp_path / "analysis.json").write_text("{not json")
    assert stems.load_analysis(str(tmp_path)) is None


def test_pick_voc_inst_standard_names(tmp_path):
    (tmp_path / "vocals.wav").write_text("x")
    (tmp_path / "no_vocals.wav").write_text("x")
    voc, inst = stems._pick_voc_inst(tmp_path, ".wav")
    assert voc.name == "vocals.wav" and inst.name == "no_vocals.wav"


def test_pick_voc_inst_fallback_by_keyword(tmp_path):
    (tmp_path / "song (Vocals).wav").write_text("x")
    (tmp_path / "song (Instrumental).wav").write_text("x")
    voc, inst = stems._pick_voc_inst(tmp_path, ".wav")
    assert voc is not None and "vocal" in voc.name.lower()
    assert inst is not None and "instrument" in inst.name.lower()


def test_pick_stem_exact_name(tmp_path):
    (tmp_path / "drums.wav").write_text("x")
    f = stems._pick_stem(tmp_path, "drums", ".wav")
    assert f is not None and f.name == "drums.wav"


def test_pick_stem_fallback_by_keyword(tmp_path):
    (tmp_path / "song (Drums).wav").write_text("x")
    f = stems._pick_stem(tmp_path, "drums", ".wav")
    assert f is not None and "drums" in f.name.lower()


def test_pick_stem_vocals_ignores_no_vocals(tmp_path):
    (tmp_path / "song no_vocals.wav").write_text("x")
    assert stems._pick_stem(tmp_path, "vocals", ".wav") is None
    (tmp_path / "song vocals.wav").write_text("x")
    f = stems._pick_stem(tmp_path, "vocals", ".wav")
    assert f is not None and f.name == "song vocals.wav"


def test_pick_stem_missing_returns_none(tmp_path):
    assert stems._pick_stem(tmp_path, "piano", ".wav") is None


def test_sw6_mode_registered():
    assert "sw6" in stems.ROFORMER_MODES
    assert stems.STEMS_FOR_MODE["sw6"] == [
        "vocals", "drums", "bass", "guitar", "piano", "other"]


# ---------------- escalation riparazione motore ----------------

def test_repair_engine_full_install_when_no_venv(monkeypatch):
    monkeypatch.setattr(stems, "venv_python", lambda: __import__("pathlib").Path("/nope/python.exe"))
    called = {}
    monkeypatch.setattr(stems, "install_engine", lambda *a: called.setdefault("install", True) or True)
    ok = stems.repair_engine(lambda *_: None, lambda *_: None, lambda: False)
    assert ok is True and called.get("install") is True


def test_repair_engine_marker_only_when_torch_ok(monkeypatch, tmp_path):
    venv_py = tmp_path / "python.exe"
    venv_py.write_text("x")
    monkeypatch.setattr(stems, "venv_python", lambda: venv_py)
    monkeypatch.setattr(stems, "_check_venv_python_works", lambda: True)
    monkeypatch.setattr(stems, "_has_pip", lambda: True)
    monkeypatch.setattr(stems, "_verify_torch", lambda *a: True)
    monkeypatch.setattr(stems, "_marker", lambda: tmp_path / "engine.ok")
    called = {}
    monkeypatch.setattr(stems, "install_engine", lambda *a: called.setdefault("install", True) or True)
    monkeypatch.setattr(stems, "_force_reinstall_torch", lambda *a: called.setdefault("reinstall", True) or True)

    ok = stems.repair_engine(lambda *_: None, lambda *_: None, lambda: False)
    assert ok is True
    assert "install" not in called and "reinstall" not in called
    assert (tmp_path / "engine.ok").read_text() == "ok"


def test_repair_engine_reinstalls_torch_only_when_verify_fails(monkeypatch, tmp_path):
    venv_py = tmp_path / "python.exe"
    venv_py.write_text("x")
    monkeypatch.setattr(stems, "venv_python", lambda: venv_py)
    monkeypatch.setattr(stems, "_check_venv_python_works", lambda: True)
    monkeypatch.setattr(stems, "_has_pip", lambda: True)
    monkeypatch.setattr(stems, "_marker", lambda: tmp_path / "engine.ok")
    monkeypatch.setattr(stems, "has_nvidia", lambda: False)

    verify_calls = {"n": 0}

    def fake_verify(*a):
        verify_calls["n"] += 1
        return verify_calls["n"] > 1   # fallisce la prima volta, ok dopo il reinstall

    monkeypatch.setattr(stems, "_verify_torch", fake_verify)
    called = {}
    monkeypatch.setattr(stems, "_force_reinstall_torch",
                         lambda *a: called.setdefault("reinstall", True) or True)
    monkeypatch.setattr(stems, "install_engine", lambda *a: called.setdefault("install", True) or True)

    ok = stems.repair_engine(lambda *_: None, lambda *_: None, lambda: False)
    assert ok is True
    assert called.get("reinstall") is True
    assert "install" not in called   # non serve la reinstallazione completa


def test_repair_engine_falls_back_to_full_install_when_torch_repair_fails(monkeypatch, tmp_path):
    venv_py = tmp_path / "python.exe"
    venv_py.write_text("x")
    monkeypatch.setattr(stems, "venv_python", lambda: venv_py)
    monkeypatch.setattr(stems, "_check_venv_python_works", lambda: True)
    monkeypatch.setattr(stems, "_has_pip", lambda: True)
    monkeypatch.setattr(stems, "_verify_torch", lambda *a: False)
    monkeypatch.setattr(stems, "has_nvidia", lambda: False)
    monkeypatch.setattr(stems, "_force_reinstall_torch", lambda *a: False)
    called = {}
    monkeypatch.setattr(stems, "install_engine", lambda *a: called.setdefault("install", True) or True)

    ok = stems.repair_engine(lambda *_: None, lambda *_: None, lambda: False)
    assert ok is True and called.get("install") is True


# ---------------- progress multi-passo ----------------

def test_step_progress_rimappa_sul_totale():
    """Passo 2 di 3: lo 0-100% locale diventa 33-66% sul totale."""
    seen = []
    cb = stems._step_progress(seen.append, 1, 3)
    cb(0.0)
    cb(50.0)
    cb(100.0)
    assert [round(v, 1) for v in seen] == [33.3, 50.0, 66.7]


def test_step_progress_clampa_fuori_range():
    seen = []
    cb = stems._step_progress(seen.append, 0, 2)
    cb(-10.0)
    cb(150.0)
    assert seen == [0.0, 50.0]
