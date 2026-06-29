"""Launcher di primo livello (per PyInstaller). Importa il package app."""

from app.main import main

if __name__ == "__main__":
    raise SystemExit(main())
