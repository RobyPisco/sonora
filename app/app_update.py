"""Controllo aggiornamenti dell'app via GitHub Releases.

Richiede un repository pubblicato (config `update_repo` = "owner/repo") in cui
caricare le release (con allegato l'installer/zip). Senza repo configurato la
funzione è inerte e lo segnala.
"""

from __future__ import annotations

import json
import re
import urllib.request

from . import __version__, config


def configured_repo() -> str:
    return (config.load().get("update_repo") or "").strip()


def _parse(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums) or (0,)


def is_newer(remote: str, local: str) -> bool:
    return _parse(remote) > _parse(local)


def check_latest() -> dict | None:
    """Ritorna {version, url, newer} oppure None se non configurato/errore."""
    repo = configured_repo()
    if not repo:
        return None
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url, headers={"User-Agent": "Sonora", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
            data = json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None
    tag = (data.get("tag_name") or "").lstrip("vV")
    if not tag:
        return None
    return {
        "version": tag,
        "url": data.get("html_url", f"https://github.com/{repo}/releases"),
        "newer": is_newer(tag, __version__),
    }
