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
                currentAssistant: null, toolEls: {}, models: [], model: null,
                server: null,               // {origin, token} — работа с другим сервером
                lastSeq: 0, finished: false };

// ---------- Где работает агент: этот сервер или другой (VPS ↔ компьютер) ------
const SERVER_KEY = "ai.server";        // JSON {origin, token} — «беру API с другого адреса»
const STARTUP_KEY = "ai.startup";      // "new" | "resume" — что открывать при запуске
const SESSION_KEY = "ai.session";      // признак «это перезагрузка, а не запуск»

function loadServer() {
  try {
    const s = JSON.parse(localStorage.getItem(SERVER_KEY) || "null");
    if (s && s.origin) return { origin: String(s.origin).replace(/\/$/, ""), token: s.token || null };
  } catch (e) { /* испорченное значение — считаем, что работаем со своего сервера */ }
  return null;
}
function saveServer(server) {
  if (server) localStorage.setItem(SERVER_KEY, JSON.stringify(server));
  else localStorage.removeItem(SERVER_KEY);
}
state.server = loadServer();   // читаем до первого запроса

// ---------- API ----------
function apiUrl(path) { return (state.server ? state.server.origin : "") + path; }

async function api(path, opts = {}) {
  opts.headers = opts.headers || {};
  if (opts.method && opts.method !== "GET") {
    opts.headers["Content-Type"] = "application/json";
    if (state.csrf) opts.headers["x-csrf-token"] = state.csrf;
  }
  if (state.server) {
    // Между сайтами cookie не передаётся — авторизуемся токеном. Тогда и CSRF
    // не нужен: чужой сайт такой заголовок сам не добавит.
    opts.credentials = "omit";
    if (state.server.token) opts.headers["Authorization"] = "Bearer " + state.server.token;
  }
  return fetch(apiUrl(path), opts);
}

// Проверка, что по адресу действительно отвечает агент.
async function pingServer(origin) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 5000);
  try {
    const r = await fetch(origin + "/api/health", { signal: ctrl.signal, credentials: "omit" });
    if (!r.ok) return { ok: false, error: "HTTP " + r.status };
    const data = await r.json();
    return { ok: data.ok === true, service: data.service };
  } catch (e) {
    return { ok: false, error: "нет ответа" };
  } finally { clearTimeout(timer); }
}

// Картинки с защищённого адреса: между сайтами тег <img> не умеет слать токен,
// поэтому забираем через fetch и показываем из памяти.
async function loadImage(img, path) {
  if (!state.server) { img.src = apiUrl(path); return; }
  try {
    const r = await api(path);
    if (!r.ok) return;
    img.src = URL.createObjectURL(await r.blob());
  } catch (e) { /* не смогли — просто не покажем */ }
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
// Клик по фону закрывает только листы. Диалог подтверждения — строго модальный:
// закрыть можно лишь кнопкой «Отменить»/«Разрешить», чтобы случайный тап не терял ответ.
scrim.addEventListener("click", () => { if (activeSheet) activeSheet.dismiss(false); });

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
  let data = null;
  try {
    data = await (await fetch(apiUrl("/api/me"), {
      credentials: state.server ? "omit" : "same-origin",
      headers: state.server && state.server.token
        ? { Authorization: "Bearer " + state.server.token } : {},
    })).json();
  } catch (e) {
    data = null;   // нет связи или чужой сервер не отвечает
  }
  if (data && data.authenticated) {
    state.csrf = data.csrf;
    try {
      await showApp();
    } catch (e) {
      // Ошибку приложения не выдаём за «нет доступа»: показываем вход, а причину — в консоль.
      console.error("Не удалось открыть приложение:", e);
      $("#login-view").hidden = false;
    }
    return;
  }
  $("#login-view").hidden = false;
  renderLoginTarget();
}
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errBox = $("#login-error"); errBox.hidden = true;
  const r = await api("/api/login", { method: "POST", body: JSON.stringify({
    username: $("#login-user").value.trim(), password: $("#login-pass").value }) });
  const data = await r.json();
  if (data.ok) {
    state.csrf = data.csrf;
    // В режиме «другой сервер» cookie не доедет — запомним токен для заголовка.
    if (state.server && data.token) { state.server = { ...state.server, token: data.token }; saveServer(state.server); }
    $("#login-view").hidden = true; showApp();
  }
  else { errBox.textContent = data.error || "Ошибка входа."; errBox.hidden = false; }
});

// На экране входа подсказываем, к какому серверу подключаемся (важно в локальном режиме).
function renderLoginTarget() {
  const box = $("#login-server");
  const btn = $("#btn-login-server");
  if (!box) return;
  box.textContent = state.server ? "Сервер: " + state.server.origin : "Сервер: этот адрес";
  box.hidden = false;
  if (btn) {
    // Если выбран другой сервер, а он не отвечает — даём вернуться на этот.
    btn.hidden = !state.server;
    btn.textContent = "← Вернуться на этот сервер";
    btn.onclick = () => { saveServer(null); location.reload(); };
  }
}

async function showApp() {
  $("#app-view").hidden = false;
  sheets = {
    chats: new Sheet($("#sheet-chats"), "left"),
    projects: new Sheet($("#sheet-projects"), "bottom"),
    settings: new Sheet($("#sheet-settings"), "bottom"),
    git: new Sheet($("#sheet-git"), "bottom"),
    mentor: new Sheet($("#sheet-mentor"), "bottom"),
  };
  await loadProjects();
  setProject(state.project);      // «Выбрать проект» в шапке, пока ничего не выбрано
  await loadSettings();
  renderServerSettings();
  renderStartupSettings();
  setupInstall();
  await startScreen();
}

// ============================================================================
//  Настройки: где работает агент + что открывать при запуске + установка
// ============================================================================
function serverChoices() {
  return [
    { id: "here", label: "Этот сервер (VPS)", note: location.origin, origin: "" },
    { id: "local", label: "На моём компьютере", note: "http://localhost:8770 — агент запущен локально", origin: "http://localhost:8770" },
    { id: "custom", label: "Другой адрес…", note: "Например, другой сервер с агентом", origin: null },
  ];
}

