/**
 * Sonora — Worker di licenza (Cloudflare Workers).
 *
 * Fa da guardiano delle attivazioni: lega ogni codice cliente a UN solo PC e
 * firma un token Ed25519 che l'app verifica poi OFFLINE con la chiave pubblica.
 *
 * Bindings richiesti (vedi wrangler.toml):
 *   - KV namespace  LICENSES        (store di codici e macchine)
 *   - secret        SIGNING_JWK     (JWK Ed25519 privata, con "d")
 *   - secret        ADMIN_SECRET    (per gli endpoint /admin/*)
 *
 * Formato token:  "<b64url(payload_json)>.<b64url(sig)>"
 *   payload_json = {"code","machine","iss","exp"}   (iss/exp in secondi epoch)
 *   firma Ed25519 sui byte ASCII di "<b64url(payload_json)>".
 */

const TOKEN_TTL_S = 7 * 24 * 3600; // durata token: 7 giorni
const CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // niente 0/O/1/I

// ---- base64url ----
function b64uEncode(bytes) {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function b64uDecode(str) {
  str = str.replace(/-/g, "+").replace(/_/g, "/");
  while (str.length % 4) str += "=";
  const bin = atob(str);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// ---- risposte JSON ----
function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// ---- chiavi ----
let _signKey = null;
async function signKey(env) {
  if (_signKey) return _signKey;
  const jwk = JSON.parse(env.SIGNING_JWK);
  _signKey = await crypto.subtle.importKey(
    "jwk", jwk, { name: "Ed25519" }, false, ["sign"]
  );
  return _signKey;
}

let _verifyKey = null;
async function verifyKey(env) {
  if (_verifyKey) return _verifyKey;
  const jwk = JSON.parse(env.SIGNING_JWK);
  const pub = { kty: "OKP", crv: "Ed25519", x: jwk.x, key_ops: ["verify"], ext: true };
  _verifyKey = await crypto.subtle.importKey(
    "jwk", pub, { name: "Ed25519" }, false, ["verify"]
  );
  return _verifyKey;
}

async function makeToken(env, code, machine) {
  const now = Math.floor(Date.now() / 1000);
  const payload = { code, machine, iss: now, exp: now + TOKEN_TTL_S };
  const pB64 = b64uEncode(new TextEncoder().encode(JSON.stringify(payload)));
  const sig = await crypto.subtle.sign(
    { name: "Ed25519" }, await signKey(env), new TextEncoder().encode(pB64)
  );
  return pB64 + "." + b64uEncode(new Uint8Array(sig));
}

async function parseToken(env, token) {
  const dot = token.indexOf(".");
  if (dot < 0) return null;
  const pB64 = token.slice(0, dot);
  const sig = b64uDecode(token.slice(dot + 1));
  const ok = await crypto.subtle.verify(
    { name: "Ed25519" }, await verifyKey(env), sig,
    new TextEncoder().encode(pB64)
  );
  if (!ok) return null;
  try {
    return JSON.parse(new TextDecoder().decode(b64uDecode(pB64)));
  } catch {
    return null;
  }
}

function newCode() {
  const rnd = crypto.getRandomValues(new Uint8Array(16));
  let s = "";
  for (let i = 0; i < 16; i++) {
    if (i > 0 && i % 4 === 0) s += "-";
    s += CODE_ALPHABET[rnd[i] % CODE_ALPHABET.length];
  }
  return s; // es. ABCD-EFGH-JKLM-NPQR
}

// ---- endpoint applicativi ----

async function handleTrial(req, env) {
  const { machineId } = await req.json();
  if (!machineId) return json({ ok: false, reason: "bad_request" }, 400);
  const key = "machine:" + machineId;
  let rec = await env.LICENSES.get(key, "json");
  if (!rec) {
    rec = { firstSeen: Math.floor(Date.now() / 1000) };
    await env.LICENSES.put(key, JSON.stringify(rec));
  }
  return json({ ok: true, firstSeen: rec.firstSeen });
}

async function handleActivate(req, env) {
  const { code, machineId } = await req.json();
  if (!code || !machineId) return json({ ok: false, reason: "bad_request" }, 400);
  const key = "code:" + code.trim().toUpperCase();
  const rec = await env.LICENSES.get(key, "json");
  if (!rec) return json({ ok: false, reason: "unknown" }, 404);
  if (rec.status === "revoked") return json({ ok: false, reason: "revoked" }, 403);

  if (rec.status === "active" && rec.machine && rec.machine !== machineId) {
    return json({ ok: false, reason: "in_use" }, 409);
  }

  // prima attivazione (o ri-attivazione dallo stesso PC): lega e firma.
  if (rec.status !== "active") {
    rec.status = "active";
    rec.machine = machineId;
    rec.activatedAt = Math.floor(Date.now() / 1000);
    await env.LICENSES.put(key, JSON.stringify(rec));
  }
  const token = await makeToken(env, code.trim().toUpperCase(), machineId);
  return json({ ok: true, token });
}

async function handleRenew(req, env) {
  const { token, machineId } = await req.json();
  if (!token) return json({ ok: false, reason: "bad_request" }, 400);
  const payload = await parseToken(env, token);
  if (!payload) return json({ ok: false, reason: "unknown" }, 403);
  if (machineId && payload.machine !== machineId) {
    return json({ ok: false, reason: "in_use" }, 409);
  }
  const rec = await env.LICENSES.get("code:" + payload.code, "json");
  if (!rec || rec.status === "revoked") {
    return json({ ok: false, reason: "revoked" }, 403);
  }
  if (rec.machine && rec.machine !== payload.machine) {
    return json({ ok: false, reason: "in_use" }, 409);
  }
  const fresh = await makeToken(env, payload.code, payload.machine);
  return json({ ok: true, token: fresh });
}

// ---- endpoint admin (protetti da ADMIN_SECRET) ----

async function handleAdmin(url, req, env) {
  if (req.headers.get("X-Admin-Secret") !== env.ADMIN_SECRET) {
    return json({ ok: false, reason: "forbidden" }, 401);
  }
  const path = url.pathname;

  if (path === "/admin/new") {
    const body = await req.json().catch(() => ({}));
    const count = Math.min(Math.max(parseInt(body.count) || 1, 1), 100);
    const note = (body.note || "").toString().slice(0, 200);
    const codes = [];
    for (let i = 0; i < count; i++) {
      const code = newCode();
      await env.LICENSES.put(
        "code:" + code,
        JSON.stringify({ status: "unused", note, createdAt: Math.floor(Date.now() / 1000) })
      );
      codes.push(code);
    }
    return json({ ok: true, codes });
  }

  if (path === "/admin/revoke") {
    const { code } = await req.json();
    const key = "code:" + (code || "").trim().toUpperCase();
    const rec = await env.LICENSES.get(key, "json");
    if (!rec) return json({ ok: false, reason: "unknown" }, 404);
    rec.status = "revoked";
    await env.LICENSES.put(key, JSON.stringify(rec));
    return json({ ok: true });
  }

  if (path === "/admin/reset") {
    // Slega un codice da un PC (es. cliente ha cambiato computer).
    const { code } = await req.json();
    const key = "code:" + (code || "").trim().toUpperCase();
    const rec = await env.LICENSES.get(key, "json");
    if (!rec) return json({ ok: false, reason: "unknown" }, 404);
    rec.status = "unused";
    delete rec.machine;
    delete rec.activatedAt;
    await env.LICENSES.put(key, JSON.stringify(rec));
    return json({ ok: true });
  }

  if (path === "/admin/get") {
    const { code } = await req.json();
    const rec = await env.LICENSES.get(
      "code:" + (code || "").trim().toUpperCase(), "json"
    );
    return json({ ok: true, record: rec });
  }

  return json({ ok: false, reason: "not_found" }, 404);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "POST") {
      return json({ ok: true, service: "sonora-license" });
    }
    try {
      if (url.pathname === "/trial") return await handleTrial(request, env);
      if (url.pathname === "/activate") return await handleActivate(request, env);
      if (url.pathname === "/renew") return await handleRenew(request, env);
      if (url.pathname.startsWith("/admin/")) return await handleAdmin(url, request, env);
      return json({ ok: false, reason: "not_found" }, 404);
    } catch (e) {
      return json({ ok: false, reason: "server_error", detail: String(e) }, 500);
    }
  },
};
