/**
 * Einkaufsliste – App (Handy und Seitenleiste)
 *
 * Funktionsweise:
 *  - "base"  = letzter Stand vom Server
 *  - "queue" = lokale Änderungen, die noch nicht übertragen sind
 *  - Angezeigt wird base + queue. Alles liegt im localStorage, daher klappt es auch offline.
 *  - Beim Sync gehen die Änderungen an Home Assistant, zurück kommt der aktuelle Stand.
 *
 * Anmeldung:
 *  - Seitenleiste: übernimmt Home Assistant, die App-Oberfläche leitet die API weiter.
 *  - Handy-App: normale Home-Assistant-Anmeldung (wie die offizielle App). Ist man im selben
 *    Browser schon in Home Assistant angemeldet, wird diese Anmeldung übernommen.
 */
"use strict";

const INGRESS = window.EINKAUFSLISTE_INGRESS === true;
const API = INGRESS ? "proxy" : "/api/einkaufsliste";
const STORE_KEY = INGRESS ? "einkaufsliste-ingress-v1" : "einkaufsliste-app-v1";
const AUTH_KEY = "einkaufsliste-auth-v1";
const CLIENT_ID = `${location.origin}/einkaufsliste/app/`;
const REDIRECT_URI = `${location.origin}/einkaufsliste/app/index.html`;
const SYNC_INTERVAL = 15000;
const REQUEST_TIMEOUT = 10000;

// ------------------------------------------------------------------ Einheiten & Formatierung

const UNIT_GROUPS = [
  { label: "Stück", units: [["stk", "Stk."], ["pkg", "Pkg."], ["dose", "Dose"], ["flasche", "Fl."], ["bund", "Bund"]] },
  { label: "Gewicht", units: [["g", "g"], ["kg", "kg"]] },
  { label: "Volumen", units: [["ml", "ml"], ["l", "l"]] },
];
const UNIT_LABEL = Object.fromEntries(UNIT_GROUPS.flatMap((g) => g.units));
const STEP = { stk: 1, pkg: 1, dose: 1, flasche: 1, bund: 1, g: 100, kg: 0.5, ml: 250, l: 0.5 };

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmtNumber = (n) => new Intl.NumberFormat("de-DE", { maximumFractionDigits: 3 }).format(n);
const fmtQty = (item) => (item.quantity == null ? "" : `${fmtNumber(item.quantity)} ${UNIT_LABEL[item.unit] ?? ""}`.trim());
const parseNumber = (s) => {
  const v = String(s).trim().replace(",", ".");
  if (v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : NaN;
};
const emptyToNull = (v) => (v == null || String(v).trim() === "" ? null : String(v).trim());
const unitOptions = (selected) =>
  `<option value="">–</option>` +
  UNIT_GROUPS.map(
    (g) =>
      `<optgroup label="${g.label}">${g.units
        .map(([v, l]) => `<option value="${v}"${v === selected ? " selected" : ""}>${l}</option>`)
        .join("")}</optgroup>`
  ).join("");

function newId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

// ------------------------------------------------------------------ Mengen erkennen (wie parsing.py)

const UNIT_ALIASES = {
  stk: ["stk", "stk.", "stück", "stueck", "st.", "x"],
  pkg: ["pkg", "pkg.", "pck", "pck.", "packung", "packungen", "pack", "päckchen"],
  dose: ["dose", "dosen"],
  flasche: ["flasche", "flaschen", "fl", "fl."],
  bund: ["bund", "bd.", "bd"],
  g: ["g", "gr", "gr.", "gramm"],
  kg: ["kg", "kilo", "kilogramm"],
  ml: ["ml", "milliliter"],
  l: ["l", "liter", "ltr", "ltr."],
};
const CONVERSION = { g: ["g", 1], kg: ["g", 1000], ml: ["ml", 1], l: ["ml", 1000] };
const ALIAS_TO_UNIT = Object.fromEntries(Object.entries(UNIT_ALIASES).flatMap(([u, list]) => list.map((a) => [a, u])));
const UNIT_RE = Object.keys(ALIAS_TO_UNIT)
  .sort((a, b) => b.length - a.length)
  .map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
  .join("|");
const NUM = String.raw`\d+(?:[.,]\d+)?`;
const PATTERNS = [
  new RegExp(String.raw`^\s*(?<name>.+?)\s*\(\s*(?<qty>${NUM})\s*(?:(?<unit>${UNIT_RE}))?\s*\)\s*$`, "iu"),
  new RegExp(String.raw`^\s*(?<qty>${NUM})\s*(?:(?<unit>${UNIT_RE})(?=[\s)]|$)\s*|\s+)(?<name>.+?)\s*$`, "iu"),
  new RegExp(String.raw`^\s*(?<name>.+?)\s*[-–:,]?\s*(?<qty>${NUM})\s*(?<unit>${UNIT_RE})\s*$`, "iu"),
];
const cleanName = (n) => {
  n = n.trim();
  return n.charAt(0).toUpperCase() + n.slice(1);
};

function parseItem(text) {
  for (const re of PATTERNS) {
    const m = text.trim().match(re);
    if (m) {
      const unit = m.groups.unit;
      return [cleanName(m.groups.name), parseFloat(m.groups.qty.replace(",", ".")), unit ? ALIAS_TO_UNIT[unit.toLowerCase()] : "stk"];
    }
  }
  return [cleanName(text), null, null];
}

const round3 = (n) => Math.round(n * 1000) / 1000;
function mergeQuantities(q1, u1, q2, u2) {
  if (q2 == null) return [q1, u1];
  if (q1 == null) return [q2, u2];
  if (u1 === u2) return [round3(q1 + q2), u1];
  const c1 = CONVERSION[u1];
  const c2 = CONVERSION[u2];
  if (c1 && c2 && c1[0] === c2[0]) {
    const total = q1 * c1[1] + q2 * c2[1];
    return total >= 1000 ? [round3(total / 1000), c1[0] === "g" ? "kg" : "l"] : [round3(total), c1[0]];
  }
  return null;
}

// ------------------------------------------------------------------ Zustand

let S = loadState();
let online = null; // null = unbekannt
let noList = false; // Integration noch nicht eingerichtet
let syncing = false;
let syncTimer = null;
let doneExpanded = false;
let editId = null;

function loadState() {
  const empty = { listId: "", listName: "", base: { items: [], history: [] }, queue: [], lastSync: null };
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) return { ...empty, ...JSON.parse(raw) };
  } catch (_e) {
    /* kein Speicher verfügbar */
  }
  return empty;
}