function renderServerSettings() {
  const box = $("#server-list"); if (!box) return;
  box.textContent = "";
  const current = state.server ? state.server.origin : "";
  const known = serverChoices().filter((c) => c.origin !== null).map((c) => c.origin);
  serverChoices().forEach((c) => {
    // «Другой адрес…» отмечаем галочкой, если выбран нестандартный адрес.
    const chosen = c.origin === null
      ? Boolean(current) && !known.includes(current)
      : (c.origin === current) || (c.id === "here" && !current);
    const b = el("button", "model-row pressable");
    b.setAttribute("aria-selected", String(chosen));
    const name = el("span", "name", c.label);
    const tick = el("span", "tick", "✓");
    b.appendChild(name); b.appendChild(tick);
    b.title = c.note;
    b.addEventListener("click", () => chooseServer(c));
    box.appendChild(b);
  });
  const note = $("#server-note");
  if (note) note.textContent = state.server
    ? "Сейчас агент работает на " + state.server.origin + " (файлы и терминал — того компьютера)."
    : "Сейчас агент работает на этом сервере. «На моём компьютере» — если запустили его локально.";

  // В шапке видно, что работаем не на VPS — иначе легко перепутать.
  const badge = $("#btn-server");
  if (badge) {
    badge.hidden = !state.server;
    badge.textContent = "💻 " + (state.server ? state.server.origin.replace(/^https?:\/\//, "") : "");
    badge.title = "Агент работает на " + (state.server ? state.server.origin : "этом сервере") + ". Нажмите, чтобы сменить.";
    badge.onclick = () => openSheet("settings");
  }
}

async function chooseServer(choice) {
  let target = choice.origin;
  if (target === null) {          // «Другой адрес…»
    const entered = prompt("Адрес агента (например http://192.168.1.10:8770):",
                           state.server ? state.server.origin : "http://");
    if (entered === null) return;
    target = entered.trim().replace(/\/+$/, "");
    if (!/^https?:\/\/[^\s]+$/i.test(target)) { alert("Нужен адрес вида http://хост:порт"); return; }
  }
  if (target === (state.server ? state.server.origin : "")) return;
  if (!target) {   // вернуться на этот сервер
    saveServer(null); location.reload(); return;
  }
  const ping = await pingServer(target);
  if (!ping.ok) {
    alert(`По адресу ${target} агент не отвечает (${ping.error || "нет связи"}).\n\n` +
          "Запустите его на компьютере и попробуйте снова.\n" +
          "Если это другой сервер — проверьте, что там разрешён этот адрес (CORS_ORIGINS в .env).");
    return;
  }
  saveServer({ origin: target, token: null });
  location.reload();
}

function renderStartupSettings() {
  const box = $("#startup-list"); if (!box) return;
  const mode = localStorage.getItem(STARTUP_KEY) || "new";
  box.textContent = "";
  [{ id: "new", label: "Новый чат (как в Claude)" },
   { id: "resume", label: "Продолжить последний чат" }].forEach((o) => {
    const b = el("button", "model-row pressable");
    b.setAttribute("aria-selected", String(mode === o.id));
    b.appendChild(el("span", "name", o.label));
    b.appendChild(el("span", "tick", "✓"));
    b.addEventListener("click", () => {
      localStorage.setItem(STARTUP_KEY, o.id);
      renderStartupSettings();
    });
    box.appendChild(b);
  });
}

// ---------- Установка на рабочий стол (PWA) ----------
let installPrompt = null;
const isStandalone = () =>
  matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;

function setupInstall() {
  const btn = $("#btn-install"), note = $("#install-note");
  if (!btn || !note) return;

  if (isStandalone()) {
    btn.hidden = true;
    note.textContent = "Приложение уже установлено — вы открыли его с рабочего стола.";
    return;
  }
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  if (installPrompt) {
    btn.hidden = false;
    btn.onclick = async () => {
      btn.hidden = true;
      installPrompt.prompt();
      try { await installPrompt.userChoice; } catch (e) { /* отменили */ }
      installPrompt = null;
      setupInstall();
    };
    note.textContent = "Добавит иконку на рабочий стол и откроет без адресной строки.";
  } else if (isIOS) {
    btn.hidden = true;
    note.textContent = "iPhone/iPad: «Поделиться» → «На экран „Домой“».";
  } else {
    btn.hidden = true;
    note.textContent = "В меню браузера выберите «Установить приложение» или «Добавить на главный экран».";
  }
}

window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  setupInstall();
});
window.addEventListener("appinstalled", () => {
  installPrompt = null;
  setupInstall();
});

// ============================================================================
//  Где я остановился: активный чат запоминается на сервере (/api/chats/active)
//  и восстанавливается при входе — с телефона, с компьютера, из любого браузера.
// ============================================================================
const LS_LAST = "ai.lastChat";
async function saveActive(convId, project) {
  try { localStorage.setItem(LS_LAST, JSON.stringify({ id: convId || null, project: project || null })); } catch (e) {}
  try {
    await api("/api/chats/active", { method: "POST",
      body: JSON.stringify({ conversation_id: convId || null, project: project || null }) });
  } catch (e) { /* не критично: в следующий раз просто откроется список чатов */ }
}
async function fetchActive() {
  try {
    const r = await api("/api/chats/active");
    if (r.ok) return await r.json();
  } catch (e) { /* сервер недоступен */ }
  return null;
}

// Тип перехода: "navigate" — приложение только что открыли (иконка, ярлык, новая
// вкладка), "reload" — обновили страницу, "back_forward" — вернулись кнопкой.
function navigationType() {
  try {
    const entry = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
    if (entry && entry.type) return entry.type;
  } catch (e) { /* старый браузер */ }
  return null;
}

// Что открыто на экране прямо сейчас: "" — пустой чат, id — конкретный чат.
// Нужно для обновления страницы: возвращаем ровно то, что человек видел.
const CURRENT_KEY = "ai.current";
function rememberCurrent(convId) {
  try { sessionStorage.setItem(CURRENT_KEY, convId || ""); } catch (e) { /* приватный режим */ }
}
function currentOnScreen() {
  try { return sessionStorage.getItem(CURRENT_KEY); } catch (e) { return null; }
}

