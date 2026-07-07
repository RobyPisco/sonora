"""Test di app/diagnostics.py: report e creazione zip, senza GUI né nvidia-smi."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app import __version__, diagnostics


FAKE_LICENSE = ["Licenza: licensed (300 giorni rimanenti)", "ID dispositivo: ABC123"]


def test_info_text_contiene_versione_e_sezioni(monkeypatch):
    # licenza finta: la vera contatta il Worker al primo avvio (no rete nei test)
    monkeypatch.setattr(diagnostics, "_license_lines", lambda: FAKE_LICENSE)
    txt = diagnostics.info_text({"stem_mode": "6hq"})
    assert __version__ in txt
    assert "--- Motore stem ---" in txt
    assert "--- Impostazioni ---" in txt
    assert '"stem_mode": "6hq"' in txt


def test_info_text_non_include_token_licenza(monkeypatch):
    # nel report finisce solo lo stato licenza, mai il token firmato
    monkeypatch.setattr(diagnostics, "_license_lines", lambda: FAKE_LICENSE)
    txt = diagnostics.info_text({})
    assert "token" not in txt.lower()


def test_export_zip_crea_zip_con_report_e_log(tmp_path, monkeypatch):
    # isola config e log su cartelle temporanee
    cfg_dir = tmp_path / "appdata"
    cfg_dir.mkdir()
    monkeypatch.setattr(diagnostics.config, "config_dir", lambda: cfg_dir)
    (cfg_dir / "settings.json").write_text(
        json.dumps({"stem_mode": "6hq"}), encoding="utf-8")
    (cfg_dir / "sonora.log").write_text("riga di log", encoding="utf-8")
    (cfg_dir / "sonora.log.1").write_text("log ruotato", encoding="utf-8")
    monkeypatch.setattr(diagnostics, "_nvidia_smi", lambda: "GPU FINTA")
    monkeypatch.setattr(diagnostics, "_license_lines", lambda: ["Licenza: test"])

    out = diagnostics.export_zip(tmp_path)

    assert out.exists() and out.name.startswith("Sonora-diagnostica-")
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert {"diagnostica.txt", "settings.json",
                "sonora.log", "sonora.log.1"} <= names
        report = zf.read("diagnostica.txt").decode("utf-8")
        assert "GPU FINTA" in report
        assert __version__ in report


def test_export_zip_senza_settings_e_log(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "vuota"
    cfg_dir.mkdir()
    monkeypatch.setattr(diagnostics.config, "config_dir", lambda: cfg_dir)
    monkeypatch.setattr(diagnostics, "_nvidia_smi", lambda: "n/d")
    monkeypatch.setattr(diagnostics, "_license_lines", lambda: ["Licenza: test"])

    out = diagnostics.export_zip(tmp_path)

    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["diagnostica.txt"]


def test_desktop_dir_esiste():
    d = diagnostics.desktop_dir()
    assert isinstance(d, Path) and d.exists()