function saveState() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(S));
  } catch (_e) {
    /* kein Speicher verfügbar */
  }
}

/** Wendet die noch nicht übertragenen Änderungen lokal auf den Serverstand an. */
function applyOps(baseItems, ops, history) {
  let items = structuredClone(baseItems);
  const now = new Date().toISOString();
  const findByName = (name) => {
    const matches = items.filter((i) => i.name.toLowerCase() === name.toLowerCase());
    return matches.find((i) => !i.checked) ?? matches[0] ?? null;
  };

  for (const op of ops) {
    if (op.op === "add") {
      if (items.some((i) => i.id === op.id)) continue;
      let name = op.name.trim();
      let quantity = op.quantity ?? null;
      let unit = op.unit ?? null;
      if (quantity == null) {
        let parsedUnit;
        [name, quantity, parsedUnit] = parseItem(name);
        unit = unit || parsedUnit;
      }
      const known = history.find((h) => h.name.toLowerCase() === name.toLowerCase());
      if (quantity != null && unit == null) unit = known?.unit ?? "stk";
      if (quantity == null) unit = null;
      const note = emptyToNull(op.note);
      const existing = findByName(name);
      if (existing) {
        if (existing.checked) {
          Object.assign(existing, { checked: false, checked_at: null, quantity, unit, note });
          continue;
        }
        const merged = mergeQuantities(existing.quantity, existing.unit, quantity, unit);
        if (merged) {
          [existing.quantity, existing.unit] = merged;
          existing.note = note ?? existing.note;
          continue;
        }
      }
      items.push({ id: op.id, name, quantity, unit, note, checked: false, created: now, checked_at: null });
    } else if (op.op === "update") {
      const item = items.find((i) => i.id === op.item_id);
      if (!item) continue;
      const c = op.changes;
      if ("name" in c && c.name.trim()) item.name = c.name.trim();
      if ("quantity" in c) item.quantity = c.quantity;
      if ("unit" in c) item.unit = c.unit;
      if ("note" in c) item.note = emptyToNull(c.note);
      if ("checked" in c) {
        if (c.checked !== item.checked) item.checked_at = c.checked ? now : null;
        item.checked = c.checked;
      }
      if (item.quantity == null) item.unit = null;
      else if (item.unit == null) item.unit = "stk";
    } else if (op.op === "remove") {
      items = items.filter((i) => !op.item_ids.includes(i.id));
    }
  }
  return items;
}

