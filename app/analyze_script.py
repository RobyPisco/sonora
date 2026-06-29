"""Analisi audio di una cartella di stem. ESEGUITO DAL VENV 3.12 del motore
(ha numpy/soundfile/librosa/pyloudnorm). Stampa JSON su stdout.

Uso: python analyze_script.py "<cartella stems>"
"""

import glob
import json
import os
import sys

import numpy as np
import soundfile as sf

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
KRUMHANSL_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KRUMHANSL_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

AUDIO_GLOBS = ("*.wav", "*.flac", "*.mp3")


def db(x):
    x = float(x)
    return 20.0 * np.log10(x) if x > 1e-9 else -120.0


def detect_key(chroma):
    chroma = chroma / (chroma.sum() + 1e-9)
    maj = (KRUMHANSL_MAJ - KRUMHANSL_MAJ.mean())
    minr = (KRUMHANSL_MIN - KRUMHANSL_MIN.mean())
    c = chroma - chroma.mean()
    best = (-1.0, 0, "maj")
    scores = []
    for i in range(12):
        rot = np.roll(c, -i)
        rmaj = float(np.dot(rot, maj) / (np.linalg.norm(rot) * np.linalg.norm(maj) + 1e-9))
        rmin = float(np.dot(rot, minr) / (np.linalg.norm(rot) * np.linalg.norm(minr) + 1e-9))
        scores.append(rmaj); scores.append(rmin)
        if rmaj > best[0]:
            best = (rmaj, i, "maj")
        if rmin > best[0]:
            best = (rmin, i, "min")
    scores.sort(reverse=True)
    conf = 0.0
    if len(scores) > 1 and scores[0] > 0:
        conf = max(0.0, min(1.0, (scores[0] - scores[1]) / (abs(scores[0]) + 1e-9)))
    return best[1], best[2], conf


def _viterbi_chords(emissions, self_bonus):
    """Viterbi su S stati con transizione uniforme + bonus di permanenza (self_bonus).
    emissions: [T, S] (più alto = meglio). Ritorna la sequenza di stati [T]."""
    t_len, s_len = emissions.shape
    if t_len == 0:
        return []
    dp = emissions[0].copy()
    back = np.zeros((t_len, s_len), dtype=np.int32)
    for t in range(1, t_len):
        gmax = float(dp.max()); garg = int(dp.argmax())
        stay = dp + self_bonus            # restare nello stesso stato k
        # per ogni stato k: meglio tra "resto in k" e "vengo dal migliore globale"
        choose_stay = stay >= gmax
        prev_best = np.where(choose_stay, stay, gmax)
        back[t] = np.where(choose_stay, np.arange(s_len), garg)
        dp = prev_best + emissions[t]
    path = np.empty(t_len, dtype=np.int32)
    path[-1] = int(dp.argmax())
    for t in range(t_len - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    return path.tolist()


def detect_sections(y, sr, duration):
    """Segmentazione strutturale del brano. Ritorna [{time, label}] con etichette
    A/B/C… condivise tra sezioni simili (utile per saltare/loopare le parti).
    Niente semantica Intro/Strofa: solo struttura affidabile."""
    import string

    import librosa
    hop = 512
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, hop_length=hop, n_mfcc=13)

    def z(x):
        return (x - x.mean(axis=1, keepdims=True)) / (x.std(axis=1, keepdims=True) + 1e-6)

    feat = np.vstack([z(chroma), z(mfcc)]).astype("float32")
    nfr = feat.shape[1]
    if nfr < 4:
        return []
    k = int(np.clip(round(duration / 22.0), 4, 10))
    k = min(k, nfr - 1)
    bounds = librosa.segment.agglomerative(feat, k)
    btimes = [float(t) for t in librosa.frames_to_time(bounds, sr=sr, hop_length=hop)]
    times = sorted(set([0.0] + btimes + [float(duration)]))
    fr = librosa.time_to_frames(times, sr=sr, hop_length=hop)

    labels = []
    ref = []   # (etichetta, vettore medio) delle sezioni già viste
    for i in range(len(times) - 1):
        a, b = int(fr[i]), max(int(fr[i + 1]), int(fr[i]) + 1)
        a = max(0, min(a, nfr - 1)); b = max(a + 1, min(b, nfr))
        m = feat[:, a:b].mean(axis=1)
        best_lbl, best_sim = None, -1.0
        for lbl, rv in ref:
            sim = float(np.dot(m, rv) / (np.linalg.norm(m) * np.linalg.norm(rv) + 1e-9))
            if sim > best_sim:
                best_sim, best_lbl = sim, lbl
        if best_sim >= 0.9 and best_lbl is not None:
            labels.append(best_lbl)
        else:
            lbl = string.ascii_uppercase[len(ref) % 26]
            ref.append((lbl, m)); labels.append(lbl)
    return [{"time": round(times[i], 3), "label": labels[i]} for i in range(len(labels))]


