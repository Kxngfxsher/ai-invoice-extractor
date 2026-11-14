"use strict";

const state = { docs: [], selectedId: null, doc: null, config: null, stats: null };

const VERDICT = { ready: "готов", check: "проверить", attention: "внимание" };
const STATUS = { approved: "подтверждён", rejected: "отклонён" };
const SEVERITY = { error: 3, warning: 2, info: 1 };
const SECTIONS = [
  ["Документ", [
    ["doc_type", "Вид", "w2", "select"], ["number", "Номер", "w2"], ["date", "Дата", "w2", "date"], ["basis", "Основание", ""],
  ]],
  ["Поставщик", [["seller.name", "Название", ""], ["seller.inn", "ИНН", "w3"], ["seller.kpp", "КПП", "w3"]]],
  ["Покупатель", [["buyer.name", "Название", ""], ["buyer.inn", "ИНН", "w3"], ["buyer.kpp", "КПП", "w3"]]],
  ["Банковские реквизиты", [
    ["bank.bank_name", "Банк", "w4"], ["bank.bik", "БИК", "w2"], ["bank.account", "Расчётный счёт", "w3"], ["bank.corr_account", "Корр. счёт", "w3"],
  ]],
];

const $ = (selector, root = document) => root.querySelector(selector);

/** Создаёт DOM-узел. Строки всегда вставляются как текст, поэтому содержимое документов не исполняется. */
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

async function api(path, options = {}) {
  const init = { method: options.method || "GET" };
  if (options.form) init.body = options.form;
  else if (options.body) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, init);
  if (!response.ok) {
    let message = `Ошибка ${response.status}`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail)) message = data.detail.map((item) => `${item.loc.slice(1).join(".")}: ${item.msg}`).join("; ");
    } catch { /* тело ответа не JSON */ }
    throw new Error(message);
  }
  return response.json();
}

// --- Форматирование ---------------------------------------------------------------------------

const moneyFmt = new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const numberFmt = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 3 });
const timeFmt = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

const money = (value) => (value === null || value === undefined ? "" : moneyFmt.format(value));
const dateRu = (iso) => (/^\d{4}-\d{2}-\d{2}$/.test(iso || "") ? iso.split("-").reverse().join(".") : iso || "");

function parseNum(text) {
  const cleaned = String(text).replace(/[\s  ]/g, "").replace(",", ".");
  if (cleaned === "") return null;
  const value = Number(cleaned);
  return Number.isFinite(value) ? value : null;
}

function fmtDuration(minutes) {
  const total = Math.max(0, Math.round(minutes));
  if (total < 60) return `${total} мин`;
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  return rest ? `${hours} ч ${rest} мин` : `${hours} ч`;
}

function getPath(data, path) {
  return path.split(".").reduce((value, key) => (value === null || value === undefined ? value : value[key]), data);
}

function setPath(data, path, value) {
  const keys = path.split(".");
  const last = keys.pop();
  keys.reduce((target, key) => target[key], data)[last] = value;
}

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = isError ? "toast error" : "toast";
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, isError ? 7000 : 3000);
}

async function run(button, action) {
  if (button) button.disabled = true;
  try {
    return await action();
  } catch (error) {
    toast(error.message, true);
    return null;
  } finally {
    if (button) button.disabled = false;
  }
}

// --- Загрузка -----------------------------------------------------------------------------------

async function loadConfig() {
  const config = await api("/api/config");
  state.config = config;
  $("#company").textContent = config.company;
  const engine = $("#engine");
  if (config.engine === "claude") {
    engine.textContent = `Движок: ${config.model}`;
    engine.classList.add("live");
    engine.title = "Документы читает Claude: текстовые PDF, сканы и фотографии. Реквизиты и суммы проверяет код.";
  } else {
    engine.textContent = "Движок: правила, без LLM";
    engine.title = "Демо-режим без ключа API: разбираются PDF с текстовым слоем в знакомых макетах. Добавьте ANTHROPIC_API_KEY в .env, чтобы документы читал Claude.";
  }
  $("#samples").hidden = !config.demo_mode;
  $("#btn-reset").hidden = !config.demo_mode;
  const banner = $("#banner");
  banner.textContent = config.engine_error
    ? `Claude недоступен (${config.engine_error}). Документы разбирает резервный движок правил.`
    : "";
  banner.hidden = !config.engine_error;
}

