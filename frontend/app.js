"use strict";

/* ============================================================================
   AI Coder — клиент. Мотион по apple-design: пружины (§4-6), 1:1 drag (§2),
   velocity handoff (§5), momentum projection (§6), rubber-band (§9),
   interruptible (§3 — springs стартуют от текущего значения).
   ============================================================================ */

const $ = (s) => document.querySelector(s);
const el = (t, c, txt) => { const e = document.createElement(t); if (c) e.className = c; if (txt != null) e.textContent = txt; return e; };
const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

const state = { csrf: null, project: null, conversationId: null, running: false,
                currentAssistant: null, toolEls: {}, models: [], model: null };

// ---------- API ----------
async function api(path, opts = {}) {
  opts.headers = opts.headers || {};
  if (opts.method && opts.method !== "GET") {
    opts.headers["Content-Type"] = "application/json";
    if (state.csrf) opts.headers["x-csrf-token"] = state.csrf;
  }
  return fetch(path, opts);
}

// ============================================================================
//  Пружина: анимирует скаляр от текущего значения к target, с учётом velocity.
//  Прерываема — новый вызов начинается от актуального значения (§3).
// ============================================================================
function animateSpring({ from, to, velocity = 0, response = 0.4, damping = 1.0, onUpdate, onDone }) {
  if (reduceMotion()) { onUpdate(to); onDone && onDone(); return () => {}; }
  const omega = (2 * Math.PI) / response;
  let x = from, v = velocity, last = performance.now(), raf = 0, cancelled = false;
  function frame(now) {
    if (cancelled) return;
    const dt = Math.min((now - last) / 1000, 1 / 30); last = now;
    const a = -omega * omega * (x - to) - 2 * damping * omega * v;  // §4 spring
    v += a * dt; x += v * dt;
    if (Math.abs(x - to) < 0.5 && Math.abs(v) < 0.5) { onUpdate(to); onDone && onDone(); return; }
    onUpdate(x); raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);
  return () => { cancelled = true; cancelAnimationFrame(raf); };
}
// §6 momentum projection (Apple's exponential-decay form)
const project = (v, decel = 0.998) => (v / 1000) * decel / (1 - decel);
// §9 rubber-band resistance beyond a boundary
const rubberband = (over, dim, c = 0.55) => (over * dim * c) / (dim + c * Math.abs(over));

// ============================================================================
//  Scrim + Sheets (нижние/левый) с жестами
// ============================================================================
const scrim = $("#scrim");
let activeSheet = null;
function hideScrimIfIdle() { if (!activeSheet) { scrim.hidden = true; scrim.style.opacity = 0; } }

class Sheet {
  constructor(elm, side) { this.el = elm; this.side = side; this.size = 0; this.pos = 0; this._cancel = null; this._bindDrag(); }

  _setPos(p) {
    this.pos = p;
    this.el.style.transform = this.side === "bottom" ? `translateY(${p}px)` : `translateX(${-p}px)`;
    const progress = this.size ? 1 - p / this.size : 0;
    scrim.style.opacity = Math.max(0, Math.min(1, progress)) * 0.4;
  }
  present() {
    if (activeSheet && activeSheet !== this) activeSheet.dismiss(true);
    activeSheet = this;
    this.el.hidden = false; scrim.hidden = false;
    this.size = (this.side === "bottom" ? this.el.offsetHeight : this.el.offsetWidth) || 320;
    this._setPos(this.size);
    requestAnimationFrame(() => this._to(0));
  }
  dismiss(immediate, velocity = 0) {
    const done = () => { this.el.hidden = true; if (activeSheet === this) activeSheet = null; hideScrimIfIdle(); };
    if (immediate) { this._cancelAnim(); this._setPos(this.size); done(); return; }
    this._to(this.size, velocity, done);
  }
  _to(target, velocity = 0, onDone) {
    this._cancelAnim();
    const bounce = target !== 0 ? 1.0 : 0.86; // лёгкий overshoot при раскрытии
    this._cancel = animateSpring({ from: this.pos, to: target, velocity, response: 0.42, damping: bounce,
      onUpdate: (v) => this._setPos(v), onDone: () => { this._cancel = null; onDone && onDone(); } });
  }
  _cancelAnim() { if (this._cancel) { this._cancel(); this._cancel = null; } }

