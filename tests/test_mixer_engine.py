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


def test_render_mix_exclude_leaves_track_out(tmp_path):
    a = np.ones((400, 2), dtype="float32") * 0.2
    b = np.ones((400, 2), dtype="float32") * 0.2
    pa, pb = tmp_path / "a.wav", tmp_path / "b.wav"
    _write_wav(pa, a)
    _write_wav(pb, b)
    eng = MixerEngine()
    eng.load_files([("a", str(pa)), ("b", str(pb))])
    both, _ = eng.render_mix()
    only_b, _ = eng.render_mix(exclude="a")
    # senza "a" il mix deve essere più basso, ma non muto (c'è ancora "b")
    assert 0.0 < float(np.max(np.abs(only_b))) < float(np.max(np.abs(both)))
    eng.close()


def test_render_mix_full_ignores_mute_and_solo(tmp_path):
    a = np.ones((400, 2), dtype="float32") * 0.2
    pa = tmp_path / "a.wav"
    _write_wav(pa, a)
    eng = MixerEngine()
    eng.load_files([("a", str(pa))])
    eng.set_mute(0, True)
    silent, _ = eng.render_mix()               # mutata → silenzio
    full, _ = eng.render_mix(full=True)        # full → la traccia c'è comunque
    assert float(np.max(np.abs(silent))) == 0.0
    assert float(np.max(np.abs(full))) > 0.0
    eng.close()


def test_arm_count_in_requires_beats(tmp_path):
    a = np.ones((44100, 2), dtype="float32") * 0.2
    pa = tmp_path / "a.wav"
    _write_wav(pa, a)
    eng = MixerEngine()
    eng.load_files([("a", str(pa))])
    assert eng.arm_count_in(4) is False        # niente beat → non si arma
    eng.set_beats([0.5, 1.0, 1.5, 2.0])        # ~120 bpm
    assert eng.arm_count_in(2) is True
    eng.close()


def test_count_in_plays_before_audio_without_advancing(tmp_path):
    # traccia con audio riconoscibile (0.5) preceduta dal count-in
    a = np.ones((44100, 2), dtype="float32") * 0.5
    pa = tmp_path / "a.wav"
    _write_wav(pa, a)
    eng = MixerEngine()
    eng.load_files([("a", str(pa))])
    eng.set_beats([0.5, 1.0, 1.5, 2.0])
    assert eng.arm_count_in(2) is True
    eng._playing = True                         # simula il play senza aprire lo stream
    frames = 1024
    out = np.zeros((frames, 2), dtype="float32")
    eng._render(out, frames)
    assert eng._pos == 0                         # durante il conteggio la playhead resta ferma
    assert float(np.max(np.abs(out))) > 0.0      # ma si sente il click
    for _ in range(2000):                        # esaurisci il conteggio
        eng._render(out, frames)
        if eng._pos > 0:
            break
    assert eng._pos > 0                          # poi parte l'audio
    eng.close()


def test_loop_count_in_injects_on_wrap(tmp_path):
    a = np.ones((44100, 2), dtype="float32") * 0.2
    pa = tmp_path / "a.wav"
    _write_wav(pa, a)
    eng = MixerEngine()
    eng.load_files([("a", str(pa))])
    eng.set_beats([0.5, 1.0, 1.5, 2.0])
    eng.set_loop_count_in(1)
    assert eng._loop_countin is not None
    eng.set_loop(0.0, 0.01, True)                # loop cortissimo → wrap subito
    eng._playing = True
    out = np.zeros((1024, 2), dtype="float32")
    eng._render(out, 1024)                        # attraversa loop_b → arma il count-in
    assert eng._countin is not None
    eng.set_loop_count_in(0)                       # disattiva
    eng._regen_loop_countin()
    assert eng._loop_countin is None
    eng.close()
