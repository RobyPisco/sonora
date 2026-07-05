"""Separazione stem con Roformer via audio-separator.

ESEGUITO DAL VENV 3.12 del motore (ha torch CUDA + audio-separator).
Uso: python roformer_script.py <input> <output_dir> <model_dir> <model> <format>

Produce nella cartella di output un file per ogni stem del modello, con nome
minuscolo normalizzato ('vocals', 'no_vocals', 'drums', …). Funziona sia coi
modelli voce/strumentale sia coi multi-stem (es. BS-Roformer-SW a 6 stem).
Il modello viene scaricato in <model_dir> alla prima esecuzione (serve
connessione, ~centinaia di MB una-tantum).
"""

import sys

from audio_separator.separator import Separator

# Nome di output per ogni stem noto (chiavi sia Capitalizzate sia minuscole:
# dipendono dal config del modello). Le chiavi che il modello non produce
# vengono ignorate; per stem fuori mappa audio-separator usa il nome di
# default e ci pensa il chiamante (_pick_stem/_pick_voc_inst).
_NAMES = {"Vocals": "vocals", "Instrumental": "no_vocals", "Drums": "drums",
          "Bass": "bass", "Guitar": "guitar", "Piano": "piano", "Other": "other"}
_NAMES.update({k.lower(): v for k, v in _NAMES.items()})


def main() -> int:
    if len(sys.argv) < 6:
        print("uso: roformer_script.py <input> <output_dir> <model_dir> <model> <format>")
        return 2
    inp, out_dir, model_dir, model, fmt = sys.argv[1:6]

    sep = Separator(
        output_dir=out_dir,
        model_file_dir=model_dir,
        output_format=fmt.upper(),
    )
    sep.load_model(model_filename=model)
    # NB: il parametro si chiama custom_output_names (non output_names).
    sep.separate(inp, custom_output_names=_NAMES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