  _bindDrag() {
    const e = this.el;
    let start = null, lastP = 0, lastT = 0, vel = 0, engaged = false;
    const noDrag = (t) => t.closest("button, a, input, textarea, pre, .list, .git-body, .segment, .tabs, .sheet-scroll");

    e.addEventListener("pointerdown", (ev) => {
      if (this.side === "bottom" && noDrag(ev.target)) return;   // низ: тянем только за «шапку»
      start = { x: ev.clientX, y: ev.clientY, pos: this.pos };
      lastP = this.side === "bottom" ? ev.clientY : ev.clientX; lastT = ev.timeStamp; vel = 0;
      engaged = this.side === "bottom";                          // низ — сразу, левый — по оси
      if (engaged) { this._cancelAnim(); e.setPointerCapture(ev.pointerId); }
    });
    e.addEventListener("pointermove", (ev) => {
      if (!start) return;
      const dx = ev.clientX - start.x, dy = ev.clientY - start.y;
      if (!engaged) { // левый лист: включаемся только на горизонтальном свайпе
        if (Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy)) { engaged = true; this._cancelAnim(); e.setPointerCapture(ev.pointerId); }
        else if (Math.abs(dy) > 10) { start = null; return; }
        else return;
      }
      const cur = this.side === "bottom" ? ev.clientY : ev.clientX;
      const dt = (ev.timeStamp - lastT) || 16;
      vel = ((cur - lastP) / dt) * 1000 * (this.side === "bottom" ? 1 : -1);
      lastP = cur; lastT = ev.timeStamp;
      let raw = start.pos + (this.side === "bottom" ? dy : -dx);
      if (raw < 0) raw = -rubberband(-raw, this.size);           // §9 сопротивление сверх открытого
      this._setPos(raw);
      ev.preventDefault();
    });
    const end = () => {
      if (!start) return; const dragged = engaged; start = null; engaged = false;
      if (!dragged) return;
      const projected = this.pos + project(vel);                 // §6 куда «долетит»
      if (projected > this.size * 0.35 || vel > 700) this.dismiss(false, vel); // §5 velocity handoff
      else this._to(0, vel);
    };
    e.addEventListener("pointerup", end);
    e.addEventListener("pointercancel", end);
  }
}

let sheets = {};
function openSheet(name) { sheets[name].present(); }
function closeSheet(name) { sheets[name] && sheets[name].dismiss(false); }
scrim.addEventListener("click", () => { if (activeSheet) activeSheet.dismiss(false); closeDialog(); });

// ---------- Диалог (материализация blur+scale, §12) ----------
let pendingCallId = null;
function showDialog(elm) {
  scrim.hidden = false; scrim.style.opacity = 0.4;
  elm.hidden = false; elm.style.transition = "none";
  elm.style.transform = "translate(-50%,-50%) scale(0.92)"; elm.style.opacity = "0";
  requestAnimationFrame(() => {
    elm.style.transition = reduceMotion() ? "opacity 180ms ease"
      : "transform 320ms cubic-bezier(0.2,0,0,1), opacity 200ms ease";
    elm.style.transform = "translate(-50%,-50%) scale(1)"; elm.style.opacity = "1";
  });
}
function closeDialog() {
  const d = $("#confirm-dialog"); if (d.hidden) return;
  d.style.transform = "translate(-50%,-50%) scale(0.94)"; d.style.opacity = "0";
  setTimeout(() => { d.hidden = true; hideScrimIfIdle(); }, 200);
}