async function refresh() {
  const requests = [api("/api/documents"), api("/api/stats")];
  if (state.config.demo_mode) requests.push(api("/api/samples"));
  const [docs, stats, samples] = await Promise.all(requests);
  state.docs = docs;
  state.stats = stats;
  renderStats();
  renderList();
  if (samples) renderSamples(samples);
}

function show(doc) {
  state.doc = doc;
  state.selectedId = doc ? doc.id : null;
  renderList();
  renderPreview();
  renderForm();
}

async function applyDoc(doc) {
  show(doc);
  await refresh();
}

// --- Показатели, список, примеры ----------------------------------------------------------------

function renderStats() {
  const s = state.stats;
  const untouched = s.untouched_rate === null ? "—" : `${Math.round(s.untouched_rate * 100)}%`;
  const tiles = [
    ["Документов", s.total, `извлечено полей: ${s.fields_extracted}`],
    ["Ждут проверки", s.waiting, s.attention ? `требуют внимания: ${s.attention}` : "без критичных замечаний", s.attention ? "bad" : "ok"],
    ["Подтверждено", s.approved, `на сумму ${moneyFmt.format(s.approved_sum)} ₽`],
    ["Найдено проблем", s.problems_found, "ошибки и риски до оплаты"],
    ["Принято без правок", untouched, "доля подтверждённых как есть"],
    ["Экономия времени", fmtDuration(s.time_saved_minutes), `оценка: ${s.manual_minutes_per_document} мин на документ`],
  ];
  $("#stats").replaceChildren(...tiles.map(([label, value, note, tone]) =>
    h("div", { class: "tile" },
      h("div", { class: "tile-label" }, label),
      h("div", { class: "tile-value" }, value),
      h("div", { class: `tile-note ${tone || ""}` }, note),
    )));
}

function chipFor(doc) {
  if (doc.status !== "new") return h("span", { class: `chip ${doc.status}` }, STATUS[doc.status]);
  return h("span", { class: `chip ${doc.verdict}` }, VERDICT[doc.verdict]);
}

function renderList() {
  const list = $("#docs");
  if (!state.docs.length) {
    list.replaceChildren(h("li", { class: "empty" }, "Документов пока нет. Загрузите файл или выберите пример."));
    return;
  }
  list.replaceChildren(...state.docs.map((doc) => {
    const title = doc.number ? `${doc.doc_type_label} № ${doc.number}` : doc.filename;
    return h("li", {
      class: `item ${doc.id === state.selectedId ? "selected" : ""}`,
      tabindex: "0",
      onclick: () => show(doc),
      onkeydown: (event) => { if (event.key === "Enter") show(doc); },
    },
      h("div", { class: "item-top" },
        h("span", { class: "item-title" }, title),
        h("span", { class: "sum" }, doc.total === null ? "" : `${money(doc.total)} ₽`),
      ),
      h("div", { class: "item-bottom" },
        h("span", { class: "who" }, [doc.seller_name || "поставщик не распознан", dateRu(doc.doc_date)].filter(Boolean).join(" · ")),
        chipFor(doc),
      ),
    );
  }));
}

function renderSamples(samples) {
  const select = $("#samples");
  select.replaceChildren(
    h("option", { value: "" }, "Добавить пример…"),
    ...samples.map((sample) => h("option", { value: sample.file, disabled: sample.loaded },
      `${sample.title}${sample.known_layout ? "" : " (незнакомый макет)"}${sample.loaded ? " ✓" : ""}`)),
  );
}