const currentItems = () => applyOps(S.base.items, S.queue, S.base.history);

function queueOp(op) {
  S.queue.push({ op_id: newId(), ...op });
  saveState();
  render();
  scheduleSync(300);
}

// ------------------------------------------------------------------ Anmeldung (nur Handy-App)

class AuthError extends Error {}

let auth = loadAuth();

function loadAuth() {
  try {
    return JSON.parse(localStorage.getItem(AUTH_KEY));
  } catch (_e) {
    return null;
  }
}

function saveAuth(value) {
  auth = value;
  try {
    if (value) localStorage.setItem(AUTH_KEY, JSON.stringify(value));
    else localStorage.removeItem(AUTH_KEY);
  } catch (_e) {
    /* kein Speicher verfügbar */
  }
}

const needsLogin = () => !INGRESS && !auth;

async function fetchWithTimeout(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
  try {
    return await fetch(url, { ...options, signal: controller.signal, cache: "no-store" });
  } finally {
    clearTimeout(timer);
  }
}

async function tokenRequest(params) {
  const res = await fetchWithTimeout("/auth/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(params),
  });
  if (res.status === 400 || res.status === 401 || res.status === 403) throw new AuthError("Anmeldung abgelaufen");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function storeTokens(data, clientId, refreshToken) {
  saveAuth({
    access_token: data.access_token,
    refresh_token: data.refresh_token ?? refreshToken,
    expires: Date.now() + data.expires_in * 1000,
    client_id: clientId,
  });
}

/** Gültiger Zugangsschlüssel; wird bei Bedarf automatisch erneuert. */
async function accessToken() {
  if (!auth) throw new AuthError("Nicht angemeldet");
  if (Date.now() < auth.expires - 60000) return auth.access_token;
  const data = await tokenRequest({
    grant_type: "refresh_token",
    refresh_token: auth.refresh_token,
    client_id: auth.client_id,
  });
  storeTokens(data, auth.client_id, auth.refresh_token);
  return auth.access_token;
}

/** Bereits bestehende Anmeldung des Home-Assistant-Frontends im selben Browser übernehmen. */
function adoptHomeAssistantLogin() {
  try {
    const t = JSON.parse(localStorage.getItem("hassTokens"));
    if (t?.refresh_token && t.clientId) {
      saveAuth({ access_token: t.access_token, refresh_token: t.refresh_token, expires: t.expires || 0, client_id: t.clientId });
      return true;
    }
  } catch (_e) {
    /* nichts gespeichert */
  }
  return false;
}

/** Zur Anmeldeseite von Home Assistant; danach kommt man mit ?code=… zurück. */
function login() {
  const state = newId();
  try {
    sessionStorage.setItem("einkaufsliste-login-state", state);
  } catch (_e) {
    /* egal */
  }
  const params = new URLSearchParams({ response_type: "code", client_id: CLIENT_ID, redirect_uri: REDIRECT_URI, state });
  location.href = `/auth/authorize?${params}`;
}

async function finishLogin() {
  const params = new URLSearchParams(location.search);
  const code = params.get("code");
  if (!code) return;
  history.replaceState(null, "", location.pathname);
  let expected = null;
  try {
    expected = sessionStorage.getItem("einkaufsliste-login-state");
  } catch (_e) {
    /* egal */
  }
  if (expected && params.get("state") !== expected) return;
  try {
    storeTokens(await tokenRequest({ grant_type: "authorization_code", code, client_id: CLIENT_ID }), CLIENT_ID);
  } catch (err) {
    console.warn("Anmeldung fehlgeschlagen:", err);
  }
}

async function logout() {
  // Nur die eigene Anmeldung widerrufen – eine übernommene gehört dem Home-Assistant-Frontend
  if (auth?.client_id === CLIENT_ID) {
    fetchWithTimeout("/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ action: "revoke", token: auth.refresh_token }),
    }).catch(() => {});
  }
  saveAuth(null);
  S = { listId: "", listName: "", base: { items: [], history: [] }, queue: [], lastSync: null };
  saveState();
}