// ============================================================================
//  Boot / auth
// ============================================================================
async function boot() {
  const data = await (await fetch("/api/me")).json();
  if (data.authenticated) { state.csrf = data.csrf; showApp(); }
  else $("#login-view").hidden = false;
}
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errBox = $("#login-error"); errBox.hidden = true;
  const r = await api("/api/login", { method: "POST", body: JSON.stringify({
    username: $("#login-user").value.trim(), password: $("#login-pass").value }) });
  const data = await r.json();
  if (data.ok) { state.csrf = data.csrf; $("#login-view").hidden = true; showApp(); }
  else { errBox.textContent = data.error || "Ошибка входа."; errBox.hidden = false; }
});

async function showApp() {
  $("#app-view").hidden = false;
  sheets = {
    chats: new Sheet($("#sheet-chats"), "left"),
    projects: new Sheet($("#sheet-projects"), "bottom"),
    settings: new Sheet($("#sheet-settings"), "bottom"),
    git: new Sheet($("#sheet-git"), "bottom"),
  };
  await loadProjects();
  await loadSettings();
  if (state.project) newChat();
}

// ============================================================================
//  Проекты
// ============================================================================
let projectsCache = [], canCreate = false;
async function loadProjects(selectName) {
  const data = await (await api("/api/projects")).json();
  projectsCache = data.projects; canCreate = data.can_create;
  const wanted = selectName && projectsCache.find((p) => p.name === selectName);
  const first = wanted || projectsCache.find((p) => p.available);
  if (first) { state.project = first.name; $("#project-name").textContent = first.name; }
}
function renderProjectsSheet() {
  const list = $("#projects-list"); list.innerHTML = "";
  projectsCache.forEach((p) => {
    const b = el("button", "list-item pressable");
    b.appendChild(el("div", "title", p.name + (p.available ? "" : " · нет")));
    if (p.kind === "custom") b.appendChild(el("div", "when", "создан в UI"));
    if (!p.available) b.disabled = true;
    b.addEventListener("click", () => { selectProject(p.name); });
    list.appendChild(b);
  });
  if (canCreate) {
    const b = el("button", "list-item pressable");
    b.appendChild(el("div", "title", "＋ Новый проект"));
    b.addEventListener("click", createProject);
    list.appendChild(b);
  }
}
function selectProject(name) {
  state.project = name; $("#project-name").textContent = name;
  closeSheet("projects"); newChat();
}
async function createProject() {
  const name = prompt("Имя нового проекта (латиница, цифры, дефис):", "");
  if (!name) return;
  const r = await api("/api/projects/new", { method: "POST", body: JSON.stringify({ name: name.trim() }) });
  const data = await r.json();
  if (!r.ok) { alert("Не удалось: " + (data.detail || r.status)); return; }
  await loadProjects(data.project.name); renderProjectsSheet();
  selectProject(data.project.name);
}
$("#btn-project").addEventListener("click", () => { renderProjectsSheet(); openSheet("projects"); });

// ============================================================================
//  Настройки — переключатель модели (segmented control)
// ============================================================================
async function loadSettings() {
  const data = await (await api("/api/settings")).json();
  state.models = data.available_models; state.model = data.model;
  buildSegment();
}
function buildSegment() {
  const seg = $("#model-segment");
  seg.querySelectorAll("button").forEach((b) => b.remove());
  const n = state.models.length;
  state.models.forEach((m, i) => {
    const b = el("button", null, m.replace("deepseek-", ""));
    b.setAttribute("aria-selected", String(m === state.model));
    b.addEventListener("click", () => switchModel(m, i));
    seg.appendChild(b);
  });
  positionPill();
}
function positionPill() {
  const i = Math.max(0, state.models.indexOf(state.model));
  const n = state.models.length || 1;
  const pill = $("#seg-pill");
  pill.style.width = `calc((100% - 6px) / ${n})`;
  pill.style.transform = `translateX(calc(${i} * 100%))`;
}
async function switchModel(m, i) {
  const prev = state.model; state.model = m;
  $("#model-segment").querySelectorAll("button").forEach((b, idx) =>
    b.setAttribute("aria-selected", String(idx === i)));
  positionPill();
  const r = await api("/api/settings/model", { method: "POST", body: JSON.stringify({ model: m }) });
  if (!r.ok) { state.model = prev; buildSegment(); alert("Не удалось переключить модель."); }
}
$("#btn-settings").addEventListener("click", () => openSheet("settings"));
$("#btn-logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" }); location.reload();
});

