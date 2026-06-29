"""Separazione voce/strumentale con Roformer via audio-separator.

ESEGUITO DAL VENV 3.12 del motore (ha torch CUDA + audio-separator).
Uso: python roformer_script.py <input> <output_dir> <model_dir> <model> <format>

Produce due file nella cartella di output: 'vocals' e 'no_vocals'
(con l'estensione del formato). Il modello viene scaricato in <model_dir>
alla prima esecuzione (serve connessione, ~centinaia di MB una-tantum).
"""

import sys

from audio_separator.separator import Separator


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
    # NB: il parametro si chiama custom_output_names (non output_names). I nomi-chiave
    # ("Vocals"/"Instrumental") sono gli stem del modello; se non combaciano,
    # audio-separator usa il nome di default e ci pensa il chiamante (_pick_voc_inst).
    sep.separate(inp, custom_output_names={"Vocals": "vocals", "Instrumental": "no_vocals"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
