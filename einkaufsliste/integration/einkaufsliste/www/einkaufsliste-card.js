/**
 * Einkaufsliste-Karte für Home Assistant
 *
 * type: custom:einkaufsliste-card
 * entity: todo.einkaufsliste
 * title: Einkauf            (optional)
 * show_checked: true        (optional, erledigte Artikel anzeigen)
 */

const CARD_VERSION = "1.1.0";

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

const unitOptions = (selected) =>
  `<option value="">–</option>` +
  UNIT_GROUPS.map(
    (g) =>
      `<optgroup label="${g.label}">${g.units
        .map(([v, l]) => `<option value="${v}" ${v === selected ? "selected" : ""}>${l}</option>`)
        .join("")}</optgroup>`
  ).join("");

class EinkaufslisteCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._items = [];
    this._history = [];
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

  _renderSuggestions() {
    const el = this.shadowRoot.querySelector("#sugg");
    if (!el) return;
    el.innerHTML = this._history
      .slice(0, 200)
      .map((h) => `<option value="${esc(h.name)}"></option>`)
      .join("");
  }

  _prefillFromHistory() {
    const form = this._form;
    const key = form.elements.name.value.trim().toLowerCase();
    const known = this._history.find((h) => h.name.toLowerCase() === key);
    if (!known) return;
    if (known.unit && !form.elements.unit.value) form.elements.unit.value = known.unit;
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
      html += open.map((i) => this._row(i)).join("");
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
          ${item.note ? `<div class="note">${esc(item.note)}</div>` : ""}
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
    try {
      await this._ws("add", payload);
      form.reset();
      form.elements.name.focus();
    } catch (_err) {
      /* Fehler wird angezeigt */
    }
  }

  // ------------------------------------------------------------ Bearbeiten

  _openEdit(item) {
    this._editId = item.id;
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
        <label>Notiz<input name="note" value="${esc(item.note || "")}" placeholder="z. B. Marke, Bio, …" /></label>
        <div class="buttons">
          <button type="button" class="link danger" data-edit="delete">Löschen</button>
          <span class="spacer"></span>
          <button type="button" class="link" data-edit="cancel">Abbrechen</button>
          <button type="submit" class="primary text">Speichern</button>
        </div>
      </form>`;
    const form = el.querySelector("form");
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
  .add .note-input { grid-column: 1 / -1; }
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
