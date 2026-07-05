"""Test del changelog «Novità» (filtro versioni + coerenza con la release)."""

from app import __version__, changelog


def test_latest_entry_matches_app_version():
    # guardiano: a ogni release il changelog VA aggiornato — se il bump di
    # __version__ non ha una voce corrispondente, questo test lo ricorda.
    assert changelog.CHANGELOG[0][0] == __version__


def test_entries_are_sorted_newest_first():
    versions = [changelog._parse(v) for v, _ in changelog.CHANGELOG]
    assert versions == sorted(versions, reverse=True)


def test_entries_since_filters_older():
    entries = changelog.entries_since("1.2.0")
    versions = [v for v, _ in entries]
    assert "1.2.0" not in versions and "1.0.0" not in versions
    assert all(changelog._parse(v) > changelog._parse("1.2.0") for v in versions)


def test_entries_since_empty_returns_all():
    assert changelog.entries_since("") == list(changelog.CHANGELOG)


def test_entries_since_current_returns_nothing():
    assert changelog.entries_since(__version__) == []


def test_as_html_contains_versions_and_notes():
    html = changelog.as_html(changelog.CHANGELOG[:2])
    for ver, notes in changelog.CHANGELOG[:2]:
        assert f"Versione {ver}" in html
        for n in notes:
            assert n in html
