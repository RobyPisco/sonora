"""Test del motore di mix (logica pura: gain, EQ, caricamento, render offline)."""

import numpy as np
import soundfile as sf

from app.mixer_engine import MixerEngine, Track, db_to_gain


def test_db_to_gain():
    assert db_to_gain(0.0) == 1.0
    assert abs(db_to_gain(20.0) - 10.0) < 1e-6
    assert abs(db_to_gain(-6.0) - 0.5012) < 1e-3


def test_track_defaults():
    t = Track("v", np.zeros((10, 2), dtype="float32"))
    assert t.gain_db == 0.0 and not t.mute and not t.solo
    assert t.pan == 0.0
    assert t.eq_low == t.eq_mid == t.eq_high == 0.0


def test_eq_curve_flat_is_unity():
    eng = MixerEngine()
    eng.sr = 44100
    H = eng._eq_curve(2048, 0.0, 0.0, 0.0)
    np.testing.assert_allclose(H, 1.0, atol=1e-6)


def test_eq_curve_boost_raises_gain():
    eng = MixerEngine()
    eng.sr = 44100
    H = eng._eq_curve(4096, 12.0, 0.0, 0.0)  # boost bassi
    # la prima banda (DC/bassi) deve essere amplificata (>1)
    assert H[1] > 1.5


def _write_wav(path, data, sr=44100):
    sf.write(str(path), data.astype("float32"), sr)


def test_load_files_pads_and_stereoizes(tmp_path):
    mono = (np.ones(1000, dtype="float32") * 0.1)
    stereo = np.zeros((500, 2), dtype="float32")
    p1 = tmp_path / "a.wav"
    p2 = tmp_path / "b.wav"
    _write_wav(p1, mono)
    _write_wav(p2, stereo)

    eng = MixerEngine()
    eng.load_files([("a", str(p1)), ("b", str(p2))])
    assert len(eng.tracks) == 2
    # tutte le tracce stereo e paddate alla lunghezza massima (1000)
    assert eng.n_frames == 1000
    for t in eng.tracks:
        assert t.data.shape == (1000, 2)
    eng.close()


def test_render_mix_solo_only_audible(tmp_path):
    a = np.ones((400, 2), dtype="float32") * 0.2
    b = np.ones((400, 2), dtype="float32") * 0.2
    pa, pb = tmp_path / "a.wav", tmp_path / "b.wav"
    _write_wav(pa, a)
    _write_wav(pb, b)

    eng = MixerEngine()
    eng.load_files([("a", str(pa)), ("b", str(pb))])
    eng.set_solo(0, True)        # solo sulla traccia 0
    mix, sr = eng.render_mix()
    assert mix is not None and sr == 44100
    # con un solo attivo il mix non deve essere nullo
    assert float(np.max(np.abs(mix))) > 0.0
    eng.close()


def test_render_mix_all_muted_is_silent(tmp_path):
    a = np.ones((400, 2), dtype="float32") * 0.2
    pa = tmp_path / "a.wav"
    _write_wav(pa, a)
    eng = MixerEngine()
    eng.load_files([("a", str(pa))])
    eng.set_mute(0, True)
    mix, _ = eng.render_mix()
    assert float(np.max(np.abs(mix))) == 0.0
    eng.close()
