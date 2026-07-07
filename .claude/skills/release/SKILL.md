---
name: release
description: Prepara e pubblica una release di Sonora - bump versione, changelog, commit, tag vX.Y.Z e push (la CI builda e pubblica l'installer)
disable-model-invocation: true
---

# Release di Sonora

Prepara e pubblica la release **$ARGUMENTS** (se non è stata indicata una versione, proponila tu in base alle modifiche dall'ultimo tag: patch per soli fix, minor per nuove funzioni — chiedi conferma prima di procedere).

## Prerequisiti (verifica prima di toccare qualsiasi file)

1. Working tree pulito su `main` (`git status`), allineato col remoto (`git pull`).
2. Guarda cosa entra nella release: `git log --oneline <ultimo-tag>..HEAD`. Se non c'è nulla di nuovo, fermati e dillo.
3. La suite deve essere verde: `python -m pytest`.

## Bump versione (tutti e quattro, nessuno escluso)

1. `app/__init__.py` → `__version__ = "X.Y.Z"` (il tag DEVE combaciare, la CI ci conta).
2. `app/changelog.py` → nuova voce in cima, in italiano, rivolta all'utente finale (cosa cambia per lui, non i dettagli interni). `test_changelog.py` fallisce se la dimentichi.
3. `installer/sonora.iss` → versione.
4. `STATO-PROGETTO.md` → aggiorna la riga «Versione corrente» con il riassunto delle modifiche, nello stile delle voci esistenti.

## Verifica e pubblicazione

1. `python -m pytest` di nuovo (il test del changelog ora deve passare).
2. Mostra all'utente il riepilogo (versione, voce changelog, commit inclusi) e **chiedi conferma esplicita** prima di committare.
3. Commit convenzionale in italiano che riassume la release, es. `feat(mixer): export basi minus-one (X.Y.Z)`.
4. Tag e push: `git tag vX.Y.Z && git push origin main --tags`.
5. La GitHub Action Release builda exe+installer e pubblica. Controlla che parta: `gh run list --workflow=release.yml --limit 1`, e riferisci all'utente il link alla run.

## Note

- Mai `--force`, mai riscrivere tag esistenti: se qualcosa è sbagliato dopo il push, si fa una release successiva.
- Build di prova senza pubblicare: `gh workflow run release.yml` (workflow_dispatch).