// Что показать при запуске: новый чат (как Claude) или продолжение последнего.
async function startScreen() {
  const params = new URLSearchParams(location.search);
  const act = await fetchActive();

  // «Запуск» — это открытие приложения. Обновление страницы (F5, потянуть вниз)
  // запуском НЕ считается: оно возвращает то, что было на экране.
  // Раньше запуск определялся по sessionStorage, но в установленном приложении он
  // переживает возврат из фона — и вместо пустого чата открывался прошлый.
  const nav = navigationType();
  const firstOpen = !sessionStorage.getItem(SESSION_KEY);
  sessionStorage.setItem(SESSION_KEY, "1");
  const isLaunch = nav ? (nav === "navigate") : firstOpen;

  const mode = localStorage.getItem(STARTUP_KEY) || "new";
  let shown = false;

  if (params.get("new") === "1" || (mode === "new" && isLaunch)) {
    newChat({ remember: false });          // иконка/ярлык → пустой чат, как в Claude
    shown = true;
  } else if (!isLaunch) {
    const onScreen = currentOnScreen();     // обновление страницы
    if (onScreen === "") {
      // Пустой чат: возвращаем выбранный проект (если он был), но не диалог.
      if (act && act.last_project) setProject(act.last_project);
      newChat({ remember: false }); shown = true;
    }
    else if (onScreen && await openChat(onScreen)) shown = true;
  }

  if (!shown) await restoreActiveChat(act);
  if (params.get("settings") === "1") openSheet("settings");
}

async function restoreActiveChat(act) {
  if (!act) {                      // сервер не ответил — пробуем локальную подсказку
    try {
      const cached = JSON.parse(localStorage.getItem(LS_LAST) || "null");
      if (cached && cached.id && await openChat(cached.id)) return;
    } catch (e) { /* нет кэша */ }
    newChat({ remember: false }); return;
  }

  const project = act.project || act.last_project;
  if (project) setProject(project);

  if (act.conversation_id && await openChat(act.conversation_id)) return;
  const fallback = project && act.by_project ? act.by_project[project] : null;
  if (fallback && await openChat(fallback)) return;
  newChat({ remember: false });
}

// ============================================================================
//  Проекты
// ============================================================================
let projectsCache = [], canCreate = false, canBrowse = false;
async function loadProjects(selectName) {
  const data = await (await api("/api/projects")).json();
  projectsCache = data.projects; canCreate = data.can_create; canBrowse = data.can_browse;
  // Проект по умолчанию НЕ выбираем: новый чат начинается без привязки к проекту.
  // Проект подставляем только когда он явно задан (после создания/выбора).
  const wanted = selectName && projectsCache.find((p) => p.name === selectName);
  if (wanted) setProject(wanted.name);
}

// Подпись проекта в шапке: без проекта — приглашение выбрать.
function setProject(name) {
  state.project = name || null;
  $("#project-name").textContent = state.project || "Выбрать проект";
  $("#btn-project").classList.toggle("no-project", !state.project);
}
function renderProjectsSheet() {
  const list = $("#projects-list"); list.innerHTML = "";
  projectsCache.forEach((p) => {
    const row = el("div", "proj-row");
    const b = el("button", "list-item pressable");
    b.appendChild(el("div", "title", p.name + (p.available ? "" : " · нет доступа")));
    b.appendChild(el("div", "when", p.kind === "custom" ? p.path : "из config.yaml"));
    if (!p.available) b.disabled = true;
    b.addEventListener("click", () => selectProject(p.name));
    row.appendChild(b);
    if (p.kind === "custom") {
      const x = el("button", "proj-del pressable", "✕");
      x.title = "Убрать из списка (папка на диске не удаляется)";
      x.addEventListener("click", (e) => { e.stopPropagation(); deleteProject(p.name); });
      row.appendChild(x);
    }
    list.appendChild(row);
  });
  if (canBrowse) {
    const b = el("button", "list-item pressable accent-item");
    b.appendChild(el("div", "title", "📁 Добавить папку с сервера"));
    b.addEventListener("click", () => openBrowser(null));
    list.appendChild(b);
  }
  if (canCreate) {
    const b = el("button", "list-item pressable");
    b.appendChild(el("div", "title", "＋ Создать новый проект"));
    b.addEventListener("click", createProject);
    list.appendChild(b);
  }
}
function selectProject(name) {
  closeSheet("projects");
  const emptyChat = !state.conversationId && !$("#chat").querySelector(".msg");
  setProject(name);
  if (emptyChat) {
    // Просто выбрали проект в пустом чате — остаёмся здесь, ничего не теряем.
    $("#chat").innerHTML = "";
    addHint(`Новый чат · проект «${name}». Опишите, что сделать.`);
    rememberCurrent(null);
    saveActive(null, name);
  } else {
    newChat();          // в идущем разговоре смена проекта = новый чат
  }
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
async function deleteProject(name) {
  if (!confirm(`Убрать проект «${name}» из списка? Папка и файлы на сервере останутся.`)) return;
  const r = await api("/api/projects/" + encodeURIComponent(name), { method: "DELETE" });
  if (!r.ok) { const d = await r.json().catch(() => ({})); alert("Не удалось: " + (d.detail || r.status)); return; }
  if (state.project === name) setProject(null);
  await loadProjects(state.project); renderProjectsSheet();
}

// --- Обзор папок сервера (добавление существующей папки как проекта) --------
async function openBrowser(path) {
  const list = $("#projects-list"); list.innerHTML = "";
  let data;
  try {
    const r = await api("/api/projects/browse" + (path ? "?path=" + encodeURIComponent(path) : ""));
    data = await r.json();
    if (!r.ok) throw new Error(data.detail || r.status);
  } catch (e) { list.appendChild(el("div", "error", "Не удалось открыть: " + e.message)); return; }

  // Шапка: назад к проектам + текущий путь.
  const head = el("div", "browse-head");
  const back = el("button", "browse-back pressable", "‹ Проекты");
  back.addEventListener("click", renderProjectsSheet);
  head.appendChild(back);
  if (data.current) head.appendChild(el("div", "browse-path", data.current.path));
  list.appendChild(head);

  // «Выбрать эту папку» — для текущей (если доступна и ещё не проект).
  if (data.current && !data.current.is_project) {
    const pick = el("button", "list-item pressable accent-item");
    pick.appendChild(el("div", "title", "✓ Добавить эту папку как проект"));
    pick.appendChild(el("div", "when", data.current.path));
    if (!data.current.writable) { pick.disabled = true;
      pick.querySelector(".when").textContent = "нет доступа на запись"; }
    pick.addEventListener("click", () => addExisting(data.current.path, data.current.name));
    list.appendChild(pick);
  }
  // Вверх по дереву.
  if (data.parent) {
    const up = el("button", "list-item pressable");
    up.appendChild(el("div", "title", "↑ Вверх"));
    up.addEventListener("click", () => openBrowser(data.parent));
    list.appendChild(up);
  }
  // Подпапки.
  if (!data.entries.length) list.appendChild(el("div", "muted browse-empty", "Вложенных папок нет."));
  data.entries.forEach((d) => {
    const row = el("div", "proj-row");
    const b = el("button", "list-item pressable");
    const title = d.name + (d.is_project ? " · уже проект" : "") + (d.accessible ? "" : " · нет доступа");
    b.appendChild(el("div", "title", title));
    if (d.accessible) b.addEventListener("click", () => openBrowser(d.path));
    else b.disabled = true;
    row.appendChild(b);
    if (d.accessible && !d.is_project && d.writable) {
      const add = el("button", "proj-del pressable", "＋");
      add.title = "Добавить как проект";
      add.addEventListener("click", (e) => { e.stopPropagation(); addExisting(d.path, d.name); });
      row.appendChild(add);
    }
    list.appendChild(row);
  });
}
async function addExisting(path, suggested) {
  const name = prompt("Имя проекта (пусто — из названия папки):", suggested || "");
  if (name === null) return;  // отмена
  const r = await api("/api/projects/add", {
    method: "POST", body: JSON.stringify({ path, name: name.trim() || null }) });
  const data = await r.json();
  if (!r.ok) { alert("Не удалось: " + (data.detail || r.status)); return; }
  await loadProjects(data.project.name); renderProjectsSheet();
  selectProject(data.project.name);
}
$("#btn-project").addEventListener("click", () => { renderProjectsSheet(); openSheet("projects"); });

// ============================================================================
//  Настройки — переключатель модели (segmented control)
// ============================================================================
const PROVIDER_LABELS = { deepseek: "DeepSeek", openai: "OpenAI", openrouter: "OpenRouter" };
async function loadSettings() {
  const data = await (await api("/api/settings")).json();
  // models — [{id,label,provider}]; available_models — legacy список id (fallback).
  state.models = (data.models && data.models.length)
    ? data.models
    : (data.available_models || []).map((id) => ({ id, label: id, provider: "deepseek" }));
  state.model = data.model;
  buildModelList();
}
function buildModelList() {
  const box = $("#model-list");
  box.textContent = "";
  let lastProvider = null;
  state.models.forEach((m) => {
    if (m.provider !== lastProvider) {
      lastProvider = m.provider;
      box.appendChild(el("div", "mg-head", PROVIDER_LABELS[m.provider] || m.provider));
    }
    const b = el("button", "model-row pressable");
    b.setAttribute("aria-selected", String(m.id === state.model));
    b.appendChild(el("span", "name", m.label || m.id));
    b.appendChild(el("span", "tick", "✓"));
    b.addEventListener("click", () => switchModel(m.id));
    box.appendChild(b);
  });
}
async function switchModel(id) {
  const prev = state.model; state.model = id;
  buildModelList();
  const r = await api("/api/settings/model", { method: "POST", body: JSON.stringify({ model: id }) });
  if (!r.ok) { state.model = prev; buildModelList(); alert("Не удалось переключить модель."); }
}
$("#btn-settings").addEventListener("click", () => openSheet("settings"));
$("#btn-logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  // В режиме другого сервера забываем ещё и токен — иначе вход останется активным.
  if (state.server) saveServer({ ...state.server, token: null });
  location.reload();
});

