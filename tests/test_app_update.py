"""Test del confronto versioni e parsing asset di app_update."""

from app import app_update as au


def test_parse_basic():
    assert au._parse("1.5.4") == (1, 5, 4)
    assert au._parse("v1.5.4") == (1, 5, 4)
    assert au._parse("1.5.10") == (1, 5, 10)
    assert au._parse("") == (0,)
    assert au._parse(None) == (0,)


def test_is_newer():
    assert au.is_newer("1.5.4", "1.5.3")
    assert au.is_newer("1.6.0", "1.5.9")
    assert au.is_newer("1.5.10", "1.5.9")        # 10 > 9 numerico, non lessicale
    assert not au.is_newer("1.5.3", "1.5.3")
    assert not au.is_newer("1.5.3", "1.5.4")
    assert not au.is_newer("1.5.3", "1.6.0")


def test_pick_installer_asset():
    assets = [
        {"name": "note.txt", "browser_download_url": "u0", "size": 1},
        {"name": "SonoraSetup-1.5.4.exe", "browser_download_url": "u1", "size": 123},
        {"name": "altro.zip", "browser_download_url": "u2", "size": 9},
    ]
    url, name, size = au._pick_installer_asset(assets)
    assert url == "u1"
    assert name == "SonoraSetup-1.5.4.exe"
    assert size == 123


def test_pick_installer_asset_none():
    assert au._pick_installer_asset([]) == ("", "", 0)
    assert au._pick_installer_asset([{"name": "x.zip"}]) == ("", "", 0)


def test_pick_sha256_asset():
    assets = [
        {"name": "SonoraSetup-1.6.4.exe", "browser_download_url": "u1", "size": 123},
        {"name": "SonoraSetup-1.6.4.exe.sha256", "browser_download_url": "u2", "size": 100},
    ]
    assert au._pick_sha256_asset(assets, "SonoraSetup-1.6.4.exe") == "u2"
    # case-insensitive sul nome
    assert au._pick_sha256_asset(assets, "sonorasetup-1.6.4.EXE") == "u2"


def test_pick_sha256_asset_missing():
    assets = [{"name": "SonoraSetup-1.6.3.exe", "browser_download_url": "u1"}]
    assert au._pick_sha256_asset(assets, "SonoraSetup-1.6.3.exe") == ""
    assert au._pick_sha256_asset(assets, "") == ""
    assert au._pick_sha256_asset([], "SonoraSetup-1.6.3.exe") == ""


def test_pick_installer_asset_skips_sha256():
    """L'asset .sha256 non deve mai essere scambiato per l'installer."""
    assets = [
        {"name": "SonoraSetup-1.6.4.exe.sha256", "browser_download_url": "u2", "size": 100},
        {"name": "SonoraSetup-1.6.4.exe", "browser_download_url": "u1", "size": 123},
    ]
    url, name, _size = au._pick_installer_asset(assets)
    assert url == "u1"
    assert name == "SonoraSetup-1.6.4.exe"


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_expected_sha256(monkeypatch):
    digest = "a" * 64
    body = f"{digest.upper()} *SonoraSetup-1.6.4.exe\n".encode()
    monkeypatch.setattr(
        au.urllib.request, "urlopen", lambda req, timeout=0: _FakeResponse(body))
    assert au._fetch_expected_sha256("http://x/f.sha256") == digest


def test_fetch_expected_sha256_invalid(monkeypatch):
    monkeypatch.setattr(
        au.urllib.request, "urlopen",
        lambda req, timeout=0: _FakeResponse(b"non sono un hash"))
    assert au._fetch_expected_sha256("http://x/f.sha256") == ""
