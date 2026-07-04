# Sonora — Worker di licenza (Cloudflare)

Micro-server gratuito che fa da guardiano delle attivazioni: lega ogni codice
cliente a **un solo PC** e firma un token Ed25519 che l'app Sonora poi verifica
**offline**. Il segreto (chiave privata) sta solo qui, mai nell'app.

## Prerequisiti
- Account Cloudflare gratuito
- Node.js + `npm i -g wrangler` (CLI di Cloudflare)
- `wrangler login`

## Setup (una tantum)

1. **Chiavi.** Genera una coppia tua:
   ```
   python worker/gen-keys.py
   ```
   - Incolla `PUBLIC_KEY_B64URL` in `app/licensing.py` (costante `PUBLIC_KEY_B64URL`).
   - Tieni da parte `SIGNING_JWK` per il passo 4.

   > In dev è già presente una coppia funzionante di default. Per la produzione
   > **rigenera** e aggiorna sia l'app sia il secret.

2. **KV namespace:**
   ```
   cd worker
   wrangler kv namespace create LICENSES
   ```
   Copia l'`id` restituito dentro `wrangler.toml` (campo `id`).

3. **Deploy:**
   ```
   wrangler deploy
   ```
   Ti darà l'URL, es. `https://sonora-license.tuosub.workers.dev`.
   Incollalo in `app/licensing.py` (costante `LICENSE_API`).

4. **Secret:**
   ```
   wrangler secret put SIGNING_JWK    # incolla il JWK del passo 1
   wrangler secret put ADMIN_SECRET   # una password a tua scelta
   ```

## Uso quotidiano (modo semplice: script PowerShell)

Una volta sola, crea il file `worker/.admin-secret` con dentro la tua password admin
(è gitignorato, resta solo sul tuo PC):
```powershell
Set-Content worker\.admin-secret 'LA_TUA_PASSWORD_ADMIN' -NoNewline
```

**Generare codici da vendere:**
```powershell
cd worker
.\genera-codici.ps1                 # 1 codice
.\genera-codici.ps1 5               # 5 codici
.\genera-codici.ps1 3 "Mario Rossi" # 3 codici con nota
```

**Revocare / gestire un codice:**
```powershell
.\revoca-codice.ps1 ABCD-EFGH-JKLM-NPQR          # revoca (blocca entro ~7 giorni)
.\revoca-codice.ps1 ABCD-EFGH-JKLM-NPQR -Reset   # sgancia dal PC (cliente cambia computer)
.\revoca-codice.ps1 ABCD-EFGH-JKLM-NPQR -Info    # mostra lo stato
```

---

## Uso quotidiano (alternativa: curl)

**Generare codici da vendere** (ne crea N, li segna `unused`):
```
curl -X POST https://TUO-WORKER/admin/new \
  -H "X-Admin-Secret: LA_TUA_PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{"count": 5, "note": "lotto luglio"}'
```
Restituisce i codici `XXXX-XXXX-XXXX-XXXX` da consegnare ai clienti.

**Revocare un codice** (si blocca entro ~7 giorni, anche offline):
```
curl -X POST https://TUO-WORKER/admin/revoke \
  -H "X-Admin-Secret: LA_TUA_PASSWORD" -H "Content-Type: application/json" \
  -d '{"code": "ABCD-EFGH-JKLM-NPQR"}'
```

**Slegare un codice da un PC** (cliente ha cambiato computer):
```
curl -X POST https://TUO-WORKER/admin/reset \
  -H "X-Admin-Secret: LA_TUA_PASSWORD" -H "Content-Type: application/json" \
  -d '{"code": "ABCD-EFGH-JKLM-NPQR"}'
```

**Stato di un codice:**
```
curl -X POST https://TUO-WORKER/admin/get \
  -H "X-Admin-Secret: LA_TUA_PASSWORD" -H "Content-Type: application/json" \
  -d '{"code": "ABCD-EFGH-JKLM-NPQR"}'
```

## Endpoint usati dall'app (non serve chiamarli a mano)
- `POST /trial`    `{machineId}` → `{firstSeen}` (prova server-side, 3 giorni)
- `POST /activate` `{code, machineId}` → `{ok, token}` oppure `{ok:false, reason}`
- `POST /renew`    `{token, machineId}` → `{ok, token}` (rinnovo silenzioso)

`reason` possibili: `unknown` (codice inesistente), `revoked`, `in_use`
(codice già legato a un altro PC), `bad_request`.