// ------------------------------------------------------------------ Synchronisation

async function request(path, { method = "GET", body } = {}, retried = false) {
  const headers = { "Content-Type": "application/json" };
  if (!INGRESS) headers.Authorization = `Bearer ${await accessToken()}`;
  const res = await fetchWithTimeout(API + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (res.status === 401) {
    if (INGRESS || retried) throw new AuthError("Nicht angemeldet");
    // Zugangsschlüssel abgelehnt: einmal erneuern und nochmal versuchen
    auth.expires = 0;
    return request(path, { method, body }, true);
  }
  return res;
}

/** Holt die verfügbaren Listen. null = keine (Integration noch nicht eingerichtet). */
async function fetchLists() {
  const res = await request("/lists");
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const lists = await res.json();
  return lists.length ? lists : null;
}

/** Wählt automatisch eine Liste, falls noch keine gewählt ist. */
async function ensureList() {
  if (S.listId) return true;
  const lists = await fetchLists();
  noList = !lists;
  if (!lists) return false;
  S.listId = lists[0].list_id;
  S.listName = lists[0].name;
  saveState();
  return true;
}

function scheduleSync(delay = 0) {
  clearTimeout(syncTimer);
  syncTimer = setTimeout(sync, delay);
}

async function sync() {
  if (syncing || needsLogin()) return;
  syncing = true;
  try {
    if (!(await ensureList())) {
      online = true;
      return;
    }
    const ops = S.queue.slice();
    const res = await request(`/${encodeURIComponent(S.listId)}/sync`, { method: "POST", body: { ops } });
    if (res.status === 404) {
      // Liste wurde gelöscht – beim nächsten Mal eine andere wählen
      S.listId = "";
      saveState();
      online = true;
      return;
    }
    if (res.status === 400) {
      // Fehlerhafte Änderungen verwerfen, sonst blockieren sie alles Weitere
      console.warn("Sync abgelehnt:", await res.text());
      S.queue = S.queue.slice(ops.length);
      saveState();
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    S.base = { items: data.items || [], history: data.history || [] };
    S.queue = S.queue.slice(ops.length);
    S.lastSync = Date.now();
    noList = false;
    online = true;
    saveState();
  } catch (err) {
    if (err instanceof AuthError) {
      saveAuth(null);
      online = true;
    } else {
      online = false;
    }
  } finally {
    syncing = false;
    render();
    if (online && S.queue.length && !needsLogin() && !noList) scheduleSync(500);
  }
}

// ------------------------------------------------------------------ Darstellung

const $ = (sel) => document.querySelector(sel);

function setStatusText(text, kind) {
  const el = $("#status");
  el.textContent = text;
  el.className = `status ${kind}`;
}

function renderStatus() {
  const pending = S.queue.length;
  if (needsLogin()) return setStatusText("Nicht angemeldet", "error");
  if (noList) return setStatusText("Keine Liste", "error");
  if (online === false) {
    return setStatusText(pending ? `Offline · ${pending} ausstehend` : "Offline", "pending");
  }
  if (pending) return setStatusText(`${pending} ausstehend`, "pending");
  if (!S.lastSync) return setStatusText("Verbinde …", "pending");
  const time = new Date(S.lastSync).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  return setStatusText(`Synchron · ${time}`, "ok");
}

const NO_LIST_HINT =
  "Noch keine Einkaufsliste eingerichtet. In Home Assistant unter Einstellungen → Geräte &amp; Dienste → " +
  "Integration hinzufügen → „Einkaufsliste“ anlegen.";

function render() {
  $("#title").textContent = S.listName || "Einkaufsliste";
  document.title = S.listName || "Einkaufsliste";
  renderStatus();

  let banner = "";
  if (needsLogin()) {
    banner = `<div class="banner">Einmal mit deinem Home-Assistant-Benutzer anmelden, danach bleibt die App angemeldet.
      <button class="primary text" data-action="login">Anmelden</button></div>`;
  } else if (noList) {
    banner = `<div class="banner">${NO_LIST_HINT}</div>`;
  }

  const items = currentItems();
  const open = items.filter((i) => !i.checked);
  const done = items.filter((i) => i.checked);
  let html = banner;
  if (!open.length && !banner) html += `<div class="empty">Nichts mehr zu kaufen ✓</div>`;
  html += open.map(row).join("");
  if (done.length) {
    html += `
      <div class="done-header">
        <button class="link" data-action="toggle-done">${doneExpanded ? "▴" : "▾"} Erledigt (${done.length})</button>
        <button class="link danger" data-action="clear">Erledigte löschen</button>
      </div>`;
    if (doneExpanded) html += done.map(row).join("");
  }
  $("#list").innerHTML = html;

  $("#sugg").innerHTML = S.base.history
    .slice(0, 200)
    .map((h) => `<option value="${esc(h.name)}"></option>`)
    .join("");
}

function row(item) {
  const qty = fmtQty(item);
  const step = STEP[item.unit] ?? 1;
  let qtyHtml = "";
  if (!item.checked && item.quantity != null) {
    qtyHtml = `
      <div class="stepper">
        <button data-action="dec" aria-label="Weniger"${item.quantity - step <= 0 ? " disabled" : ""}>−</button>
        <span class="qty">${esc(qty)}</span>
        <button data-action="inc" aria-label="Mehr">+</button>
      </div>`;
  } else if (qty) {
    qtyHtml = `<span class="qty">${esc(qty)}</span>`;
  }
  return `
    <div class="item${item.checked ? " checked" : ""}" data-id="${esc(item.id)}">
      <input type="checkbox" data-action="toggle"${item.checked ? " checked" : ""} aria-label="Abhaken" />
      <div class="text" data-action="toggle">
        <div class="name">${esc(item.name)}</div>
        ${item.note ? `<div class="note">${esc(item.note)}</div>` : ""}
      </div>
      ${qtyHtml}
      <button class="icon" data-action="${item.checked ? "delete" : "edit"}" aria-label="${item.checked ? "Löschen" : "Bearbeiten"}">${item.checked ? "✕" : "✎"}</button>
    </div>`;
}

// ------------------------------------------------------------------ Bedienung

$("#add").elements.unit.innerHTML = unitOptions("");
$("#edit form").elements.unit.innerHTML = unitOptions("");

$("#add").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const f = ev.target.elements;
  const name = f.name.value.trim();
  if (!name) return;
  const quantity = parseNumber(f.quantity.value);
  if (Number.isNaN(quantity)) {
    alert("Ungültige Menge");
    return;
  }
  const op = { op: "add", id: newId(), name };
  if (quantity != null) op.quantity = quantity;
  if (f.unit.value) op.unit = f.unit.value;
  if (f.note.value.trim()) op.note = f.note.value.trim();
  ev.target.reset();
  f.name.focus();
  queueOp(op);
});