def detect_chords(chroma_full, sr, bt, duration):
    """Stima la sequenza di accordi (triadi maggiori/minori) per battuta tramite
    template matching sul chroma, stabilizzata con uno smoothing Viterbi (evita i
    cambi 'ballerini'). Ritorna segmenti {time, root, quality} uniti quando l'accordo
    non cambia. `bt` = tempi dei beat (s); fallback a finestre 0.5 s."""
    import librosa
    n = chroma_full.shape[1]
    ctimes = librosa.frames_to_time(np.arange(n), sr=sr)
    maj = np.zeros((12, 12)); minr = np.zeros((12, 12))
    for r in range(12):
        for o in (0, 4, 7):
            maj[r, (r + o) % 12] = 1.0
        for o in (0, 3, 7):
            minr[r, (r + o) % 12] = 1.0
    templates = np.vstack([maj, minr])
    templates /= (np.linalg.norm(templates, axis=1, keepdims=True) + 1e-9)

    bt = list(bt) if bt is not None else []
    if len(bt) >= 2:
        bounds = bt + [duration]
    else:
        bounds = list(np.arange(0.0, duration, 0.5)) + [duration]

    # 1) emission per segmento: score di correlazione coi 24 template, + maschera "ha accordo"
    emissions = []
    has_chord = []
    for i in range(len(bounds) - 1):
        s, e = bounds[i], bounds[i + 1]
        sel = (ctimes >= s) & (ctimes < e)
        if not sel.any():
            emissions.append(np.zeros(24, dtype="float32")); has_chord.append(False); continue
        vec = chroma_full[:, sel].mean(axis=1)
        nrm = float(np.linalg.norm(vec))
        if nrm < 1e-6:
            emissions.append(np.zeros(24, dtype="float32")); has_chord.append(False); continue
        scores = templates @ (vec / nrm)
        srt = np.sort(scores)[::-1]
        emissions.append(scores.astype("float32"))
        # silenzio/ambiguità → nessun accordo (il Viterbi mantiene comunque lo stato)
        has_chord.append(not (srt[0] < 0.45))

    if not emissions:
        return []
    # 2) smoothing Viterbi (self_bonus alto = più stabile)
    path = _viterbi_chords(np.vstack(emissions), self_bonus=0.25)

    # 3) costruisci i segmenti, marcando None dove non c'è accordo
    raw = []
    for i, st in enumerate(path):
        if not has_chord[i]:
            raw.append(None)
        else:
            raw.append((st % 12, "maj" if st < 12 else "min"))

    chords = []
    prev = None
    for i, item in enumerate(raw):
        if item == prev:
            continue
        prev = item
        if item is not None:
            chords.append({"time": round(float(bounds[i]), 3),
                           "root": item[0], "quality": item[1]})
    return chords


def main():
    folder = sys.argv[1]
    paths = []
    for g in AUDIO_GLOBS:
        paths += glob.glob(os.path.join(folder, g))
    paths = sorted(set(paths))
    if not paths:
        print(json.dumps({"error": "nessuno stem"})); return

    sr = None
    stems = {}
    maxlen = 0
    for p in paths:
        data, fsr = sf.read(p, dtype="float32", always_2d=True)
        sr = fsr
        mono = data.mean(axis=1)
        name = os.path.splitext(os.path.basename(p))[0]
        stems[name] = mono
        maxlen = max(maxlen, len(mono))

    mix = np.zeros(maxlen, dtype="float32")
    rms = {}
    for name, mono in stems.items():
        if len(mono) < maxlen:
            mono = np.concatenate([mono, np.zeros(maxlen - len(mono), dtype="float32")])
            stems[name] = mono
        mix += mono
        rms[name] = float(np.sqrt(np.mean(mono ** 2)))

    duration = maxlen / sr

    out = {"duration": duration, "sr": sr}

    # presenza per stem (RMS normalizzato sul massimo)
    mx = max(rms.values()) or 1.0
    out["presence"] = {n: round(100.0 * v / mx) for n, v in rms.items()}

    # dynamic range / peak (sul mix)
    peak = float(np.max(np.abs(mix))) if maxlen else 0.0
    rms_mix = float(np.sqrt(np.mean(mix ** 2))) if maxlen else 0.0
    out["peak_db"] = round(db(peak), 1)
    out["dynamic_range"] = round(db(peak) - db(rms_mix), 1)

    try:
        import librosa
        y = mix.astype("float32")
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
        out["bpm"] = int(round(float(np.atleast_1d(tempo)[0])))
        bt = librosa.frames_to_time(beats, sr=sr)
        out["beat_times"] = [round(float(x), 4) for x in bt.tolist()]
        if len(bt) > 2:
            ibi = np.diff(bt)
            cv = float(ibi.std() / (ibi.mean() + 1e-9))
            out["tempo_stability"] = int(round(max(0.0, min(1.0, 1.0 - cv)) * 100))
        else:
            out["tempo_stability"] = 0
        chroma_full = librosa.feature.chroma_cqt(y=y, sr=sr)
        chroma = chroma_full.mean(axis=1)
        ki, mode, conf = detect_key(chroma)
        out["key"] = NOTES[ki]
        out["mode"] = mode
        out["scale"] = "Major" if mode == "maj" else "Natural Minor"
        out["key_conf"] = round(conf * 100)
        out["chords"] = detect_chords(chroma_full, sr, bt, duration)
        try:
            out["sections"] = detect_sections(y, sr, duration)
        except Exception:  # noqa: BLE001
            out["sections"] = []
    except Exception as e:  # noqa: BLE001
        out["bpm"] = None
        out["key"] = None
        out["analyze_error"] = str(e)

    try:
        import pyloudnorm as pyln
        meter = pyln.Meter(sr)
        out["lufs"] = round(float(meter.integrated_loudness(mix)), 1)
    except Exception:  # noqa: BLE001
        out["lufs"] = None

    print(json.dumps(out))


if __name__ == "__main__":
    main()