// ---------- Установка как приложение: service worker ----------
if ("serviceWorker" in navigator &&
    (location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => { /* без SW просто нет офлайна */ });
  });
}

// ============================================================================
//  Наставник — напоминания в Telegram (планировщик)
// ============================================================================
const DOW = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];
async function openMentor() {
  // Проекты в выпадающий список.
  const sel = $("#mentor-project"); sel.innerHTML = "";
  sel.appendChild(el("option", null, "— без проекта —"));
  (projectsCache || []).forEach((p) => {
    const o = el("option", null, p.name); o.value = p.name; sel.appendChild(o);
  });
  await loadMentor();
  openSheet("mentor");
}
async function loadMentor() {
  const data = await (await api("/api/mentor")).json();
  const tg = $("#mentor-tg");
  tg.className = "mentor-status " + (data.telegram_configured ? "ok" : "warn");
  tg.textContent = data.telegram_configured
    ? "✓ Telegram подключён — напоминания будут приходить в чат."
    : "⚠ Telegram не настроен. Задай TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env на сервере.";

  const list = $("#mentor-list"); list.innerHTML = "";
  if (!data.reminders.length) list.appendChild(el("div", "muted", "Пока нет напоминаний."));
  data.reminders.forEach((r) => list.appendChild(renderReminder(r)));

  const recent = $("#mentor-recent"); recent.innerHTML = "";
  if (!data.recent.length) recent.appendChild(el("div", "muted", "Советов пока не было."));
  data.recent.forEach((l) => {
    const d = el("div", "mentor-log" + (l.ok ? "" : " bad"));
    d.appendChild(el("div", "mentor-log-head",
      `${l.project || "без проекта"} · ${new Date(l.created_at).toLocaleString()}${l.ok ? "" : " · не доставлено"}`));
    d.appendChild(el("div", "mentor-log-text", l.text));
    recent.appendChild(d);
  });
}
function renderReminder(r) {
  const row = el("div", "reminder");
  const top = el("div", "reminder-top");
  const when = r.time_local + (r.weekdays_only ? " · будни" : " · ежедневно");
  top.appendChild(el("div", "reminder-title", (r.project || "без проекта") + " · " + when));
  const toggle = el("button", "reminder-toggle pressable", r.enabled ? "вкл" : "выкл");
  toggle.setAttribute("aria-selected", String(r.enabled));
  toggle.addEventListener("click", () => patchReminder(r.id, { enabled: !r.enabled }));
  top.appendChild(toggle);
  row.appendChild(top);
  if (r.goal) row.appendChild(el("div", "reminder-goal", r.goal));
  const acts = el("div", "reminder-acts");
  const test = el("button", "reminder-btn pressable", "Прислать сейчас");
  test.addEventListener("click", () => testReminder(r.id, test));
  const del = el("button", "reminder-btn danger pressable", "Удалить");
  del.addEventListener("click", () => deleteReminder(r.id));
  acts.appendChild(test); acts.appendChild(del);
  row.appendChild(acts);
  return row;
}
async function addReminder() {
  const project = $("#mentor-project").value || null;
  const time_local = $("#mentor-time").value || "09:00";
  const weekdays_only = $("#mentor-weekdays").checked;
  const goal = $("#mentor-goal").value.trim();
  const r = await api("/api/mentor/reminders", { method: "POST",
    body: JSON.stringify({ project, time_local, weekdays_only, goal }) });
  const data = await r.json();
  if (!r.ok) { alert("Не удалось: " + (data.detail || r.status)); return; }
  $("#mentor-goal").value = "";
  await loadMentor();
}
async function patchReminder(id, fields) {
  const r = await api("/api/mentor/reminders/" + id, { method: "PATCH", body: JSON.stringify(fields) });
  if (!r.ok) { const d = await r.json().catch(() => ({})); alert("Не удалось: " + (d.detail || r.status)); return; }
  await loadMentor();
}
async function deleteReminder(id) {
  if (!confirm("Удалить напоминание?")) return;
  const r = await api("/api/mentor/reminders/" + id, { method: "DELETE" });
  if (!r.ok) { alert("Не удалось удалить."); return; }
  await loadMentor();
}
async function testReminder(id, btn) {
  const prev = btn.textContent; btn.textContent = "…"; btn.disabled = true;
  const r = await api("/api/mentor/test", { method: "POST", body: JSON.stringify({ id }) });
  const data = await r.json().catch(() => ({}));
  btn.textContent = prev; btn.disabled = false;
  if (!r.ok) { alert("Ошибка: " + (data.detail || r.status)); return; }
  await loadMentor();
  if (!data.ok) alert("Совет создан, но не отправлен: " + (data.error || "проверь Telegram"));
}
$("#btn-mentor").addEventListener("click", openMentor);
$("#mentor-add").addEventListener("click", addReminder);