// ============================================================================
//  Чаты (история)
// ============================================================================
$("#btn-menu").addEventListener("click", async () => { await loadChats(); openSheet("chats"); });
$("#btn-new-chat").addEventListener("click", () => { newChat(); closeSheet("chats"); });
async function loadChats() {
  const data = await (await api("/api/chats")).json();
  const list = $("#chats-list"); list.innerHTML = "";
  data.chats.forEach((c) => {
    const b = el("button", "list-item pressable");
    b.appendChild(el("div", "title", c.title || "Без названия"));
    b.appendChild(el("div", "when", `${c.project} · ${new Date(c.updated_at).toLocaleString()}`));
    b.addEventListener("click", () => openChat(c.id));
    list.appendChild(b);
  });
  if (!data.chats.length) list.appendChild(el("div", "muted", "Пока нет чатов."));
}
async function openChat(id) {
  const r = await api("/api/chat/" + id); if (!r.ok) return;
  const conv = await r.json();
  state.conversationId = conv.id; state.project = conv.project;
  $("#project-name").textContent = conv.project;
  $("#chat").innerHTML = ""; state.currentAssistant = null;
  conv.messages.forEach((m) => {
    if (m.role === "user") addUser(m.content);
    else if (m.role === "assistant" && m.content) { const a = startAssistant(); a.innerHTML = mdToHtml(m.content); state.currentAssistant = null; }
  });
  closeSheet("chats"); scrollDown();
}
function newChat() {
  state.conversationId = null; $("#chat").innerHTML = "";
  addNote(`Новая задача в проекте «${state.project || "—"}». Опишите, что сделать.`);
}

// ============================================================================
//  Рендер сообщений
// ============================================================================
function addUser(text) { $("#chat").appendChild(el("div", "msg user", text)); scrollDown(); }
function startAssistant() { const m = el("div", "msg assistant"); $("#chat").appendChild(m); state.currentAssistant = m; scrollDown(); return m; }
function appendAssistant(d) {
  if (!state.currentAssistant) startAssistant();
  const m = state.currentAssistant;
  m._raw = (m._raw || "") + d;
  m.innerHTML = mdToHtml(m._raw);
  scrollDown();
}
function addNote(t) { $("#chat").appendChild(el("div", "msg system-note", t)); scrollDown(); }

