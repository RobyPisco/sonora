"""Design token centrali di Sonora: colori, spaziature, tipografia.

Unica fonte di verità per la palette. Il QSS (resources/style.qss) usa
placeholder `@tok(nome)` risolti da load_qss(); il codice Python importa
COLORS / STEM_COLORS / STATUS_COLORS invece di ripetere hex letterali.
"""

from __future__ import annotations

import re

from . import paths

# ---------- colori ----------

COLORS = {
    "bg": "#0f1117",            # sfondo finestra
    "panel": "#151823",         # pannelli / card / rail / playbar
    "panel2": "#1b1f2c",        # superfici in rilievo (hover, gruppi)
    "raise": "#222738",         # superfici più chiare (input attivi, chip task)
    "input": "#20242f",         # campi testo / combo
    "border": "#262b3a",        # bordo standard
    "border2": "#323848",       # bordo evidenziato
    "text": "#e8eaf2",          # testo principale
    "muted": "#8b90a3",         # testo secondario
    "faint": "#5d6274",         # testo terziario / hint
    "accent": "#ff3b5c",        # brand / azioni primarie
    "accent_hover": "#ff5170",
    "accent_press": "#e62e4d",
    "ok": "#3ddc84",
    "warn": "#ff9f43",
    "err": "#ff5d5d",
    "info": "#4aa8ff",
    "solo": "#ffd23f",          # stato Solo (giallo, come il basso)
    "wave_bg": "#10121a",       # sfondo waveform / log
    "strip_sep": "#1e2230",     # separatori strisce mixer
}

# Colori per stem (la firma visiva dell'app)
STEM_COLORS = {
    "vocals": "#ff4d8d", "drums": "#ff9f43", "bass": "#ffd23f",
    "guitar": "#3ddc84", "piano": "#a974ff", "other": "#4aa8ff",
}

# Colori di stato per la coda download (chip di stato)
STATUS_COLORS = {
    "in attesa": COLORS["muted"],
    "pronto": COLORS["muted"],
    "scaricando": COLORS["info"],
    "conversione": COLORS["warn"],
    "stem": COLORS["accent"],
    "fatto": COLORS["ok"],
    "errore": COLORS["err"],
}

# ---------- spaziature / raggi / tipografia ----------

SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24}
RADII = {"sm": 8, "md": 10, "lg": 14}
FONT_SIZES = {
    "caption": 11,   # etichette minuscole, hint
    "small": 12,     # testo secondario
    "base": 14,      # testo standard
    "mid": 15,       # bottoni / input
    "lead": 17,      # valori in evidenza
    "h2": 20,        # sottotitoli
    "h1": 26,        # titoli schermata
    "display": 32,   # hero
}


def _tokens() -> dict[str, str]:
    toks: dict[str, str] = dict(COLORS)
    for k, v in STEM_COLORS.items():
        toks[f"stem_{k}"] = v
    for k, v in FONT_SIZES.items():
        toks[f"fs_{k}"] = f"{v}px"
    for k, v in SPACE.items():
        toks[f"sp_{k}"] = f"{v}px"
    for k, v in RADII.items():
        toks[f"r_{k}"] = f"{v}px"
    return toks


_TOK_RE = re.compile(r"@tok\(([A-Za-z0-9_]+)\)")


def load_qss() -> str:
    """Legge style.qss e risolve i placeholder @tok(nome) + path immagini."""
    qss = paths.resource("style.qss")
    if not qss.exists():
        return ""
    css = qss.read_text(encoding="utf-8")
    # i path immagine in QSS vanno con slash; risolti runtime (dev + exe)
    css = css.replace("__CHECK__", paths.resource("check.svg").as_posix())
    css = css.replace("__CHEVRON__", paths.resource("chevron.svg").as_posix())
    toks = _tokens()

    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name not in toks:
            raise KeyError(f"token QSS sconosciuto: @tok({name})")
        return toks[name]

    css = _TOK_RE.sub(sub, css)
    if "@tok(" in css:
        raise ValueError("QSS: placeholder @tok non risolti")
    return css


def repolish(widget) -> None:
    """Riapplica il QSS dopo il cambio di una dynamic property."""
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)
    widget.update()


def set_state(widget, prop: str, value) -> None:
    """Imposta una dynamic property usata dal QSS e riapplica lo stile."""
    widget.setProperty(prop, value)
    repolish(widget)