// ============================================================================
//  Чаты (история)
// ============================================================================
$("#btn-menu").addEventListener("click", async () => { await loadChats(); openSheet("chats"); });
$("#btn-new-chat").addEventListener("click", () => { newChat(); closeSheet("chats"); });
let foldersCache = [];
async function loadChats() {
  const data = await (await api("/api/chats")).json();
  foldersCache = data.folders || [];
  const list = $("#chats-list"); list.innerHTML = "";
  if (!data.chats.length && !foldersCache.length) { list.appendChild(el("div", "muted", "Пока нет чатов.")); return; }

  const byFolder = {}; const none = [];
  data.chats.forEach((c) => { if (c.folder_id) (byFolder[c.folder_id] = byFolder[c.folder_id] || []).push(c); else none.push(c); });

  foldersCache.forEach((f) => {
    renderFolderHeader(list, f);
    const items = byFolder[f.id] || [];
    items.forEach((c) => renderChatRow(list, c));
    if (!items.length) list.appendChild(el("div", "muted", "— пусто —"));
  });
  if (none.length) {
    if (foldersCache.length) renderFolderHeader(list, null);
    none.forEach((c) => renderChatRow(list, c));
  }
}
function renderFolderHeader(list, f) {
  const h = el("div", "folder-head");
  h.appendChild(el("span", "folder-name", "📁 " + (f ? f.name : "Без папки")));
  if (f) {
    const ren = el("button", "chat-edit", "✎");
    ren.addEventListener("click", () => renameFolder(f));
    const del = el("button", "chat-edit chat-del", "🗑");
    del.addEventListener("click", () => deleteFolder(f));
    h.appendChild(ren); h.appendChild(del);
  }
  list.appendChild(h);
}
function renderChatRow(list, c) {
  const row = el("div", "chat-row");
  const main = el("div", "list-item pressable chat-main");
  main.appendChild(el("div", "title", c.title || "Без названия"));
  const where = c.project || "без проекта";
  main.appendChild(el("div", "when", `${where} · ${new Date(c.updated_at).toLocaleString()}`));
  main.addEventListener("click", () => openChat(c.id));
  const mv = el("button", "chat-edit", "📁"); mv.title = "В папку";
  mv.addEventListener("click", (e) => { e.stopPropagation(); moveChat(c); });
  const edit = el("button", "chat-edit", "✎"); edit.title = "Переименовать";
  edit.addEventListener("click", (e) => { e.stopPropagation(); renameChat(c); });
  const del = el("button", "chat-edit chat-del", "🗑"); del.title = "Удалить";
  del.addEventListener("click", (e) => { e.stopPropagation(); deleteChat(c); });
  row.appendChild(main); row.appendChild(mv); row.appendChild(edit); row.appendChild(del);
  list.appendChild(row);
}
$("#btn-new-folder").addEventListener("click", createFolder);
async function createFolder() {
  const name = prompt("Название папки:", "");
  if (!name || !name.trim()) return;
  await api("/api/folders", { method: "POST", body: JSON.stringify({ name: name.trim() }) });
  loadChats();
}
async function renameFolder(f) {
  const name = prompt("Новое название папки:", f.name);
  if (name === null || !name.trim()) return;
  await api("/api/folders/" + f.id + "/rename", { method: "POST", body: JSON.stringify({ name: name.trim() }) });
  loadChats();
}
async function deleteFolder(f) {
  if (!confirm(`Удалить папку «${f.name}»? Чаты из неё не удалятся, станут «без папки».`)) return;
  await api("/api/folders/" + f.id, { method: "DELETE" });
  loadChats();
}
async function moveChat(c) {
  const opts = ["0 — Без папки", ...foldersCache.map((f, i) => `${i + 1} — ${f.name}`)];
  const ans = prompt("Куда переместить? Введи номер или новое имя папки:\n" + opts.join("\n"), "");
  if (ans === null) return;
  const t = ans.trim(); if (!t) return;
  let folderId = null;
  if (/^\d+$/.test(t)) {
    const n = parseInt(t, 10);
    if (n === 0) folderId = null;
    else { const f = foldersCache[n - 1]; if (!f) { alert("Нет такого номера."); return; } folderId = f.id; }
  } else {
    const r = await (await api("/api/folders", { method: "POST", body: JSON.stringify({ name: t }) })).json();
    folderId = r.id;
  }
  await api("/api/chat/" + c.id + "/move", { method: "POST", body: JSON.stringify({ folder_id: folderId }) });
  loadChats();
}
async function renameChat(c) {
  const name = prompt("Новое название чата:", c.title || "");
  if (name === null) return;
  const t = name.trim(); if (!t) return;
  const r = await api("/api/chat/" + c.id + "/rename", { method: "POST", body: JSON.stringify({ title: t }) });
  if (r.ok) loadChats();
}
async function deleteChat(c) {
  if (!confirm(`Удалить чат «${c.title || "Без названия"}»? Это необратимо.`)) return;
  const r = await api("/api/chat/" + c.id, { method: "DELETE" });
  if (r.ok) {
    if (state.conversationId === c.id) newChat();
    loadChats();
  }
}
async function openChat(id) {
  const r = await api("/api/chat/" + id); if (!r.ok) return false;
  const conv = await r.json();
  state.conversationId = conv.id;
  setProject(conv.project);
  $("#chat").innerHTML = ""; state.currentAssistant = null;
  conv.messages.forEach((m) => {
    if (m.role === "user") addUser(m.content);
    else if (m.role === "assistant" && m.content) { const a = startAssistant(); a.innerHTML = mdToHtml(m.content); state.currentAssistant = null; }
  });
  closeSheet("chats"); scrollDown();
  state.lastSeq = 0; state.finished = false;
  rememberCurrent(conv.id);
  saveActive(conv.id, conv.project);      // запомним: сюда вернёмся при следующем входе
  // Если по этому чату работа ещё идёт — подключимся к ней.
  resumeIfRunning();
  return true;
}
function newChat(opts = {}) {
  state.conversationId = null; $("#chat").innerHTML = "";
  state.lastSeq = 0; state.finished = false;
  rememberCurrent(null);
  addHint(state.project
    ? `Новый чат · проект «${state.project}». Опишите, что сделать.`
    : "Новый чат. Опишите, что сделать — проект можно выбрать сверху.");
  // Запоминаем проект, а чат — новый. При автоматическом новом чате на старте
  // (remember: false) память не трогаем: чтобы «Продолжить последний» работал.
  if (opts.remember !== false) saveActive(null, state.project || null);
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
function addHint(t) { $("#chat").appendChild(el("div", "msg system-note hint", t)); scrollDown(); }
function addLimitNote(msg) {
  const box = el("div", "msg system-note");
  box.appendChild(el("div", null, "⏸ Достигнут лимит шагов за один запуск. Прогресс сохранён."));
  const btn = el("button", "btn-accent pressable", "▶ Продолжить");
  btn.style.marginTop = "10px";
  btn.addEventListener("click", () => {
    if (state.running) return;
    input.value = "Продолжи задачу с того места, где остановился.";
    send();
  });
  box.appendChild(btn);
  $("#chat").appendChild(box); scrollDown();
}

const ICON = { read_file: "📄", list_files: "📁", search_files: "🔎", write_file: "✏️", edit_file: "✏️", terminal: "▶", git: "🔀", github: "🐙", browser: "🌐", web_search: "🌍", web_fetch: "📰", generate_image: "🎨", tasks: "✅" };
const VERB = { read_file: "Читаю", list_files: "Смотрю папку", search_files: "Ищу", write_file: "Пишу", edit_file: "Правлю", terminal: "Терминал", git: "Git" };
// Человекочитаемая подпись действия из имени и аргументов инструмента.
function toolLabel(name, args, preview) {
  args = args || {};
  if (name === "read_file" || name === "write_file" || name === "edit_file") return `${VERB[name]} ${args.path || ""}`.trim();
  if (name === "list_files") return `${VERB[name]}: ${args.path || "."}`;
  if (name === "search_files") return `${VERB[name]} «${args.query || ""}»`;
  if (name === "terminal") return preview || args.command || "Терминал";
  if (name === "git") return preview || ("git " + (Array.isArray(args.args) ? args.args.join(" ") : ""));
  if (name === "browser") { const act = args.action || "browser"; return "Браузер: " + act + (args.url ? " " + args.url : args.text ? " «" + args.text + "»" : args.selector ? " " + args.selector : ""); }
  if (name === "github") return "GitHub: " + (args.action || "");
  if (name === "web_search") return "Поиск в интернете «" + (args.query || "") + "»";
  if (name === "web_fetch") return "Читаю страницу: " + (args.url || "");
  if (name === "generate_image") return "Рисую: " + (args.prompt || "").slice(0, 60);
  if (name === "tasks") return "Задачи: " + (args.action || "list");
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
  // Скриншот браузера — показываем картинку пользователю.
  if (extra && extra.screenshot_url && !d._shot) {
    const img = el("img", "tool-shot"); img.loading = "lazy";
    img.addEventListener("click", () => window.open(img.src, "_blank"));
    loadImage(img, extra.screenshot_url);
    d.appendChild(img); d._shot = true; d.open = true;
  }
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

// ---------- Индикатор «агент думает» ----------
let thinkingEl = null;
function showThinking(label) {
  if (!thinkingEl) {
    thinkingEl = el("div", "thinking");
    thinkingEl.innerHTML = '<span class="dots"><i></i><i></i><i></i></span>';
    thinkingEl._label = el("span", "th-label");
    thinkingEl.appendChild(thinkingEl._label);
  }
  thinkingEl._label.textContent = label || "думаю…";
  $("#chat").appendChild(thinkingEl);   // всегда внизу
  scrollDown();
}
function hideThinking() { if (thinkingEl && thinkingEl.parentNode) thinkingEl.remove(); }

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
  const M = "";
  src = src.replace(/```(\w*)\n?([\s\S]*?)```/g, (m, lang, code) => {
    blocks.push('<pre class="md-code"><code>' + escapeHtml(code.replace(/\n$/, "")) + "</code></pre>");
    return M + (blocks.length - 1) + M;
  });
  const lines = src.split("\n");
  let html = "", listType = null, para = [];
  const flushPara = () => { if (para.length) { html += "<p>" + mdInline(para.join(" ")) + "</p>"; para = []; } };
  const flushList = () => { if (listType) { html += "</" + listType + ">"; listType = null; } };
  const isSep = (l) => l.includes("-") && /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$/.test(l);
  const cells = (l) => { let s = l.trim(); if (s.startsWith("|")) s = s.slice(1); if (s.endsWith("|")) s = s.slice(0, -1); return s.split("|").map((x) => x.trim()); };
  const phRe = new RegExp("^" + M + "(\\d+)" + M + "$");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    // GFM-таблица: строка с '|' и следующая строка-разделитель (|---|---|)
    if (line.includes("|") && line.trim() && i + 1 < lines.length && isSep(lines[i + 1])) {
      flushPara(); flushList();
      const header = cells(line); i += 2; const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) { rows.push(cells(lines[i])); i++; }
      let t = '<div class="md-table"><table><thead><tr>' +
        header.map((h) => "<th>" + mdInline(h) + "</th>").join("") + "</tr></thead><tbody>";
      for (const r of rows) t += "<tr>" + r.map((c) => "<td>" + mdInline(c) + "</td>").join("") + "</tr>";
      html += t + "</tbody></table></div>"; continue;
    }
    const ph = line.match(phRe);
    if (ph) { flushPara(); flushList(); html += blocks[+ph[1]]; i++; continue; }
    if (/^\s*$/.test(line)) { flushPara(); flushList(); i++; continue; }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) { flushPara(); flushList(); const lvl = Math.min(h[1].length + 2, 6); html += "<h" + lvl + ">" + mdInline(h[2]) + "</h" + lvl + ">"; i++; continue; }
    const q = line.match(/^>\s?(.*)$/);
    if (q) { flushPara(); flushList(); html += "<blockquote>" + mdInline(q[1]) + "</blockquote>"; i++; continue; }
    const ul = line.match(/^\s*[-*+]\s+(.*)$/), ol = line.match(/^\s*\d+\.\s+(.*)$/);
    if (ul || ol) { flushPara(); const t = ul ? "ul" : "ol"; if (listType !== t) { flushList(); html += "<" + t + ">"; listType = t; } html += "<li>" + mdInline((ul || ol)[1]) + "</li>"; i++; continue; }
    para.push(line); i++;
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
// Вставка скриншотов из буфера обмена (Ctrl+V)
input.addEventListener("paste", async (e) => {
  const items = (e.clipboardData && e.clipboardData.items) || [];
  for (const it of items) {
    if (it.type && it.type.startsWith("image/")) {
      const blob = it.getAsFile();
      if (blob) {
        e.preventDefault();
        const ext = (it.type.split("/")[1] || "png").replace("jpeg", "jpg");
        const named = new File([blob], `screenshot-${Date.now()}.${ext}`, { type: it.type });
        await uploadFile(named);
      }
    }
  }
});
// Загрузка файла: FormData с CSRF (свой сервер) или с токеном (другой сервер).
function uploadOpts(fd) {
  if (state.server) {
    const headers = {};
    if (state.server.token) headers.Authorization = "Bearer " + state.server.token;
    return { method: "POST", headers, body: fd, credentials: "omit" };
  }
  return { method: "POST", headers: { "x-csrf-token": state.csrf }, body: fd };
}

