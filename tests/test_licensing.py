"""Test della logica di licenza (app/licensing.py).

Coprono verifica firma token, transizioni di stato prova/licenza e il parsing
degli esiti di attivazione. La rete è mockata; nessuna chiamata reale al Worker.
"""

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app import licensing


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


# --- helper: firma token con la privata corrispondente alla pubblica di test ---

@pytest.fixture()
def signer(monkeypatch):
    """Sostituisce la chiave pubblica del modulo con una coppia di test."""
    priv = Ed25519PrivateKey.generate()
    raw_pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    monkeypatch.setattr(licensing, "_PUBKEY",
                        Ed25519PublicKey.from_public_bytes(raw_pub))

    def make(machine="M1", code="AAAA-BBBB", exp_delta=7 * 86400):
        payload = {"code": code, "machine": machine,
                   "iss": int(time.time()), "exp": int(time.time()) + exp_delta}
        p_b64 = _b64u(json.dumps(payload).encode())
        return p_b64 + "." + _b64u(priv.sign(p_b64.encode("ascii")))

    return make


def test_machine_id_stable():
    assert licensing.machine_id() == licensing.machine_id()
    assert len(licensing.machine_id()) == 32


def test_token_valid_right_machine(signer):
    tok = signer(machine="M1")
    assert licensing.token_valid(tok, "M1")


def test_token_invalid_wrong_machine(signer):
    tok = signer(machine="M1")
    assert not licensing.token_valid(tok, "OTHER")


def test_token_invalid_expired(signer):
    tok = signer(machine="M1", exp_delta=-10)
    assert not licensing.token_valid(tok, "M1")


def test_token_invalid_tampered(signer):
    tok = signer(machine="M1")
    assert not licensing.token_valid(tok[:-4] + "AAAA", "M1")


def test_token_invalid_garbage(signer):
    assert not licensing.token_valid("not-a-token", "M1")


def test_status_licensed(signer, monkeypatch):
    tok = signer(machine="MID", exp_delta=5 * 86400)
    monkeypatch.setattr(licensing, "machine_id", lambda: "MID")
    monkeypatch.setattr(licensing, "load_state", lambda: {"token": tok})
    st = licensing.status()
    assert st.state == "licensed"
    assert st.days_left >= 4


def test_status_trial_active(monkeypatch):
    monkeypatch.setattr(licensing, "machine_id", lambda: "MID")
    monkeypatch.setattr(licensing, "load_state", lambda: {})
    monkeypatch.setattr(licensing, "_reg_read_trial_start", lambda: None)
    monkeypatch.setattr(licensing, "_reg_write_trial_start", lambda ts: None)
    monkeypatch.setattr(licensing, "_server_trial_start", lambda mid: None)
    monkeypatch.setattr(licensing, "save_state", lambda s: None)
    # prova iniziata "adesso"
    st = licensing.status()
    assert st.state == "trial"
    assert st.days_left == licensing.TRIAL_DAYS


def test_status_trial_expired(monkeypatch):
    old = time.time() - (licensing.TRIAL_DAYS + 1) * 86400
    monkeypatch.setattr(licensing, "machine_id", lambda: "MID")
    monkeypatch.setattr(licensing, "load_state", lambda: {"trial_start": old})
    monkeypatch.setattr(licensing, "_reg_read_trial_start", lambda: None)
    monkeypatch.setattr(licensing, "_reg_write_trial_start", lambda ts: None)
    monkeypatch.setattr(licensing, "_server_trial_start", lambda mid: None)
    monkeypatch.setattr(licensing, "save_state", lambda s: None)
    st = licensing.status()
    assert st.state == "expired"
    assert st.days_left == 0


def test_activate_in_use(monkeypatch):
    monkeypatch.setattr(licensing, "machine_id", lambda: "MID")
    monkeypatch.setattr(licensing, "_post",
                        lambda path, body: {"ok": False, "reason": "in_use"})
    res = licensing.activate("AAAA-BBBB")
    assert not res.ok
    assert "altro dispositivo" in res.message


def test_activate_network_error(monkeypatch):
    monkeypatch.setattr(licensing, "machine_id", lambda: "MID")

    def boom(path, body):
        raise licensing.NetworkError("offline")

    monkeypatch.setattr(licensing, "_post", boom)
    res = licensing.activate("AAAA-BBBB")
    assert not res.ok
    assert "connessione" in res.message.lower()


def test_activate_success(signer, monkeypatch):
    tok = signer(machine="MID", code="AAAA-BBBB")
    monkeypatch.setattr(licensing, "machine_id", lambda: "MID")
    monkeypatch.setattr(licensing, "save_state", lambda s: None)
    monkeypatch.setattr(licensing, "load_state", lambda: {})
    monkeypatch.setattr(licensing, "_post",
                        lambda path, body: {"ok": True, "token": tok})
    res = licensing.activate("aaaa-bbbb")
    assert res.ok