// --- Просмотр и форма ---------------------------------------------------------------------------

function renderPreview() {
  const root = $("#preview");
  const doc = state.doc;
  if (!doc) {
    root.replaceChildren(h("div", { class: "placeholder" }, "Выберите документ в списке слева"));
    return;
  }
  root.replaceChildren(
    h("div", { class: "preview-head" }, h("b", null, doc.filename), h("span", null, `загружен ${timeFmt.format(new Date(doc.uploaded_at))}`)),
    h("img", { src: `/api/documents/${doc.id}/preview`, alt: "Первая страница документа", loading: "lazy" }),
  );
  root.scrollTop = 0;
}

function worstIssue(issues, field) {
  return issues.filter((issue) => issue.field === field).sort((a, b) => SEVERITY[b.level] - SEVERITY[a.level])[0];
}

function field(path, label, width, kind, doc, editable) {
  const value = getPath(doc.data, path);
  const issue = worstIssue(doc.issues, path);
  const attrs = { "data-path": path, class: issue ? issue.level : null, disabled: !editable };
  let control;
  if (kind === "select") {
    control = h("select", attrs, Object.entries(state.config.doc_types).map(([code, title]) =>
      h("option", { value: code, selected: code === value }, title)));
  } else {
    const isDate = kind === "date" && (!value || /^\d{4}-\d{2}-\d{2}$/.test(value));
    control = h("input", { ...attrs, type: isDate ? "date" : "text", autocomplete: "off", spellcheck: "false" });
    control.value = value === null || value === undefined ? "" : value;
  }
  return h("label", { class: `field ${width}` }, h("span", null, label), control, issue ? h("small", { class: issue.level }, issue.message) : null);
}

function lineRow(item, index, doc, editable) {
  const amountIssue = worstIssue(doc.issues, `items.${index}.amount`);
  const cell = (key, value, extra = "") => {
    const input = h("input", {
      "data-item": key,
      class: `${extra} ${key === "amount" && amountIssue ? amountIssue.level : ""}`,
      disabled: !editable,
      autocomplete: "off",
      inputmode: extra ? "decimal" : null,
      "aria-label": key,
    });
    input.value = value === null || value === undefined ? "" : value;
    return input;
  };
  const row = h("tr", null,
    h("td", null, cell("name", item.name)),
    h("td", { class: "c-qty" }, cell("quantity", item.quantity === null ? "" : numberFmt.format(item.quantity), "num")),
    h("td", { class: "c-unit" }, cell("unit", item.unit)),
    h("td", { class: "c-price" }, cell("price", money(item.price), "num")),
    h("td", { class: "c-sum" }, cell("amount", money(item.amount), "num")),
    h("td", { class: "c-del" }, editable ? h("button", { class: "row-del", type: "button", title: "Удалить строку", "aria-label": "Удалить строку", onclick: () => row.remove() }, "×") : null),
  );
  return row;
}

function collect(form, doc) {
  const data = JSON.parse(JSON.stringify(doc.data));
  for (const control of form.querySelectorAll("[data-path]")) {
    const raw = control.value.trim();
    setPath(data, control.dataset.path, raw === "" ? null : raw);
  }
  data.total = parseNum($("[data-total=total]", form).value);
  const rate = parseNum($("[data-total=vat_rate]", form).value);
  data.vat_rate = rate === null ? null : Math.round(rate);
  data.vat_amount = parseNum($("[data-total=vat_amount]", form).value);
  data.items = [...form.querySelectorAll(".lines tbody tr")].map((row) => {
    const value = (key) => $(`[data-item=${key}]`, row).value.trim();
    return {
      name: value("name"),
      quantity: parseNum(value("quantity")),
      unit: value("unit") || null,
      price: parseNum(value("price")),
      amount: parseNum(value("amount")),
    };
  }).filter((item) => item.name);
  return data;
}