async function uploadFile(file) {
  const chip = renderChip(file.name, true);
  const fd = new FormData(); fd.append("file", file);
  try {
    const r = await fetch(apiUrl("/api/upload"), uploadOpts(fd));
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
  const text = input.value.trim(); if (!text && !attachments.length) return;
  const atts = attachments.slice();
  input.value = ""; input.style.height = "auto";
  // Подсказка «Новый чат…» нужна только пока чат пуст.
  $("#chat").querySelectorAll(".system-note.hint").forEach((n) => n.remove());
  addUser(text + (atts.length ? "\n📎 " + atts.map((a) => a.name).join(", ") : ""));
  clearAttachments();
  setRunning(true); state.currentAssistant = null; state.lastSeq = 0; state.finished = false;
  try {
    const r = await api("/api/chat", { method: "POST", body: JSON.stringify({
      project: state.project, message: text, conversation_id: state.conversationId, attachments: atts }) });
    if (!r.ok) { addNote("Ошибка запроса: " + r.status); setRunning(false); return; }
    await consume(r);
    if (!state.finished) await reconnect();
  } catch (err) {
    // Связь оборвалась — работа на сервере продолжается. Переподключаемся.
    await reconnect();
  }
  finally { if (state.finished) setRunning(false); }
}
async function consume(resp) {
  if (!resp.ok || !resp.body) {
    // 404 на переподключении = задача уже завершена, догоняем историю из БД.
    throw new Error("нет потока");
  }
  const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = "";
  try {
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
  } finally {
    try { reader.cancel(); } catch (e) { /* уже закрыт */ }
  }
}
// Переподключение к уже идущей задаче: забираем пропущенные события по seq.
async function reconnect(tries) {
  tries = tries || 0;
  if (!state.conversationId) { setRunning(false); return; }
  try {
    const r = await api(`/api/chat/${state.conversationId}/stream?from=${state.lastSeq}`);
    if (r.status === 404) {
      // Задачи в памяти нет: либо всё закончилось, либо сервис перезапускался.
      addNote("Работа на сервере уже завершилась — обновляю чат.");
      const id = state.conversationId; await openChat(id); setRunning(false); return;
    }
    if (!r.ok) throw new Error("HTTP " + r.status);
    await consume(r);
    if (!state.finished && tries < 5) return reconnect(tries + 1);
    setRunning(false);
  } catch (err) {
    if (tries < 5) {
      addNote("Связь пропала, пробую снова…");
      await new Promise((res) => setTimeout(res, 1000 * Math.min(tries + 1, 5)));
      return reconnect(tries + 1);
    }
    addNote("Не удалось восстановить связь. Работа продолжается на сервере — открой чат заново.");
    setRunning(false);
  }
}
// При открытии страницы: если по текущему чату идёт работа — подключиться к ней.
async function resumeIfRunning() {
  if (!state.conversationId) return;
  try {
    const r = await api(`/api/chat/${state.conversationId}/job`);
    if (!r.ok) return;
    const data = await r.json();
    if (data.running) {
      setRunning(true); state.currentAssistant = null; state.lastSeq = 0; state.finished = false;
      addNote("Подключаюсь к работе, которая уже идёт…");
      await reconnect();
    }
  } catch (err) { /* тихо: это лишь удобство */ }
}
function handleEvent(ev) {
  if (typeof ev.seq === "number") state.lastSeq = ev.seq;
  switch (ev.type) {
    case "session":
      state.conversationId = ev.conversation_id;
      rememberCurrent(ev.conversation_id);   // обновление страницы вернёт в этот чат
      saveActive(ev.conversation_id, ev.project || state.project);
      break;
    case "text": hideThinking(); appendAssistant(ev.delta); break;
    case "assistant_message": state.currentAssistant = null; if (state.running) showThinking("думаю…"); break;
    case "final": state.currentAssistant = null; hideThinking(); break;
    case "tool_start": addTool(ev.id, ev.name, ev.preview, ev.args); showThinking("работаю…"); break;
    case "tool_result": setToolResult(ev.id, ev.ok, ev.summary, ev.content, ev.extra); if (state.running) showThinking("анализирую результат…"); break;
    case "iteration": if (state.running) showThinking("думаю…"); break;
    case "confirm_required": hideThinking(); showConfirm(ev); break;
    case "confirmed": showThinking("выполняю…"); break;
    case "blocked": addNote("⛔ Заблокировано: " + ev.reason + "\n" + (ev.preview || "")); break;
    case "usage": showUsage(ev); break;
    case "stopped": hideThinking(); addNote("⏹ Агент остановлен."); break;
    case "retry": showThinking("сеть подвела — повторяю запрос (" + ev.attempt + "/" + ev.of + ")…"); break;
    case "limit": hideThinking(); addLimitNote(ev.message); break;
    case "error": hideThinking(); addNote("Ошибка: " + ev.message); break;
    case "ping": break;
    case "end": state.finished = true; hideThinking(); setRunning(false); break;
  }
}
function setRunning(v) {
  state.running = v; $("#btn-stop").hidden = !v; $("#btn-send").disabled = v;
  if (v) showThinking("думаю…"); else hideThinking();
}
$("#btn-stop").addEventListener("click", async () => {
  if (!state.conversationId) return;
  await api("/api/agent/stop", { method: "POST", body: JSON.stringify({ conversation_id: state.conversationId }) });
});
function showUsage(u) {
  const b = $("#usage"); b.hidden = false;
  const peak = u.peak ? " · пик×2" : "";
  b.textContent = `↑${u.input_tokens} ↓${u.output_tokens} · ≈ $${u.estimated_cost} ${u.currency} · ${u.model || state.model || ""}${peak}`;
}

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
  if (!state.project) { alert("Сначала выберите проект — кнопка «Выбрать проект» вверху."); return; }
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
  } else if (tab === "commit") {
    body.innerHTML = ""; const inp = el("input", "commit-input"); inp.placeholder = "fix: краткое описание";
    const btn = el("button", "btn-accent pressable", "Commit"); btn.style.marginTop = "10px";
    btn.addEventListener("click", async () => {
      if (!inp.value.trim()) return; btn.disabled = true;
      const res = await (await api("/api/git/commit", { method: "POST", body: JSON.stringify({ project: state.project, message: inp.value.trim() }) })).json();
      body.appendChild(el("div", res.ok ? "muted" : "error", res.ok ? "✓ " + (res.last_commit || "commit создан") : res.output));
      btn.disabled = false;
    });
    body.appendChild(inp); body.appendChild(btn);
  } else if (tab === "github") {
    await renderGithub(body, pq);
  }
}

