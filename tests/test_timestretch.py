"""Test del time-stretch / pitch-shift numpy (percorso fallback, senza rubberband).

I test forzano il percorso numpy disabilitando rubberband, così non dipendono
da bin/rubberband.exe (assente in CI / ambiente di test)."""

import numpy as np
import pytest

from app import timestretch as ts


@pytest.fixture(autouse=True)
def _no_rubberband(monkeypatch):
    # forza il fallback numpy: rubberband non disponibile
    monkeypatch.setattr(ts, "_get_rubberband_path", lambda: None)
    monkeypatch.setattr(ts, "rubberband_process", lambda *a, **k: None)


def _sine(n=44100, f=440, sr=44100):
    t = np.arange(n) / sr
    return (0.5 * np.sin(2 * np.pi * f * t)).astype("float32")


def test_stretch_identity_returns_same_length():
    x = _sine()
    out = ts.time_stretch(x, 1.0)
    assert out.shape == x.shape
    np.testing.assert_allclose(out, x, atol=1e-6)


def test_stretch_longer():
    x = _sine(n=22050)
    out = ts.time_stretch(x, 2.0)
    # circa il doppio dei campioni (tolleranza per il padding STFT)
    assert abs(out.shape[0] - 2 * x.shape[0]) < ts._NFFT * 2


def test_stretch_shorter():
    x = _sine(n=44100)
    out = ts.time_stretch(x, 0.5)
    assert abs(out.shape[0] - x.shape[0] // 2) < ts._NFFT * 2


def test_stretch_stereo_keeps_two_channels():
    mono = _sine(n=22050)
    x = np.stack([mono, mono], axis=1)
    out = ts.time_stretch(x, 1.5)
    assert out.ndim == 2 and out.shape[1] == 2


def test_pitch_shift_preserves_length():
    x = _sine(n=22050)
    out = ts.pitch_shift(x, 12.0)
    assert out.shape[0] == x.shape[0]


def test_pitch_shift_zero_is_identity():
    x = _sine()
    out = ts.pitch_shift(x, 0.0)
    np.testing.assert_allclose(out, x, atol=1e-6)


def test_resample_linear_target_length():
    x = _sine(n=1000)
    assert ts._resample_linear(x, 500).shape[0] == 500
    assert ts._resample_linear(x, 2000).shape[0] == 2000
