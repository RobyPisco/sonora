"""Licenza / attivazione Sonora.

Modello: prova di 3 giorni, poi attivazione online una-tantum con un codice
cliente. Il server (Cloudflare Worker) lega il codice a UN solo PC e restituisce
un token firmato Ed25519. L'app poi verifica il token OFFLINE con la chiave
pubblica qui embedded; contatta il server solo per attivare o rinnovare.

Nessuna dipendenza di rete extra: usa urllib (come app/app_update.py).
La verifica firma usa `cryptography` (Ed25519).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import config

log = logging.getLogger(__name__)

# --- Configurazione (da personalizzare dopo il deploy del Worker) ------------

# URL base del Worker Cloudflare. Sostituire con il proprio dopo il deploy.
LICENSE_API = "https://sonora-license.piscofactory.workers.dev"

# Chiave pubblica Ed25519 (base64url, senza padding). La PRIVATA corrispondente
# vive SOLO come secret del Worker e non deve mai stare nell'app.
PUBLIC_KEY_B64URL = "pOUHT9zfixLmEqk9kzbeBP8VbAua8_TkGM6-Jze4op8"

TRIAL_DAYS = 3
NET_TIMEOUT = 8          # secondi per le chiamate al Worker
# Quando il token è entro questa finestra dalla scadenza, tenta il rinnovo.
RENEW_BEFORE_S = 2 * 24 * 3600


# --- Utility base64url --------------------------------------------------------

def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


_PUBKEY = Ed25519PublicKey.from_public_bytes(_b64u_decode(PUBLIC_KEY_B64URL))


# --- Identità macchina --------------------------------------------------------

def machine_id() -> str:
    """Fingerprint stabile del PC (hash breve, non reversibile).

    Su Windows usa MachineGuid del registro + volume serial di C:.
    Altrove ripiega su uuid.getnode()+hostname (l'app è Windows-only in distro).
    """
    parts: list[str] = []
    try:
        import winreg  # noqa: PLC0415 (import locale: solo Windows)

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as k:
            guid, _ = winreg.QueryValueEx(k, "MachineGuid")
            parts.append(str(guid))
    except OSError:
        pass

    try:
        import ctypes  # noqa: PLC0415

        vol = ctypes.c_uint(0)
        ctypes.windll.kernel32.GetVolumeInformationW(  # type: ignore[attr-defined]
            "C:\\", None, 0, ctypes.byref(vol), None, None, None, 0
        )
        parts.append(str(vol.value))
    except (AttributeError, OSError):
        pass

    if not parts:
        import platform
        import uuid

        parts.append(str(uuid.getnode()))
        parts.append(platform.node())

    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:32]


# --- Stato locale (%APPDATA%/Sonora/license.json) -----------------------------

def _state_path() -> Path:
    return config.config_dir() / "license.json"


def load_state() -> dict[str, Any]:
    p = _state_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(state: dict[str, Any]) -> None:
    try:
        _state_path().write_text(
            json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        log.warning("Impossibile salvare license.json", exc_info=True)


# --- Prova: timestamp ridondante nel registro (resiste al reset del file) -----

_REG_PATH = r"Software\Sonora"
_REG_VALUE = "TrialStart"


def _reg_read_trial_start() -> float | None:
    try:
        import winreg  # noqa: PLC0415

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as k:
            v, _ = winreg.QueryValueEx(k, _REG_VALUE)
            return float(v)
    except (OSError, ValueError):
        return None


def _reg_write_trial_start(ts: float) -> None:
    try:
        import winreg  # noqa: PLC0415

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as k:
            winreg.SetValueEx(k, _REG_VALUE, 0, winreg.REG_SZ, str(ts))
    except OSError:
        pass


# --- Verifica token firmato ---------------------------------------------------
# Formato token: "<b64url(payload_json)>.<b64url(sig)>"
# payload_json: {"code": str, "machine": str, "iss": int, "exp": int}
# firma Ed25519 calcolata sui byte ASCII di "<b64url(payload_json)>".

def _parse_token(token: str) -> dict[str, Any] | None:
    try:
        p_b64, sig_b64 = token.split(".", 1)
        _PUBKEY.verify(_b64u_decode(sig_b64), p_b64.encode("ascii"))
        payload = json.loads(_b64u_decode(p_b64))
        if isinstance(payload, dict):
            return payload
    except (ValueError, InvalidSignature, json.JSONDecodeError):
        pass
    return None


def token_valid(token: str, mid: str, now: float | None = None) -> bool:
    """True se il token è firmato correttamente, per QUESTA macchina, non scaduto."""
    now = time.time() if now is None else now
    payload = _parse_token(token)
    if not payload:
        return False
    if payload.get("machine") != mid:
        return False
    exp = payload.get("exp")
    return isinstance(exp, (int, float)) and exp > now


def _token_exp(token: str) -> float | None:
    payload = _parse_token(token)
    if payload and isinstance(payload.get("exp"), (int, float)):
        return float(payload["exp"])
    return None


# --- Rete: chiamate al Worker -------------------------------------------------

class NetworkError(Exception):
    """Il server non è raggiungibile (nessuna connessione / timeout)."""


def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST JSON al Worker. Solleva NetworkError se irraggiungibile.

    Ritorna il JSON di risposta (anche per status HTTP 4xx, che portano un
    messaggio applicativo, es. codice già usato).
    """
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        LICENSE_API.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "Sonora"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"ok": False, "reason": "http_error"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise NetworkError(str(e)) from e


# --- API pubblica del modulo --------------------------------------------------

@dataclass
class Status:
    state: str          # "licensed" | "trial" | "expired"
    days_left: int      # giorni rimanenti (prova o licenza), 0 se scaduto


@dataclass
class ActivateResult:
    ok: bool
    message: str        # messaggio pronto per l'utente


def _server_trial_start(mid: str) -> float | None:
    """Chiede al Worker il first-seen della macchina. None se offline/errore."""
    try:
        resp = _post("/trial", {"machineId": mid})
    except NetworkError:
        return None
    fs = resp.get("firstSeen")
    return float(fs) if isinstance(fs, (int, float)) else None


def _ensure_trial_start(state: dict[str, Any], mid: str) -> float:
    """Determina (e persiste) l'inizio prova.

    Se esiste già un valore locale (file o registro) lo usa — nessuna rete a
    ogni avvio. Solo al PRIMO avvio (nessun valore locale) contatta il Worker
    per il first-seen server-side, così cancellare il file non azzera la prova.
    """
    local = [c for c in (state.get("trial_start"), _reg_read_trial_start())
             if isinstance(c, (int, float))]
    if local:
        ts = min(float(c) for c in local)
    else:
        server = _server_trial_start(mid)  # rete solo qui, al primo avvio
        ts = float(server) if server is not None else time.time()
    state["trial_start"] = ts
    save_state(state)
    _reg_write_trial_start(ts)
    return ts


def status() -> Status:
    """Stato corrente della licenza. Non contatta il server se non serve."""
    mid = machine_id()
    state = load_state()
    token = state.get("token")
    if isinstance(token, str) and token_valid(token, mid):
        exp = _token_exp(token) or time.time()
        return Status("licensed", max(0, int((exp - time.time()) // 86400)))

    ts = _ensure_trial_start(state, mid)
    remaining = TRIAL_DAYS - (time.time() - ts) / 86400
    if remaining > 0:
        return Status("trial", math.ceil(remaining))
    return Status("expired", 0)


def activate(code: str) -> ActivateResult:
    """Tenta l'attivazione del codice presso il Worker."""
    code = code.strip().upper()
    if not code:
        return ActivateResult(False, "Inserisci un codice.")
    mid = machine_id()
    try:
        resp = _post("/activate", {"code": code, "machineId": mid})
    except NetworkError:
        return ActivateResult(
            False, "Nessuna connessione. Verifica internet e riprova."
        )

    if resp.get("ok") and isinstance(resp.get("token"), str):
        token = resp["token"]
        if not token_valid(token, mid):
            return ActivateResult(False, "Risposta del server non valida.")
        state = load_state()
        state.update({"token": token, "code": code, "machine_id": mid,
                      "last_check": time.time()})
        save_state(state)
        return ActivateResult(True, "Attivazione completata. Grazie!")

    reason = resp.get("reason", "")
    messages = {
        "in_use": "Questo codice è già in uso su un altro dispositivo.",
        "revoked": "Questo codice è stato revocato.",
        "unknown": "Codice non valido.",
        "not_found": "Codice non valido.",
    }
    return ActivateResult(False, messages.get(reason, "Attivazione non riuscita."))


def refresh_if_needed() -> None:
    """Rinnova silenziosamente il token se online e vicino a scadenza.

    Da chiamare in background all'avvio. Se il codice è stato revocato, il
    rinnovo fallisce e il token viene rimosso (l'app tornerà a chiedere il
    codice al riavvio successivo). Fail-soft: se offline, non tocca nulla.
    """
    mid = machine_id()
    state = load_state()
    token = state.get("token")
    if not isinstance(token, str) or not token_valid(token, mid):
        return
    exp = _token_exp(token)
    if exp is None or exp - time.time() > RENEW_BEFORE_S:
        return  # ancora lontano dalla scadenza
    try:
        resp = _post("/renew", {"token": token, "machineId": mid})
    except NetworkError:
        return  # riproveremo al prossimo avvio, il token è ancora valido
    if resp.get("ok") and isinstance(resp.get("token"), str) \
            and token_valid(resp["token"], mid):
        state["token"] = resp["token"]
        state["last_check"] = time.time()
        save_state(state)
    elif resp.get("reason") in ("revoked", "in_use", "unknown", "not_found"):
        state.pop("token", None)
        save_state(state)