const ICON = { read_file: "📄", list_files: "📁", search_files: "🔎", write_file: "✏️", edit_file: "✏️", terminal: "▶", git: "🔀" };
const VERB = { read_file: "Читаю", list_files: "Смотрю папку", search_files: "Ищу", write_file: "Пишу", edit_file: "Правлю", terminal: "Терминал", git: "Git" };
// Человекочитаемая подпись действия из имени и аргументов инструмента.
function toolLabel(name, args, preview) {
  args = args || {};
  if (name === "read_file" || name === "write_file" || name === "edit_file") return `${VERB[name]} ${args.path || ""}`.trim();
  if (name === "list_files") return `${VERB[name]}: ${args.path || "."}`;
  if (name === "search_files") return `${VERB[name]} «${args.query || ""}»`;
  if (name === "terminal") return preview || args.command || "Терминал";
  if (name === "git") return preview || ("git " + (Array.isArray(args.args) ? args.args.join(" ") : ""));
  return preview || name || "Инструмент";
}
function addTool(id, name, preview, args) {
  const d = el("details", "tool"); const s = el("summary");
  s.appendChild(el("span", "t-ico", ICON[name] || "🛠"));
  s.appendChild(el("span", "t-name", toolLabel(name, args, preview) || name || "инструмент"));
  const badge = el("span", "badge run", "…"); s.appendChild(badge);
  d.appendChild(s); const pre = el("pre"); pre.hidden = true; d.appendChild(pre);
  d._badge = badge; d._pre = pre; $("#chat").appendChild(d); state.toolEls[id] = d; scrollDown(); return d;
}
function setToolResult(id, ok, summary, content, extra) {
  const d = state.toolEls[id]; if (!d) return;
  d._badge.textContent = ok ? "готово" : "ошибка"; d._badge.className = "badge " + (ok ? "ok" : "err");
  if (summary) d.querySelector(".t-name").textContent = summary;   // точная подпись из бэкенда
  const body = (extra && extra.diff) ? null : (content || "");
  if (extra && extra.diff) { renderDiff(d._pre, extra.diff); d._pre.hidden = false; }
  else if (body.trim()) { d._pre.textContent = body; d._pre.hidden = false; }
  else { d._pre.hidden = true; }                                    // пустой вывод — не показываем
  scrollDown();
}
function renderDiff(pre, diff) {
  pre.textContent = "";
  diff.split("\n").forEach((line) => {
    let c = null;
    if (line.startsWith("+") && !line.startsWith("+++")) c = "diff-add";
    else if (line.startsWith("-") && !line.startsWith("---")) c = "diff-del";
    pre.appendChild(el("span", c, line + "\n"));
  });
}
function scrollDown() { const c = $("#chat"); c.scrollTop = c.scrollHeight; }

