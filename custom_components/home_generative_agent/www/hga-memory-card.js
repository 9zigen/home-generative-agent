const HGA_MEMORY_I18N = {
  en: {
    title: "HGA Memories",
    refresh: "Refresh",
    search: "Search",
    shared: "Shared (unknown voice)",
    empty: "No memories.",
    no_match: "Nothing matches the search.",
    limit: "{n} of {max}",
    updated: "Changed {when}",
    edit: "Edit",
    save: "Save",
    cancel: "Cancel",
    move: "Move to",
    remove: "Delete",
    confirm_remove: "Delete this memory?\n\n{text}",
    failed: "Failed: {msg}",
    admin_only: "Only an administrator can manage memories.",
  },
  ru: {
    title: "Воспоминания HGA",
    refresh: "Обновить",
    search: "Поиск",
    shared: "Общие (неизвестный голос)",
    empty: "Воспоминаний нет.",
    no_match: "Ничего не найдено.",
    limit: "{n} из {max}",
    updated: "Изменено {when}",
    edit: "Изменить",
    save: "Сохранить",
    cancel: "Отмена",
    move: "Переместить к",
    remove: "Удалить",
    confirm_remove: "Удалить это воспоминание?\n\n{text}",
    failed: "Ошибка: {msg}",
    admin_only: "Управлять воспоминаниями может только администратор.",
  },
};

const HGA_SHARED_MEMORY_USER = "robot";

class HgaMemoryCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
  }

  getCardSize() {
    return 6;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._started) {
      this._started = true;
      this._build();
      this._load();
    }
  }

  _t(key, values = {}) {
    const lang = (this._hass?.language || "en").split("-")[0];
    const text = (HGA_MEMORY_I18N[lang] || HGA_MEMORY_I18N.en)[key];
    return Object.entries(values).reduce(
      (out, [name, value]) => out.replace(`{${name}}`, value),
      text,
    );
  }

  _el(tag, props = {}, ...children) {
    const node = Object.assign(document.createElement(tag), props);
    node.append(...children);
    return node;
  }

  _label(user) {
    return user === HGA_SHARED_MEMORY_USER ? this._t("shared") : user;
  }

  async _call(service, data) {
    const result = await this._hass.callWS({
      type: "call_service",
      domain: "home_generative_agent",
      service,
      service_data: data,
      return_response: true,
    });
    return result.response;
  }

  _build() {
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    root.replaceChildren();
    const style = document.createElement("style");
    style.textContent = `
      .wrap { padding: 16px; }
      header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
      h2 { flex: 1; margin: 0; font-size: 18px; font-weight: 500; }
      .people { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
      .people button.active { background: var(--primary-color); color: var(--text-primary-color); }
      input, textarea, select { box-sizing: border-box; font: inherit; color: var(--primary-text-color);
        background: var(--card-background-color); border: 1px solid var(--divider-color);
        border-radius: 6px; padding: 8px; }
      input.search, textarea { width: 100%; }
      button { font: inherit; cursor: pointer; padding: 6px 10px; border-radius: 6px; color: var(--primary-text-color);
        background: transparent; border: 1px solid var(--divider-color); min-height: 36px; }
      .memory { padding: 10px 0; border-top: 1px solid var(--divider-color); }
      .text { white-space: pre-wrap; overflow-wrap: anywhere; }
      .meta { color: var(--secondary-text-color); font-size: 12px; margin: 4px 0 8px; }
      .actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
      .message { color: var(--secondary-text-color); padding: 12px 0; }
      .error { color: var(--error-color); padding: 8px 0; }
    `;
    this._people = this._el("div", { className: "people" });
    this._list = this._el("div");
    this._error = this._el("div", { className: "error" });
    this._search = this._el("input", {
      className: "search",
      type: "search",
      placeholder: this._t("search"),
      oninput: () => this._renderList(),
    });
    const header = this._el(
      "header",
      {},
      this._el("h2", { textContent: this._t("title") }),
      this._el("button", {
        textContent: this._t("refresh"),
        onclick: () => this._load(),
      }),
    );
    root.append(
      style,
      this._el(
        "ha-card",
        {},
        this._el(
          "div",
          { className: "wrap" },
          header,
          this._people,
          this._search,
          this._error,
          this._list,
        ),
      ),
    );
  }

  async _guard(action) {
    this._error.textContent = "";
    try {
      await action();
    } catch (err) {
      this._error.textContent =
        err?.code === "unauthorized"
          ? this._t("admin_only")
          : this._t("failed", { msg: err?.message || String(err) });
    }
  }

  async _load() {
    await this._guard(async () => {
      let data = await this._call("get_memories", {});
      const known = data.people.some((p) => p.user === this._user);
      if (!known) {
        const first = data.people.find((p) => p.count) || data.people[0];
        this._user = first?.user;
      }
      if (this._user) {
        data = await this._call("get_memories", { user: this._user });
      }
      this._data = data;
      this._editing = null;
      this._renderPeople();
      this._renderList();
    });
  }

  _renderPeople() {
    const { people, limit } = this._data;
    this._people.replaceChildren(
      ...people.map((person) => {
        const count = limit
          ? this._t("limit", { n: person.count, max: limit })
          : String(person.count);
        return this._el("button", {
          textContent: `${this._label(person.user)} · ${count}`,
          className: person.user === this._user ? "active" : "",
          onclick: () => {
            this._user = person.user;
            this._load();
          },
        });
      }),
    );
  }

  _when(iso) {
    return new Date(iso).toLocaleString(this._hass.language);
  }

  _renderList() {
    const memories = this._data?.memories || [];
    const wanted = this._search.value.trim().toLowerCase();
    const shown = memories.filter((m) =>
      `${m.content} ${m.context}`.toLowerCase().includes(wanted),
    );
    if (!shown.length) {
      const key = memories.length ? "no_match" : "empty";
      this._list.replaceChildren(
        this._el("div", { className: "message", textContent: this._t(key) }),
      );
      return;
    }
    this._list.replaceChildren(
      ...shown.map((m) =>
        m.id === this._editing ? this._editor(m) : this._row(m),
      ),
    );
  }

  _row(memory) {
    const user = this._user;
    const targets = this._data.people.filter((p) => p.user !== user);
    const move = this._el(
      "select",
      {
        ariaLabel: this._t("move"),
        onchange: (event) =>
          this._guard(async () => {
            await this._call("move_memory", {
              user,
              memory_id: memory.id,
              to_user: event.target.value,
            });
            await this._load();
          }),
      },
      this._el("option", {
        textContent: this._t("move"),
        value: "",
        selected: true,
        disabled: true,
      }),
      ...targets.map((p) =>
        this._el("option", { textContent: this._label(p.user), value: p.user }),
      ),
    );
    const parts = [
      this._el("div", { className: "text", textContent: memory.content }),
    ];
    if (memory.context) {
      parts.push(
        this._el("div", { className: "meta", textContent: memory.context }),
      );
    }
    parts.push(
      this._el("div", {
        className: "meta",
        textContent: this._t("updated", { when: this._when(memory.updated_at) }),
      }),
      this._el(
        "div",
        { className: "actions" },
        this._el("button", {
          textContent: this._t("edit"),
          onclick: () => {
            this._editing = memory.id;
            this._renderList();
          },
        }),
        move,
        this._el("button", {
          textContent: this._t("remove"),
          onclick: () => this._remove(memory),
        }),
      ),
    );
    return this._el("div", { className: "memory" }, ...parts);
  }

  _remove(memory) {
    if (!window.confirm(this._t("confirm_remove", { text: memory.content }))) {
      return;
    }
    this._guard(async () => {
      await this._call("delete_memory", {
        user: this._user,
        memory_id: memory.id,
      });
      await this._load();
    });
  }

  _editor(memory) {
    const content = this._el("textarea", { rows: 3, value: memory.content });
    const save = () =>
      this._guard(async () => {
        const text = content.value.trim();
        if (!text) {
          return;
        }
        await this._call("update_memory", {
          user: this._user,
          memory_id: memory.id,
          content: text,
          context: memory.context,
        });
        await this._load();
      });
    return this._el(
      "div",
      { className: "memory" },
      content,
      this._el(
        "div",
        { className: "actions" },
        this._el("button", { textContent: this._t("save"), onclick: save }),
        this._el("button", {
          textContent: this._t("cancel"),
          onclick: () => {
            this._editing = null;
            this._renderList();
          },
        }),
      ),
    );
  }
}

// HGA loads this file itself; a hand-added Resources entry would load it again.
if (!customElements.get("hga-memory-card")) {
  customElements.define("hga-memory-card", HgaMemoryCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "hga-memory-card",
    name: "HGA Memories",
    description: "Browse, search, edit, move and delete long-term memories per person.",
  });
}