async function renderGithub(body, pq) {
  const info = await (await api("/api/github/info?" + pq)).json();
  body.innerHTML = "";
  if (!info.github) { body.appendChild(el("div", "muted", info.reason || "Проект не на GitHub.")); return; }
  if (!info.has_token) { body.appendChild(el("div", "muted", "GITHUB_TOKEN не задан на сервере — GitHub-функции выключены.")); }
  body.appendChild(el("div", "muted", `${info.owner}/${info.repo} · ветка: ${info.current_branch || "?"}` + (info.default_branch ? ` · base: ${info.default_branch}` : "")));
  if (info.token_error) body.appendChild(el("div", "error", info.token_error));

  // Создать PR
  const title = el("input", "commit-input"); title.placeholder = "Заголовок PR (напр. fix: webhook Megafon)"; title.style.marginTop = "10px";
  const prBtn = el("button", "btn-accent pressable", "Создать Pull Request"); prBtn.style.marginTop = "10px";
  prBtn.addEventListener("click", async () => {
    if (!title.value.trim()) return; prBtn.disabled = true;
    const res = await (await api("/api/github/pr", { method: "POST", body: JSON.stringify({ project: state.project, title: title.value.trim() }) })).json();
    if (res.ok) { const a = el("a", null, `✓ PR #${res.number} создан — открыть`); a.href = res.url; a.target = "_blank"; a.rel = "noopener"; a.style.color = "var(--accent)"; const w = el("div"); w.style.marginTop = "8px"; w.appendChild(a); body.appendChild(w); }
    else body.appendChild(el("div", "error", res.error || "Не удалось создать PR."));
    prBtn.disabled = false;
  });
  body.appendChild(title); body.appendChild(prBtn);

  // Статус CI
  const ciBtn = el("button", "btn-ghost pressable", "Проверить CI"); ciBtn.style.marginTop = "10px";
  const ciOut = el("div"); ciOut.style.marginTop = "8px";
  ciBtn.addEventListener("click", async () => {
    ciBtn.disabled = true; ciOut.innerHTML = "Загрузка…";
    const r = await (await api("/api/github/ci?" + pq)).json();
    ciOut.innerHTML = "";
    if (!r.ok) { ciOut.appendChild(el("div", "muted", r.error || "Нет данных CI.")); }
    else if (!r.total) { ciOut.appendChild(el("div", "muted", "Проверок CI нет для текущего коммита.")); }
    else {
      ciOut.appendChild(el("div", r.failure ? "error" : "muted", `CI: ✓${r.success} ✗${r.failure} ⏳${r.pending}`));
      r.runs.forEach((run) => ciOut.appendChild(el("div", "gline", `${run.conclusion === "success" ? "✓" : run.conclusion === "failure" ? "✗" : "•"} ${run.name}`)));
    }
    ciBtn.disabled = false;
  });
  body.appendChild(ciBtn); body.appendChild(ciOut);
}
$("#btn-zip").addEventListener("click", async () => {
  const r = await api("/api/files/zip", { method: "POST", body: JSON.stringify({ project: state.project }) });
  if (!r.ok) return;
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a"); a.href = url; a.download = state.project + ".zip";
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
});

boot();
