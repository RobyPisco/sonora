"""Preset di mix riusabili tra brani.

Un preset descrive, per nome stem (vocals/drums/bass/…), le differenze dallo
stato neutro del mixer (volume/pan/mute/solo/EQ). Applicarlo = riportare tutte
le tracce al neutro e sovrapporre le differenze: così lo stesso preset funziona
su qualunque brano, anche con set di stem diversi.

I preset predefiniti sono fissi nel codice; quelli dell'utente vivono in
%APPDATA%/Sonora/mix_presets.json.
"""

from __future__ import annotations

import json
from typing import Any

from . import config

# (nome, override per stem) — l'ordine è quello del menu
BUILTINS: list[tuple[str, dict[str, dict[str, Any]]]] = [
    ("Karaoke (senza voce)", {"vocals": {"mute": True}}),
    ("Senza basso", {"bass": {"mute": True}}),
    ("Senza batteria", {"drums": {"mute": True}}),
    ("Solo ritmica (batteria+basso)", {"drums": {"solo": True},
                                       "bass": {"solo": True}}),
    ("Voce guida (bassa)", {"vocals": {"gain": -12}}),
]


def neutral_state() -> dict[str, Any]:
    """Stato neutro di una traccia (stesso schema di TrackStrip.state())."""
    return {"gain": 0, "pan": 0.0, "mute": False, "solo": False,
            "eq": {"low": 0, "mid": 0, "high": 0}}


def states_for(overrides: dict[str, dict[str, Any]],
               track_names: list[str]) -> dict[str, dict[str, Any]]:
    """Stato completo per ogni traccia: neutro + override del preset."""
    out: dict[str, dict[str, Any]] = {}
    for name in track_names:
        st = neutral_state()
        ov = overrides.get(name)
        if isinstance(ov, dict):
            for k, v in ov.items():
                if k == "eq" and isinstance(v, dict):
                    st["eq"].update(v)
                elif k in st:
                    st[k] = v
        out[name] = st
    return out


def _user_path():
    return config.config_dir() / "mix_presets.json"


def load_user() -> dict[str, dict[str, dict[str, Any]]]:
    """Preset dell'utente: {nome: {stem: override}}. Vuoto se assente/corrotto."""
    p = _user_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


def save_user(presets: dict[str, dict[str, dict[str, Any]]]) -> None:
    try:
        _user_path().write_text(
            json.dumps(presets, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def builtin_names() -> list[str]:
    return [name for name, _ov in BUILTINS]


def builtin_overrides(name: str) -> dict[str, dict[str, Any]] | None:
    for n, ov in BUILTINS:
        if n == name:
            return ov
    return None
