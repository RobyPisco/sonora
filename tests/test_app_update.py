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