$("#add").elements.name.addEventListener("input", (ev) => {
  const unit = $("#add").elements.unit;
  const known = S.base.history.find((h) => h.name.toLowerCase() === ev.target.value.trim().toLowerCase());
  if (known?.unit && !unit.value) unit.value = known.unit;
});

$("#list").addEventListener("click", (ev) => {
  const target = ev.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  if (action === "login") return login();
  if (action === "toggle-done") {
    doneExpanded = !doneExpanded;
    return render();
  }
  if (action === "clear") {
    const ids = currentItems().filter((i) => i.checked).map((i) => i.id);
    if (ids.length) queueOp({ op: "remove", item_ids: ids });
    return;
  }
  const id = target.closest(".item")?.dataset.id;
  const item = currentItems().find((i) => i.id === id);
  if (!item) return;
  if (action === "toggle") {
    queueOp({ op: "update", item_id: id, changes: { checked: !item.checked } });
  } else if (action === "inc" || action === "dec") {
    const step = STEP[item.unit] ?? 1;
    const q = round3(item.quantity + (action === "inc" ? step : -step));
    if (q > 0) queueOp({ op: "update", item_id: id, changes: { quantity: q } });
  } else if (action === "edit") {
    openEdit(item);
  } else if (action === "delete") {
    queueOp({ op: "remove", item_ids: [id] });
  }
});

// ------------------------------------------------------------------ Bearbeiten

const editDialog = $("#edit");
const editForm = $("#edit form");

function openEdit(item) {
  editId = item.id;
  const f = editForm.elements;
  f.name.value = item.name;
  f.quantity.value = item.quantity == null ? "" : fmtNumber(item.quantity);
  f.unit.value = item.unit || "";
  f.note.value = item.note || "";
  editDialog.showModal();
}

