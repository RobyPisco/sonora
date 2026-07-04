"""Genera una coppia di chiavi Ed25519 per la licenza Sonora.

Stampa:
  - PUBLIC_KEY_B64URL : da incollare in app/licensing.py (PUBLIC_KEY_B64URL)
  - SIGNING_JWK       : da impostare come secret del Worker (SIGNING_JWK)

La chiave privata (SIGNING_JWK) NON deve MAI finire nell'app né nel repo:
vive solo come secret di Cloudflare. Rigenerala per la produzione e aggiorna
entrambi i valori insieme (public nell'app, JWK sul Worker).

Uso:  python worker/gen-keys.py
"""

import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def main() -> None:
    priv = Ed25519PrivateKey.generate()
    raw_priv = priv.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    raw_pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    d, x = b64u(raw_priv), b64u(raw_pub)
    jwk = {"kty": "OKP", "crv": "Ed25519", "d": d, "x": x,
           "key_ops": ["sign"], "ext": True}

    print("PUBLIC_KEY_B64URL (in app/licensing.py):")
    print("  " + x)
    print()
    print("SIGNING_JWK (wrangler secret put SIGNING_JWK):")
    print("  " + json.dumps(jwk))


if __name__ == "__main__":
    main()
