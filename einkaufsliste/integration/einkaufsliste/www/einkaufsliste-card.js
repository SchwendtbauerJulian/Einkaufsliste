/**
 * Einkaufsliste-Karte für Home Assistant
 *
 * type: custom:einkaufsliste-card
 * entity: todo.einkaufsliste
 * title: Einkauf            (optional)
 * show_checked: true        (optional, erledigte Artikel anzeigen)
 */

const CARD_VERSION = "1.3.0";

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
/** Notiz und wer den Artikel auf die Liste gesetzt hat: "Bio · von Anna" */
const noteLine = (item) => [item.note, item.added_by && `von ${item.added_by}`].filter(Boolean).join(" · ");
const parseNumber = (s) => {
  const v = String(s).trim().replace(",", ".");
  if (v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : NaN;
};

const unitOptions = (selected) =>
  `<option value="">–</option>` +
  UNIT_GROUPS.map(
    (g) =>
      `<optgroup label="${g.label}">${g.units
        .map(([v, l]) => `<option value="${v}" ${v === selected ? "selected" : ""}>${l}</option>`)
        .join("")}</optgroup>`
  ).join("");

// Märkte & Kategorien kommen vom Server: [{ key, name, categories: [{ key, name }] }]
const options = (list, selected, empty) =>
  `<option value="">${empty}</option>` +
  list.map((e) => `<option value="${esc(e.key)}" ${e.key === selected ? "selected" : ""}>${esc(e.name)}</option>`).join("");
const productLabel = (p, markets) => {
  const market = markets.find((m) => m.key === p.market);
  return [market?.name, market?.categories.find((c) => c.key === p.category)?.name].filter(Boolean).join(" · ");
};

// Produktname ohne Menge und Einheit ("2 kg Mehl" -> "Mehl"), wie parsing.py
const UNIT_ALIASES = [
  "stk", "stk.", "stück", "stueck", "st.", "x", "pkg", "pkg.", "pck", "pck.", "packung", "packungen", "pack", "päckchen",
  "dose", "dosen", "flasche", "flaschen", "fl", "fl.", "bund", "bd.", "bd", "g", "gr", "gr.", "gramm",
  "kg", "kilo", "kilogramm", "ml", "milliliter", "l", "liter", "ltr", "ltr.",
];
const UNIT_RE = UNIT_ALIASES.sort((a, b) => b.length - a.length)
  .map((u) => u.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
  .join("|");
const NUM = String.raw`\d+(?:[.,]\d+)?`;
const NAME_PATTERNS = [
  new RegExp(String.raw`^\s*(?<name>.+?)\s*\(\s*${NUM}\s*(?:${UNIT_RE})?\s*\)\s*$`, "iu"),
  new RegExp(String.raw`^\s*${NUM}\s*(?:(?:${UNIT_RE})(?=[\s)]|$)\s*|\s+)(?<name>.+?)\s*$`, "iu"),
  new RegExp(String.raw`^\s*(?<name>.+?)\s*[-–:,]?\s*${NUM}\s*(?:${UNIT_RE})\s*$`, "iu"),
];
const productKey = (text) => {
  for (const re of NAME_PATTERNS) {
    const m = text.trim().match(re);
    if (m) return m.groups.name.trim().toLowerCase();
  }
  return text.trim().toLowerCase();
};

/** Offene Artikel nach Markt und ggf. Kategorie gruppiert (Reihenfolge wie im Geschäft). */
function groupedRows(items, products, marketList, rowHtml) {
  const index = (list, key) => {
    const i = list.findIndex((e) => e.key === key);
    return i < 0 ? list.length : i;
  };
  const sorted = items
    .map((item) => {
      const p = products.get(item.name.toLowerCase());
      const m = index(marketList, p?.market);
      return { item, m, c: index(marketList[m]?.categories ?? [], p?.category) };
    })
    .sort((a, b) => a.m - b.m || a.c - b.c);
  let html = "";
  let lastM = null;
  let lastC = null;
  for (const { item, m, c } of sorted) {
    if (m !== lastM) {
      html += `<div class="group">${esc(marketList[m]?.name ?? "Nicht zugeordnet")}</div>`;
      lastM = m;
      lastC = null;
    }
    const categories = marketList[m]?.categories ?? [];
    if (categories.length && c !== lastC) {
      html += `<div class="subgroup">${esc(categories[c]?.name ?? "Ohne Kategorie")}</div>`;
      lastC = c;
    }
    html += rowHtml(item);
  }
  return html;
}

/** Kategorien des gewählten Markts; ohne Kategorien bleibt das Feld ausgeblendet. */
function updateCategoryField(form, markets, category = form.elements.category.value) {
  const categories = markets.find((m) => m.key === form.elements.market.value)?.categories ?? [];
  form.elements.category.innerHTML = options(categories, category, "Ohne Kategorie");
  form.querySelector(".category").hidden = !categories.length;
}

/** Markt und Kategorie im Formular setzen. */
function fillProduct(form, markets, product) {
  form.elements.market.value = product?.market ?? "";
  form.elements.market.setCustomValidity("");
  updateCategoryField(form, markets, product?.category ?? "");
}

/** Markt-Auswahl im Formular einrichten (getMarkets liefert die aktuellen Märkte). */
function setupMarketField(form, getMarkets) {
  form.elements.market.addEventListener("change", () => {
    delete form.elements.market.dataset.auto;
    form.elements.market.setCustomValidity("");
    updateCategoryField(form, getMarkets());
  });
  updateCategoryField(form, getMarkets());
}

/** Markt (und Kategorie) aus dem Formular, falls gewählt. */
function marketPayload(form) {
  const market = form.elements.market.value;
  return market ? { market, category: form.elements.category.value || null } : {};
}

class EinkaufslisteCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._items = [];
    this._history = [];
    this._products = new Map(); // name (klein) -> { name, market, category }
    this._markets = [];
    this._marketsShown = null;
    this._unsub = null;
    this._listId = null;
    this._built = false;
    this._doneExpanded = false;
    this._editId = null;
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find((id) => id.startsWith("todo.") && hass.states[id].attributes.list_id);
    return { entity: entity || "todo.einkaufsliste" };
  }

  setConfig(config) {
    if (!config.entity) throw new Error("Bitte 'entity' angeben (z. B. todo.einkaufsliste)");
    this._config = { show_checked: true, ...config };
    this._built = false;
    this._unsubscribe();
    if (this._hass) this.hass = this._hass;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._updateHeader();
    this._ensureSubscription();
  }

  connectedCallback() {
    this._ensureSubscription();
  }

  disconnectedCallback() {
    this._unsubscribe();
  }

  getCardSize() {
    return 3 + this._items.filter((i) => !i.checked).length;
  }

  // ------------------------------------------------------------ Verbindung

  _ensureSubscription() {
    if (!this._hass || !this._config || !this.isConnected) return;
    const listId = this._hass.states[this._config.entity]?.attributes?.list_id;
    if (!listId) {
      this._showError(`Entität ${this._config.entity} ist keine Einkaufsliste dieser Integration.`);
      return;
    }
    if (this._unsub && this._listId === listId) return;
    this._unsubscribe();
    this._listId = listId;
    this._unsub = this._hass.connection
      .subscribeMessage((data) => this._onData(data), { type: "einkaufsliste/subscribe", list_id: listId })
      .catch((err) => {
        this._showError(err.message || String(err));
        return null;
      });
  }

  _unsubscribe() {
    if (this._unsub) {
      this._unsub.then((unsub) => unsub && unsub()).catch(() => {});
      this._unsub = null;
    }
  }

  _onData(data) {
    this._items = data.items || [];
    this._history = data.history || [];
    this._products = new Map((data.products || []).map((p) => [p.name.toLowerCase(), p]));
    this._markets = data.markets || [];
    this._renderMarketSelect();
    this._showError(null);
    if (this._editId && !this._items.some((i) => i.id === this._editId)) this._closeEdit();
    this._renderList();
    this._renderSuggestions();
    this._updateHeader();
  }

  async _ws(type, payload = {}) {
    try {
      return await this._hass.callWS({ type: `einkaufsliste/${type}`, list_id: this._listId, ...payload });
    } catch (err) {
      this._showError(err.message || String(err));
      throw err;
    }
  }

  // ------------------------------------------------------------ Aufbau

  _build() {
    if (!this._config) return;
    this._built = true;
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card>
        <div class="header">
          <div class="title"></div>
          <div class="count"></div>
        </div>
        <form class="add" autocomplete="off">
          <input class="name" name="name" list="sugg" placeholder="z. B. 2 kg Mehl" aria-label="Artikel" enterkeyhint="done" />
          <input class="qty" name="quantity" inputmode="decimal" placeholder="Menge" />
          <select class="unit" name="unit" aria-label="Einheit">${unitOptions("")}</select>
          <button type="submit" class="primary" aria-label="Hinzufügen"><ha-icon icon="mdi:plus"></ha-icon></button>
          <div class="product">
            <select name="market" aria-label="Markt">${options(this._markets, "", "Markt wählen …")}</select>
            <select class="category" name="category" aria-label="Kategorie"></select>
          </div>
          <input class="note-input" name="note" placeholder="Notiz (optional), z. B. Marke" aria-label="Notiz" />
        </form>
        <div class="error" hidden></div>
        <div class="edit" hidden></div>
        <div class="list"></div>
        <datalist id="sugg"></datalist>
      </ha-card>`;

    const root = this.shadowRoot;
    this._form = root.querySelector("form.add");
    this._form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      this._add();
    });
    this._form.elements.name.addEventListener("input", () => this._prefillFromHistory());
    setupMarketField(this._form, () => this._markets);
    root.querySelector(".list").addEventListener("click", (ev) => this._onListClick(ev));
    this._renderList();
  }

  _updateHeader() {
    if (!this._built || !this._hass) return;
    const st = this._hass.states[this._config.entity];
    const title = this._config.title ?? st?.attributes?.friendly_name ?? "Einkaufsliste";
    const open = this._items.filter((i) => !i.checked).length;
    this.shadowRoot.querySelector(".title").textContent = title;
    this.shadowRoot.querySelector(".count").textContent = open ? `${open} offen` : "";
  }

  _showError(message) {
    const el = this.shadowRoot.querySelector(".error");
    if (!el) return;
    el.hidden = !message;
    el.textContent = message || "";
  }

  /** Autovervollständigung: oft gekaufte Artikel zuerst, dann alle übrigen bekannten Produkte. */
  _renderSuggestions() {
    const el = this.shadowRoot.querySelector("#sugg");
    if (!el) return;
    const names = new Map(this._history.map((h) => [h.name.toLowerCase(), h.name]));
    for (const [key, p] of this._products) if (!names.has(key)) names.set(key, p.name);
    el.innerHTML = [...names]
      .slice(0, 500)
      .map(([key, name]) => {
        const p = this._products.get(key);
        return `<option value="${esc(name)}">${p ? esc(productLabel(p, this._markets)) : ""}</option>`;
      })
      .join("");
  }

  /** Auswahl der Märkte neu aufbauen, wenn sie sich geändert haben (Admin-Modus). */
  _renderMarketSelect() {
    const json = JSON.stringify(this._markets);
    if (!this._form || json === this._marketsShown) return;
    this._marketsShown = json;
    const f = this._form.elements;
    const category = f.category.value;
    f.market.innerHTML = options(this._markets, f.market.value, "Markt wählen …");
    updateCategoryField(this._form, this._markets, category);
  }

  _prefillFromHistory() {
    const form = this._form;
    const key = form.elements.name.value.trim().toLowerCase();
    const known = this._history.find((h) => h.name.toLowerCase() === key);
    if (known?.unit && !form.elements.unit.value) form.elements.unit.value = known.unit;

    // Markt und Kategorie eines bekannten Produkts vorbelegen
    const market = form.elements.market;
    const product = this._products.get(productKey(form.elements.name.value));
    if (product) {
      fillProduct(form, this._markets, product);
      market.dataset.auto = "1";
    } else if (market.dataset.auto) {
      fillProduct(form, this._markets, null);
      delete market.dataset.auto;
    }
  }

  // ------------------------------------------------------------ Liste

  _renderList() {
    const el = this.shadowRoot.querySelector(".list");
    if (!el) return;
    const open = this._items.filter((i) => !i.checked);
    const done = this._items.filter((i) => i.checked);
    let html = "";

    if (!open.length) {
      html += `<div class="empty"><ha-icon icon="mdi:cart-check"></ha-icon> Nichts mehr zu kaufen</div>`;
    } else {
      html += groupedRows(open, this._products, this._markets, (i) => this._row(i));
    }

    if (this._config.show_checked && done.length) {
      html += `
        <div class="done-header">
          <button class="link" data-action="toggle-done">
            <ha-icon icon="mdi:chevron-${this._doneExpanded ? "up" : "down"}"></ha-icon>
            Erledigt (${done.length})
          </button>
          <button class="link danger" data-action="clear">Erledigte löschen</button>
        </div>`;
      if (this._doneExpanded) html += done.map((i) => this._row(i)).join("");
    }
    el.innerHTML = html;
  }

  _row(item) {
    const qty = fmtQty(item);
    const step = STEP[item.unit] ?? 1;
    let qtyHtml = "";
    if (!item.checked && item.quantity != null) {
      qtyHtml = `
        <div class="stepper">
          <button data-action="dec" aria-label="Weniger" ${item.quantity - step <= 0 ? "disabled" : ""}>−</button>
          <span class="qtytext">${esc(qty)}</span>
          <button data-action="inc" aria-label="Mehr">+</button>
        </div>`;
    } else if (qty) {
      qtyHtml = `<span class="qtytext">${esc(qty)}</span>`;
    }
    return `
      <div class="item ${item.checked ? "checked" : ""}" data-id="${esc(item.id)}">
        <input type="checkbox" data-action="toggle" ${item.checked ? "checked" : ""} aria-label="Abhaken" />
        <div class="text" data-action="toggle">
          <div class="iname">${esc(item.name)}</div>
          ${noteLine(item) ? `<div class="note">${esc(noteLine(item))}</div>` : ""}
        </div>
        ${qtyHtml}
        <button class="icon" data-action="${item.checked ? "delete" : "edit"}" aria-label="${item.checked ? "Löschen" : "Bearbeiten"}">
          <ha-icon icon="mdi:${item.checked ? "close" : "pencil"}"></ha-icon>
        </button>
      </div>`;
  }

  async _onListClick(ev) {
    const target = ev.target.closest("[data-action]");
    if (!target) return;
    const action = target.dataset.action;
    const id = target.closest(".item")?.dataset.id;
    const item = this._items.find((i) => i.id === id);

    if (action === "toggle-done") {
      this._doneExpanded = !this._doneExpanded;
      this._renderList();
      return;
    }
    if (action === "clear") {
      await this._ws("clear_checked").catch(() => {});
      return;
    }
    if (!item) return;

    try {
      if (action === "toggle") {
        await this._ws("update", { item_id: id, checked: !item.checked });
      } else if (action === "inc" || action === "dec") {
        const step = STEP[item.unit] ?? 1;
        const q = Math.round((item.quantity + (action === "inc" ? step : -step)) * 1000) / 1000;
        if (q > 0) await this._ws("update", { item_id: id, quantity: q });
      } else if (action === "edit") {
        this._openEdit(item);
      } else if (action === "delete") {
        await this._ws("remove", { item_ids: [id] });
      }
    } catch (_err) {
      this._renderList(); // Checkbox-Zustand zurücksetzen
    }
  }

  // ------------------------------------------------------------ Hinzufügen

  async _add() {
    const form = this._form;
    const name = form.elements.name.value.trim();
    if (!name) return;
    const payload = { name };
    const qty = parseNumber(form.elements.quantity.value);
    if (Number.isNaN(qty)) {
      this._showError("Ungültige Menge");
      return;
    }
    if (qty != null) payload.quantity = qty;
    if (form.elements.unit.value) payload.unit = form.elements.unit.value;
    if (form.elements.note.value.trim()) payload.note = form.elements.note.value.trim();
    // Neues Produkt: Markt muss beim ersten Anlegen festgelegt werden
    if (!form.elements.market.value && this._markets.length && !this._products.has(productKey(name))) {
      form.elements.market.setCustomValidity("Neues Produkt – bitte Markt wählen");
      form.elements.market.reportValidity();
      return;
    }
    Object.assign(payload, marketPayload(form));
    try {
      await this._ws("add", payload);
      form.reset();
      delete form.elements.market.dataset.auto;
      updateCategoryField(form, this._markets, "");
      form.elements.name.focus();
    } catch (_err) {
      /* Fehler wird angezeigt */
    }
  }

  // ------------------------------------------------------------ Bearbeiten

  _openEdit(item) {
    this._editId = item.id;
    const product = this._products.get(item.name.toLowerCase());
    const el = this.shadowRoot.querySelector(".edit");
    el.hidden = false;
    el.innerHTML = `
      <form autocomplete="off">
        <div class="edit-title">Artikel bearbeiten</div>
        <label>Name<input name="name" value="${esc(item.name)}" required /></label>
        <div class="row">
          <label>Menge<input name="quantity" inputmode="decimal" value="${item.quantity == null ? "" : esc(fmtNumber(item.quantity))}" /></label>
          <label>Einheit<select name="unit">${unitOptions(item.unit || "")}</select></label>
        </div>
        <div class="row">
          <label>Markt<select name="market">${options(this._markets, product?.market ?? "", "Markt wählen …")}</select></label>
          <label class="category">Kategorie<select name="category"></select></label>
        </div>
        <label>Notiz<input name="note" value="${esc(item.note || "")}" placeholder="z. B. Marke, Bio, …" /></label>
        <div class="buttons">
          <button type="button" class="link danger" data-edit="delete">Löschen</button>
          <span class="spacer"></span>
          <button type="button" class="link" data-edit="cancel">Abbrechen</button>
          <button type="submit" class="primary text">Speichern</button>
        </div>
      </form>`;
    const form = el.querySelector("form");
    setupMarketField(form, () => this._markets);
    updateCategoryField(form, this._markets, product?.category ?? "");
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      this._saveEdit(form);
    });
    el.querySelector('[data-edit="cancel"]').addEventListener("click", () => this._closeEdit());
    el.querySelector('[data-edit="delete"]').addEventListener("click", async () => {
      await this._ws("remove", { item_ids: [this._editId] }).catch(() => {});
      this._closeEdit();
    });
    form.elements.name.focus();
    el.scrollIntoView({ block: "nearest" });
  }

  async _saveEdit(form) {
    const qty = parseNumber(form.elements.quantity.value);
    if (Number.isNaN(qty)) {
      this._showError("Ungültige Menge");
      return;
    }
    try {
      await this._ws("update", {
        item_id: this._editId,
        name: form.elements.name.value,
        quantity: qty,
        unit: form.elements.unit.value || null,
        note: form.elements.note.value,
        ...marketPayload(form),
      });
      this._closeEdit();
    } catch (_err) {
      /* Fehler wird angezeigt */
    }
  }

  _closeEdit() {
    this._editId = null;
    const el = this.shadowRoot.querySelector(".edit");
    if (el) {
      el.hidden = true;
      el.innerHTML = "";
    }
  }
}

const STYLES = `
  ha-card { padding: 16px; }
  .header { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 12px; }
  .title { font-size: 1.4em; font-weight: 500; color: var(--primary-text-color); }
  .count { color: var(--secondary-text-color); font-size: 0.9em; }
  input, select {
    font: inherit; color: var(--primary-text-color);
    background: var(--secondary-background-color, #f5f5f5);
    border: 1px solid var(--divider-color, #ddd); border-radius: 8px;
    padding: 8px 10px; min-width: 0; box-sizing: border-box;
  }
  input:focus, select:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; }
  .add { display: grid; grid-template-columns: 1fr 72px 76px 42px; gap: 6px; margin-bottom: 8px; }
  .add .note-input, .add .product { grid-column: 1 / -1; }
  .add .product { display: flex; gap: 6px; }
  .add .product select { flex: 1; }
  .group {
    margin: 14px 0 2px; font-size: 0.8em; font-weight: 500; letter-spacing: 0.04em;
    text-transform: uppercase; color: var(--primary-color);
  }
  .group:first-child { margin-top: 4px; }
  .subgroup { margin: 8px 0 0; font-size: 0.8em; color: var(--secondary-text-color); }
  [hidden] { display: none !important; }
  button { font: inherit; cursor: pointer; }
  button.primary {
    background: var(--primary-color); color: var(--text-primary-color, #fff);
    border: none; border-radius: 8px; display: flex; align-items: center; justify-content: center;
  }
  button.primary.text { padding: 8px 16px; }
  button.link { background: none; border: none; color: var(--primary-color); padding: 6px 4px; display: inline-flex; align-items: center; gap: 2px; }
  button.danger { color: var(--error-color, #db4437); }
  button.icon {
    background: none; border: none; color: var(--secondary-text-color);
    width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex: none;
  }
  button.icon:hover { background: var(--secondary-background-color); }
  .error { color: var(--error-color, #db4437); padding: 6px 0; }
  .item {
    display: flex; align-items: center; gap: 8px; padding: 4px 0;
    border-bottom: 1px solid var(--divider-color, #eee);
  }
  .item:last-child { border-bottom: none; }
  .item input[type="checkbox"] {
    width: 22px; height: 22px; flex: none; margin: 0 4px; accent-color: var(--primary-color); cursor: pointer;
  }
  .text { flex: 1; min-width: 0; cursor: pointer; padding: 6px 0; }
  .iname { color: var(--primary-text-color); overflow-wrap: anywhere; }
  .note { color: var(--secondary-text-color); font-size: 0.85em; overflow-wrap: anywhere; }
  .checked .iname { text-decoration: line-through; color: var(--disabled-text-color, #999); }
  .qtytext { white-space: nowrap; color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
  .checked .qtytext { color: var(--disabled-text-color, #999); }
  .stepper { display: flex; align-items: center; gap: 4px; flex: none; }
  .stepper .qtytext { min-width: 52px; text-align: center; }
  .stepper button {
    width: 28px; height: 28px; border-radius: 50%; border: 1px solid var(--divider-color, #ddd);
    background: none; color: var(--primary-text-color); line-height: 1; padding: 0;
  }
  .stepper button:disabled { opacity: 0.35; cursor: default; }
  .empty { color: var(--secondary-text-color); text-align: center; padding: 16px 0; }
  .done-header { display: flex; justify-content: space-between; margin-top: 12px; }
  .edit {
    border: 1px solid var(--primary-color); border-radius: 12px; padding: 12px; margin: 8px 0;
  }
  .edit form { display: flex; flex-direction: column; gap: 8px; }
  .edit-title { font-weight: 500; }
  .edit label { display: flex; flex-direction: column; gap: 2px; font-size: 0.85em; color: var(--secondary-text-color); flex: 1; }
  .edit .row { display: flex; gap: 8px; }
  .buttons { display: flex; align-items: center; gap: 8px; }
  .spacer { flex: 1; }
`;

if (!customElements.get("einkaufsliste-card")) {
  customElements.define("einkaufsliste-card", EinkaufslisteCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "einkaufsliste-card",
  name: "Einkaufsliste",
  description: "Einkaufsliste mit Mengen (Stück, Gewicht, Volumen) und Abhaken.",
});

console.info(`%c EINKAUFSLISTE-CARD %c v${CARD_VERSION} `, "background:#4caf50;color:#fff", "");
