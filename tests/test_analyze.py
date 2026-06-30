"""Test del rilevamento tonalità (Krumhansl) in analyze_script.

detect_key usa solo numpy (librosa è importata pigramente altrove), quindi è
testabile nell'ambiente principale alimentandolo con profili chroma sintetici."""

import numpy as np

from app import analyze_script as a


def test_detect_key_c_major():
    chroma = a.KRUMHANSL_MAJ.copy()      # profilo Do maggiore "puro"
    idx, mode, conf = a.detect_key(chroma)
    assert a.NOTES[idx] == "C"
    assert mode == "maj"
    assert conf > 0.0


def test_detect_key_g_major():
    chroma = np.roll(a.KRUMHANSL_MAJ, 7)  # tonica spostata su G (pc 7)
    idx, mode, _ = a.detect_key(chroma)
    assert a.NOTES[idx] == "G"
    assert mode == "maj"


def test_detect_key_a_minor():
    chroma = np.roll(a.KRUMHANSL_MIN, 9)  # La minore (pc 9)
    idx, mode, _ = a.detect_key(chroma)
    assert a.NOTES[idx] == "A"
    assert mode == "min"


def test_db_helper():
    assert a.db(1.0) == 0.0
    assert a.db(0.0) == -120.0           # guardia sotto soglia
    assert abs(a.db(0.5) - (-6.0206)) < 1e-3