// ---------- Компактный безопасный Markdown → HTML ----------
function escapeHtml(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function mdInline(s) {
  s = escapeHtml(s);
  s = s.replace(/`([^`]+)`/g, (m, c) => "<code>" + c + "</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/__([^_]+)__/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  s = s.replace(/(^|[^_\w])_([^_\n]+)_/g, "$1<em>$2</em>");
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return s;
}
function mdToHtml(src) {
  const blocks = [];
  src = src.replace(/```(\w*)\n?([\s\S]*?)```/g, (m, lang, code) => {
    blocks.push('<pre class="md-code"><code>' + escapeHtml(code.replace(/\n$/, "")) + "</code></pre>");
    return " B" + (blocks.length - 1) + " ";
  });
  const lines = src.split("\n");
  let html = "", listType = null, para = [];
  const flushPara = () => { if (para.length) { html += "<p>" + mdInline(para.join(" ")) + "</p>"; para = []; } };
  const flushList = () => { if (listType) { html += "</" + listType + ">"; listType = null; } };
  for (const line of lines) {
    const ph = line.match(/^ B(\d+) $/);
    if (ph) { flushPara(); flushList(); html += blocks[+ph[1]]; continue; }
    if (/^\s*$/.test(line)) { flushPara(); flushList(); continue; }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) { flushPara(); flushList(); const lvl = Math.min(h[1].length + 2, 6); html += "<h" + lvl + ">" + mdInline(h[2]) + "</h" + lvl + ">"; continue; }
    const q = line.match(/^>\s?(.*)$/);
    if (q) { flushPara(); flushList(); html += "<blockquote>" + mdInline(q[1]) + "</blockquote>"; continue; }
    const ul = line.match(/^\s*[-*+]\s+(.*)$/), ol = line.match(/^\s*\d+\.\s+(.*)$/);
    if (ul || ol) { flushPara(); const t = ul ? "ul" : "ol"; if (listType !== t) { flushList(); html += "<" + t + ">"; listType = t; } html += "<li>" + mdInline((ul || ol)[1]) + "</li>"; continue; }
    para.push(line);
  }
  flushPara(); flushList();
  return html;
}

// ============================================================================
//  Отправка + стриминг
// ============================================================================
const input = $("#input");
input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, window.innerHeight * 0.4) + "px"; });
$("#btn-send").addEventListener("click", send);
input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !matchMedia("(pointer: coarse)").matches) { e.preventDefault(); send(); } });

// ---------- Прикрепление файлов ----------
let attachments = [];  // [{token, name, size}]
$("#btn-attach").addEventListener("click", () => $("#file-input").click());
$("#file-input").addEventListener("change", async (e) => {
  for (const file of e.target.files) await uploadFile(file);
  e.target.value = "";
});
async function uploadFile(file) {
  const chip = renderChip(file.name, true);
  const fd = new FormData(); fd.append("file", file);
  try {
    const r = await fetch("/api/upload", { method: "POST", headers: { "x-csrf-token": state.csrf }, body: fd });
    const data = await r.json();
    if (!r.ok) { alert("Не удалось загрузить " + file.name + ": " + (data.detail || r.status)); chip.remove(); return; }
    attachments.push({ token: data.token, name: data.name, size: data.size });
    chip.remove(); renderChip(data.name, false, data.token);
  } catch (err) { chip.remove(); alert("Ошибка загрузки: " + err.message); }
}
function renderChip(name, pending, token) {
  const box = $("#attach-chips"); box.hidden = false;
  const chip = el("div", "chip" + (pending ? " pending" : ""));
  chip.appendChild(el("span", null, "📄 " + name));
  if (!pending) {
    const x = el("span", "x", "✕");
    x.addEventListener("click", () => { attachments = attachments.filter((a) => a.token !== token); chip.remove(); if (!attachments.length) box.hidden = true; });
    chip.appendChild(x);
  }
  box.appendChild(chip); return chip;
}
function clearAttachments() { attachments = []; $("#attach-chips").innerHTML = ""; $("#attach-chips").hidden = true; }

async function send() {
  if (state.running) return;
  const text = input.value.trim(); if ((!text && !attachments.length) || !state.project) return;
  const atts = attachments.slice();
  input.value = ""; input.style.height = "auto";
  addUser(text + (atts.length ? "\n📎 " + atts.map((a) => a.name).join(", ") : ""));
  clearAttachments();
  setRunning(true); state.currentAssistant = null;
  try {
    const r = await api("/api/chat", { method: "POST", body: JSON.stringify({
      project: state.project, message: text, conversation_id: state.conversationId, attachments: atts }) });
    if (!r.ok) { addNote("Ошибка запроса: " + r.status); setRunning(false); return; }
    await consume(r);
  } catch (err) { addNote("Сбой соединения: " + err.message); }
  finally { setRunning(false); }
}
async function consume(resp) {
  const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = "";
  for (;;) {
    const { done, value } = await reader.read(); if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i); buf = buf.slice(i + 2);
      for (const line of block.split("\n"))
        if (line.startsWith("data:")) { const j = line.slice(5).trim(); if (j) handleEvent(JSON.parse(j)); }
    }
  }
}
function handleEvent(ev) {
  switch (ev.type) {
    case "session": state.conversationId = ev.conversation_id; break;
    case "text": appendAssistant(ev.delta); break;
    case "assistant_message": case "final": state.currentAssistant = null; break;
    case "tool_start": addTool(ev.id, ev.name, ev.preview, ev.args); break;
    case "tool_result": setToolResult(ev.id, ev.ok, ev.summary, ev.content, ev.extra); break;
    case "confirm_required": showConfirm(ev); break;
    case "blocked": addNote("⛔ Заблокировано: " + ev.reason + "\n" + (ev.preview || "")); break;
    case "usage": showUsage(ev); break;
    case "stopped": addNote("⏹ Агент остановлен."); break;
    case "limit": addNote(ev.message); break;
    case "error": addNote("Ошибка: " + ev.message); break;
    case "end": break;
  }
}
function setRunning(v) { state.running = v; $("#btn-stop").hidden = !v; $("#btn-send").disabled = v; }
$("#btn-stop").addEventListener("click", async () => {
  if (!state.conversationId) return;
  await api("/api/agent/stop", { method: "POST", body: JSON.stringify({ conversation_id: state.conversationId }) });
});
function showUsage(u) { const b = $("#usage"); b.hidden = false; b.textContent = `↑${u.input_tokens} ↓${u.output_tokens} · ≈ $${u.estimated_cost} ${u.currency} · ${state.model || ""}`; }

// ---------- Подтверждение ----------
function showConfirm(ev) {
  pendingCallId = ev.id;
  $("#confirm-reason").textContent = ev.reason || "";
  $("#confirm-command").textContent = ev.preview || ev.name;
  showDialog($("#confirm-dialog"));
}
async function resolveConfirm(approved) {
  closeDialog(); if (!pendingCallId) return;
  await api("/api/chat/confirm", { method: "POST", body: JSON.stringify({
    conversation_id: state.conversationId, call_id: pendingCallId, approved }) });
  pendingCallId = null;
}
$("#confirm-allow").addEventListener("click", () => resolveConfirm(true));
$("#confirm-cancel").addEventListener("click", () => resolveConfirm(false));

// ============================================================================
//  Git
// ============================================================================
$("#btn-git").addEventListener("click", () => {
  if (!state.project) return;
  $("#git-project").textContent = state.project;
  $("#sheet-git").querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === "status"));
  renderGitTab("status"); openSheet("git");
});
$("#sheet-git").querySelectorAll(".tabs button").forEach((t) => t.addEventListener("click", () => {
  $("#sheet-git").querySelectorAll(".tabs button").forEach((x) => x.classList.remove("active"));
  t.classList.add("active"); renderGitTab(t.dataset.tab);
}));
async function renderGitTab(tab) {
  const body = $("#git-body"); body.innerHTML = "Загрузка…";
  const pq = "project=" + encodeURIComponent(state.project);
  if (tab === "status") {
    const s = await (await api("/api/git/status?" + pq)).json();
    body.innerHTML = ""; body.appendChild(el("div", "muted", "Ветка: " + (s.branch || "?")));
    const R = (arr, code, cls) => arr.forEach((f) => body.appendChild(el("div", "gline " + cls, code + " " + f)));
    R(s.modified, "M", "m"); R(s.added, "A", "a"); R(s.deleted, "D", "d"); R(s.untracked, "?", "");
    if (!s.modified.length && !s.added.length && !s.deleted.length && !s.untracked.length)
      body.appendChild(el("div", "muted", "Нет изменений."));
  } else if (tab === "diff") {
    const d = await (await api("/api/git/diff?" + pq)).json();
    body.innerHTML = ""; const pre = el("pre");
    if (d.diff) renderDiff(pre, d.diff); else pre.textContent = "Нет изменений."; body.appendChild(pre);
  } else {
    body.innerHTML = ""; const inp = el("input", "commit-input"); inp.placeholder = "fix: краткое описание";
    const btn = el("button", "btn-accent pressable", "Commit"); btn.style.marginTop = "10px";
    btn.addEventListener("click", async () => {
      if (!inp.value.trim()) return; btn.disabled = true;
      const res = await (await api("/api/git/commit", { method: "POST", body: JSON.stringify({ project: state.project, message: inp.value.trim() }) })).json();
      body.appendChild(el("div", res.ok ? "muted" : "error", res.ok ? "✓ " + (res.last_commit || "commit создан") : res.output));
      btn.disabled = false;
    });
    body.appendChild(inp); body.appendChild(btn);
  }
}
$("#btn-zip").addEventListener("click", async () => {
  const r = await api("/api/files/zip", { method: "POST", body: JSON.stringify({ project: state.project }) });
  if (!r.ok) return;
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a"); a.href = url; a.download = state.project + ".zip";
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
});

boot();