editForm.addEventListener("submit", (ev) => {
  ev.preventDefault();
  const f = editForm.elements;
  const quantity = parseNumber(f.quantity.value);
  if (Number.isNaN(quantity)) {
    alert("Ungültige Menge");
    return;
  }
  if (!f.name.value.trim()) return;
  queueOp({
    op: "update",
    item_id: editId,
    changes: { name: f.name.value.trim(), quantity, unit: f.unit.value || null, note: f.note.value },
  });
  editDialog.close();
});
editForm.querySelector('[data-edit="cancel"]').addEventListener("click", () => editDialog.close());
editForm.querySelector('[data-edit="delete"]').addEventListener("click", () => {
  queueOp({ op: "remove", item_ids: [editId] });
  editDialog.close();
});

// ------------------------------------------------------------------ Einstellungen

function setSettingsMsg(text, kind = "") {
  const el = $("#settings-msg");
  el.textContent = text;
  el.className = `msg ${kind}`;
}

async function openSettings() {
  $("#main").hidden = true;
  $("#settings").hidden = false;
  $("#logout").hidden = INGRESS || needsLogin();
  const select = $("#list-select");
  select.innerHTML = S.listId ? `<option value="${esc(S.listId)}">${esc(S.listName)}</option>` : "";
  if (needsLogin()) return setSettingsMsg("Nicht angemeldet.", "error");
  setSettingsMsg("Lade Listen …");
  try {
    const lists = await fetchLists();
    if (!lists) return setSettingsMsg("Noch keine Einkaufsliste eingerichtet.", "error");
    select.innerHTML = lists
      .map((l) => `<option value="${esc(l.list_id)}"${l.list_id === S.listId ? " selected" : ""}>${esc(l.name)}</option>`)
      .join("");
    setSettingsMsg("");
  } catch (err) {
    setSettingsMsg(err instanceof AuthError ? "Nicht angemeldet." : "Home Assistant nicht erreichbar.", "error");
  }
}

function closeSettings() {
  $("#settings").hidden = true;
  $("#main").hidden = false;
}

$("#settings-btn").addEventListener("click", () => ($("#settings").hidden ? openSettings() : closeSettings()));
$("#status").addEventListener("click", () => (needsLogin() ? login() : scheduleSync()));
$("#cancel-settings").addEventListener("click", closeSettings);

$("#save-settings").addEventListener("click", () => {
  const select = $("#list-select");
  const listId = select.value;
  if (!listId) return closeSettings();
  if (listId !== S.listId) {
    if (S.queue.length && !confirm(`${S.queue.length} nicht übertragene Änderungen gehen verloren. Trotzdem wechseln?`)) return;
    S.base = { items: [], history: [] };
    S.queue = [];
    S.lastSync = null;
  }
  S.listId = listId;
  S.listName = select.options[select.selectedIndex].textContent;
  saveState();
  closeSettings();
  render();
  scheduleSync();
});

$("#logout").addEventListener("click", async () => {
  if (S.queue.length && !confirm(`${S.queue.length} nicht übertragene Änderungen gehen verloren. Trotzdem abmelden?`)) return;
  await logout();
  closeSettings();
  render();
});

// ------------------------------------------------------------------ Start

if (!INGRESS && "serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("sw.js").catch((err) => console.warn("Service Worker:", err));
  $("#sw-hint").textContent = "Offline-Start ist aktiv: Die App startet auch ohne Verbindung.";
} else if (!INGRESS) {
  $("#sw-hint").textContent =
    "Hinweis: Ohne HTTPS kann die App nicht ohne Verbindung gestartet werden. Änderungen werden trotzdem " +
    "gespeichert, solange die App offen bleibt. Für vollen Offline-Betrieb über HTTPS öffnen (z. B. Nabu-Casa-Adresse).";
}

window.addEventListener("online", () => scheduleSync());
window.addEventListener("offline", () => {
  online = false;
  render();
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") scheduleSync();
});
setInterval(() => {
  if (document.visibilityState === "visible") sync();
}, SYNC_INTERVAL);

(async () => {
  if (!INGRESS) {
    await finishLogin();
    if (!auth) adoptHomeAssistantLogin();
  }
  render();
  // Erster Start ohne Anmeldung: direkt zur Anmeldeseite
  if (needsLogin() && !S.lastSync && navigator.onLine) return login();
  scheduleSync();
})();