function renderForm() {
  const root = $("#form");
  const doc = state.doc;
  if (!doc) {
    root.replaceChildren(h("div", { class: "placeholder" }, "Здесь появятся извлечённые данные и результаты проверки"));
    return;
  }
  const editable = doc.status === "new";
  const data = doc.data;
  const title = data.number ? `${doc.doc_type_label} № ${data.number}` : doc.filename;

  const form = h("form", { class: "f-body", onsubmit: (event) => event.preventDefault() });
  const focusField = (path) => {
    const target = form.querySelector(`[data-path="${path}"], [data-total="${path}"]`)
      || (path && path.startsWith("items.") ? form.querySelectorAll(".lines tbody tr")[Number(path.split(".")[1])]?.querySelector("[data-item=amount]") : null);
    if (target) { target.scrollIntoView({ block: "center", behavior: "smooth" }); target.focus({ preventScroll: true }); }
  };

  const issues = [...doc.issues].sort((a, b) => SEVERITY[b.level] - SEVERITY[a.level]);
  form.append(issues.length
    ? h("ul", { class: "issues" }, issues.map((issue) =>
        h("li", null, h("button", { class: `issue ${issue.level}`, type: "button", onclick: () => focusField(issue.field) }, issue.message))))
    : h("div", { class: "all-good" }, "Замечаний нет: реквизиты проходят контрольные суммы, арифметика сходится."));

  for (const [legend, fields] of SECTIONS) {
    form.append(h("fieldset", null, h("legend", null, legend),
      h("div", { class: "grid" }, fields.map(([path, label, width, kind]) => field(path, label, width, kind, doc, editable)))));
  }

  const body = h("tbody", null, data.items.map((item, index) => lineRow(item, index, doc, editable)));
  const itemsIssue = worstIssue(doc.issues, "items");
  form.append(h("fieldset", null, h("legend", null, "Позиции"),
    h("table", { class: "lines" },
      h("thead", null, h("tr", null,
        h("th", null, "Наименование"), h("th", { class: "num" }, "Кол-во"), h("th", null, "Ед."),
        h("th", { class: "num" }, "Цена"), h("th", { class: "num" }, "Сумма"), h("th", null))),
      body),
    h("div", { class: "lines-foot" },
      h("span", null, itemsIssue ? itemsIssue.message : `Строк: ${data.items.length}`),
      editable ? h("button", { class: "link", type: "button", onclick: () => body.append(lineRow({ name: "", quantity: null, unit: null, price: null, amount: null }, body.children.length, { issues: [] }, true)) }, "Добавить строку") : null),
  ));

  const totalField = (key, label, width, value) => {
    const issue = worstIssue(doc.issues, key);
    const input = h("input", { "data-total": key, class: issue ? issue.level : null, disabled: !editable, inputmode: "decimal", autocomplete: "off" });
    input.value = value;
    return h("label", { class: `field ${width}` }, h("span", null, label), input, issue ? h("small", { class: issue.level }, issue.message) : null);
  };
  form.append(h("fieldset", null, h("legend", null, "Итоги"),
    h("div", { class: "grid" },
      totalField("total", "Сумма к оплате, ₽", "w2", money(data.total)),
      totalField("vat_rate", "Ставка НДС, %", "w2", data.vat_rate === null ? "" : data.vat_rate),
      totalField("vat_amount", "Сумма НДС, ₽", "w2", money(data.vat_amount)),
    )));

  if (editable) {
    const save = h("button", { class: "btn", type: "button", onclick: (event) => run(event.target, async () => {
      const updated = await api(`/api/documents/${doc.id}`, { method: "PUT", body: collect(form, doc) });
      toast(updated.verdict === "ready" ? "Сохранено, замечаний больше нет" : "Сохранено и проверено заново");
      await applyDoc(updated);
    }) }, "Сохранить и перепроверить");
    const approve = h("button", { class: "btn primary", type: "button", onclick: (event) => run(event.target, async () => {
      const saved = await api(`/api/documents/${doc.id}`, { method: "PUT", body: collect(form, doc) });
      if (saved.verdict === "attention" && !confirm("В документе остались ошибки. Подтвердить его всё равно?")) {
        await applyDoc(saved);
        return;
      }
      toast("Документ подтверждён и попадёт в выгрузку");
      await applyDoc(await api(`/api/documents/${doc.id}/approve`, { method: "POST" }));
    }) }, "Подтвердить");
    const reject = h("button", { class: "btn ghost danger", type: "button", onclick: (event) => run(event.target, async () => {
      await applyDoc(await api(`/api/documents/${doc.id}/reject`, { method: "POST" }));
    }) }, "Отклонить");
    form.append(h("div", { class: "actions" }, approve, save, reject));
  } else {
    form.append(h("div", { class: "actions" },
      h("span", { class: "decision" }, `${doc.status === "approved" ? "Подтверждён" : "Отклонён"} ${timeFmt.format(new Date(doc.decided_at))}${doc.edited ? " · с правками оператора" : ""}`),
      h("button", { class: "btn ghost", type: "button", onclick: (event) => run(event.target, async () => {
        await applyDoc(await api(`/api/documents/${doc.id}/reopen`, { method: "POST" }));
      }) }, "Вернуть в работу")));
  }

  const meta = doc.meta;
  const engineLine = meta.engine === "claude"
    ? `${meta.model} · ${meta.latency_ms} мс · ${meta.input_tokens || 0} → ${meta.output_tokens || 0} токенов` + (meta.cost_usd ? ` · $${meta.cost_usd.toFixed(4)}` : "")
    : `Разобрано правилами, без LLM · ${meta.latency_ms} мс`;
  form.append(h("p", { class: "engine-line" }, meta.note ? `${meta.note}. ` : "", engineLine));

  root.replaceChildren(
    h("header", { class: "f-head" },
      h("h2", null, title),
      h("div", { class: "f-tags" }, chipFor(doc), doc.edited ? h("span", { class: "chip neutral" }, "есть правки") : null,
        h("span", { class: "chip neutral" }, `замечаний: ${doc.issues.filter((issue) => issue.level !== "info").length}`))),
    form,
  );
  root.scrollTop = 0;
}

// --- Действия в шапке -----------------------------------------------------------------------------

function setupActions() {
  $("#samples").addEventListener("change", (event) => run(event.target, async () => {
    const name = event.target.value;
    if (!name) return;
    const doc = await api(`/api/samples/${encodeURIComponent(name)}`, { method: "POST" });
    toast(`Документ разобран: ${VERDICT[doc.verdict]}`);
    await applyDoc(doc);
  }));

  const fileInput = $("#file");
  $("#btn-upload").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => run($("#btn-upload"), async () => {
    const file = fileInput.files[0];
    fileInput.value = "";
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    toast("Разбираю документ…");
    const doc = await api("/api/documents", { method: "POST", form });
    toast(`Документ разобран: ${VERDICT[doc.verdict]}`);
    await applyDoc(doc);
  }));

  $("#btn-reset").addEventListener("click", (event) => run(event.target, async () => {
    await api("/api/demo/reset", { method: "POST" });
    show(null);
    await refresh();
    toast("Демо-данные обновлены");
  }));
}

async function start() {
  setupActions();
  show(null);
  try {
    await loadConfig();
    await refresh();
    const wanted = Number(new URLSearchParams(location.search).get("open"));
    const first = state.docs.find((doc) => doc.id === wanted) || state.docs.find((doc) => doc.status === "new") || state.docs[0];
    if (first) show(first);
  } catch (error) {
    toast(`Не удалось загрузить данные: ${error.message}`, true);
  }
}

start();
