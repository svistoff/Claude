"use strict";

// ------- Состояние -------
const state = {
  csrf: null,
  project: null,
  conversationId: null,
  running: false,
  currentAssistant: null,
  toolEls: {},        // call_id -> DOM элемент
};

// ------- Утилиты -------
const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

async function api(path, opts = {}) {
  opts.headers = opts.headers || {};
  if (opts.method && opts.method !== "GET") {
    opts.headers["Content-Type"] = "application/json";
    if (state.csrf) opts.headers["x-csrf-token"] = state.csrf;
  }
  const resp = await fetch(path, opts);
  return resp;
}

// ------- Инициализация -------
async function boot() {
  const resp = await fetch("/api/me");
  const data = await resp.json();
  if (data.authenticated) {
    state.csrf = data.csrf;
    showApp();
  } else {
    $("#login-view").hidden = false;
  }
}

// ------- Вход -------
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errBox = $("#login-error");
  errBox.hidden = true;
  const resp = await api("/api/login", {
    method: "POST",
    body: JSON.stringify({
      username: $("#login-user").value.trim(),
      password: $("#login-pass").value,
    }),
  });
  const data = await resp.json();
  if (data.ok) {
    state.csrf = data.csrf;
    $("#login-view").hidden = true;
    showApp();
  } else {
    errBox.textContent = data.error || "Ошибка входа.";
    errBox.hidden = false;
  }
});

async function showApp() {
  $("#app-view").hidden = false;
  await loadProjects();
  await loadChats();
}

// ------- Проекты -------
let projectsBound = false;
async function loadProjects(selectName) {
  const resp = await api("/api/projects");
  const data = await resp.json();
  const sel = $("#project-select");
  sel.innerHTML = "";
  data.projects.forEach((p) => {
    const label = (p.kind === "custom" ? "• " : "") + p.name + (p.available ? "" : " (нет)");
    const opt = el("option", null, label);
    opt.value = p.name;
    if (!p.available) opt.disabled = true;
    sel.appendChild(opt);
  });
  if (data.can_create) {
    const opt = el("option", null, "➕ Новый проект…");
    opt.value = "__new__";
    sel.appendChild(opt);
  }

  const wanted = selectName && data.projects.find((p) => p.name === selectName);
  const first = wanted || data.projects.find((p) => p.available);
  if (first) {
    sel.value = first.name;
    state.project = first.name;
  }

  if (!projectsBound) {
    projectsBound = true;
    sel.addEventListener("change", onProjectChange);
  }
}

async function onProjectChange() {
  const sel = $("#project-select");
  if (sel.value === "__new__") {
    sel.value = state.project || "";     // вернём выбор, пока создаём
    await createProject();
    return;
  }
  state.project = sel.value;
  newChat();
}

async function createProject() {
  const name = prompt("Имя нового проекта (латиница, цифры, дефис):", "");
  if (!name) return;
  const resp = await api("/api/projects/new", {
    method: "POST",
    body: JSON.stringify({ name: name.trim() }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    alert("Не удалось создать проект: " + (data.detail || resp.status));
    return;
  }
  await loadProjects(data.project.name);
  newChat();
}

// ------- Чаты -------
async function loadChats() {
  const resp = await api("/api/chats");
  const data = await resp.json();
  const list = $("#chats-list");
  list.innerHTML = "";
  data.chats.forEach((c) => {
    const item = el("div", "chat-item");
    item.appendChild(el("div", null, c.title || "Без названия"));
    item.appendChild(el("div", "when", `${c.project} · ${new Date(c.updated_at).toLocaleString()}`));
    item.addEventListener("click", () => openChat(c.id));
    list.appendChild(item);
  });
}

async function openChat(id) {
  const resp = await api("/api/chat/" + id);
  if (!resp.ok) return;
  const conv = await resp.json();
  state.conversationId = conv.id;
  state.project = conv.project;
  $("#project-select").value = conv.project;
  $("#chat").innerHTML = "";
  conv.messages.forEach((m) => {
    if (m.role === "user") addUserMsg(m.content);
    else if (m.role === "assistant" && m.content) {
      const a = startAssistant();
      a.textContent = m.content;
    }
    // tool-сообщения истории показываем компактно
    else if (m.role === "tool") {
      const t = addTool("hist", "результат", "");
      setToolResult("hist", true, "из истории", m.content, {});
      delete state.toolEls["hist"];
    }
  });
  closeSidebar();
  scrollDown();
}

function newChat() {
  state.conversationId = null;
  $("#chat").innerHTML = "";
  const note = el("div", "msg system-note", "Новая задача. Опишите, что сделать в проекте " + (state.project || "") + ".");
  $("#chat").appendChild(note);
}

$("#btn-new-chat").addEventListener("click", () => { newChat(); closeSidebar(); });
$("#btn-menu").addEventListener("click", openSidebar);
$("#scrim").addEventListener("click", closeSidebar);
function openSidebar() { $("#sidebar").hidden = false; $("#scrim").hidden = false; loadChats(); }
function closeSidebar() { $("#sidebar").hidden = true; $("#scrim").hidden = true; }

// ------- Рендер сообщений -------
function addUserMsg(text) {
  const m = el("div", "msg user", text);
  $("#chat").appendChild(m);
  scrollDown();
}
function startAssistant() {
  const m = el("div", "msg assistant");
  $("#chat").appendChild(m);
  state.currentAssistant = m;
  scrollDown();
  return m;
}
function appendAssistant(delta) {
  if (!state.currentAssistant) startAssistant();
  state.currentAssistant.textContent += delta;
  scrollDown();
}
function addSystemNote(text) {
  $("#chat").appendChild(el("div", "msg system-note", text));
  scrollDown();
}

const TOOL_ICONS = {
  read_file: "📄", list_files: "📁", search_files: "🔎",
  write_file: "✏️", edit_file: "✏️", terminal: "▶", git: "🔀",
};
function addTool(id, name, preview) {
  const details = el("details", "tool");
  const summary = el("summary");
  summary.appendChild(el("span", null, TOOL_ICONS[name] || "🛠"));
  summary.appendChild(el("span", null, preview || name));
  const badge = el("span", "badge", "…");
  summary.appendChild(badge);
  details.appendChild(summary);
  const pre = el("pre");
  details.appendChild(pre);
  details._badge = badge; details._pre = pre;
  $("#chat").appendChild(details);
  state.toolEls[id] = details;
  scrollDown();
  return details;
}
function setToolResult(id, ok, summary, content, extra) {
  const d = state.toolEls[id];
  if (!d) return;
  d._badge.textContent = ok ? "ok" : "ошибка";
  d._badge.className = "badge " + (ok ? "ok" : "err");
  d._pre.textContent = content || summary || "";
  if (extra && extra.diff) renderDiff(d._pre, extra.diff);
  scrollDown();
}
function renderDiff(pre, diff) {
  pre.textContent = "";
  diff.split("\n").forEach((line) => {
    let cls = null;
    if (line.startsWith("+") && !line.startsWith("+++")) cls = "diff-add";
    else if (line.startsWith("-") && !line.startsWith("---")) cls = "diff-del";
    pre.appendChild(el("span", cls, line + "\n"));
  });
}

function scrollDown() {
  const c = $("#chat");
  c.scrollTop = c.scrollHeight;
}

// ------- Отправка / стриминг -------
const input = $("#input");
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 140) + "px";
});
$("#btn-send").addEventListener("click", send);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});

async function send() {
  if (state.running) return;
  const text = input.value.trim();
  if (!text || !state.project) return;
  input.value = ""; input.style.height = "auto";
  addUserMsg(text);
  setRunning(true);
  state.currentAssistant = null;

  try {
    const resp = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        project: state.project,
        message: text,
        conversation_id: state.conversationId,
      }),
    });
    if (!resp.ok) {
      addSystemNote("Ошибка запроса: " + resp.status);
      setRunning(false);
      return;
    }
    await consumeStream(resp);
  } catch (err) {
    addSystemNote("Сбой соединения: " + err.message);
  } finally {
    setRunning(false);
  }
}

async function consumeStream(resp) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      for (const line of block.split("\n")) {
        if (line.startsWith("data:")) {
          const json = line.slice(5).trim();
          if (json) handleEvent(JSON.parse(json));
        }
      }
    }
  }
}

function handleEvent(ev) {
  switch (ev.type) {
    case "session":
      state.conversationId = ev.conversation_id;
      break;
    case "text":
      appendAssistant(ev.delta);
      break;
    case "assistant_message":
      // следующий шаг начнётся с нового пузыря
      state.currentAssistant = null;
      break;
    case "tool_start":
      addTool(ev.id, ev.name, ev.preview);
      break;
    case "tool_result":
      setToolResult(ev.id, ev.ok, ev.summary, ev.content, ev.extra);
      break;
    case "confirm_required":
      showConfirm(ev);
      break;
    case "confirmed":
      break;
    case "blocked":
      addSystemNote("⛔ Заблокировано: " + ev.reason + "\n" + (ev.preview || ""));
      break;
    case "usage":
      showUsage(ev);
      break;
    case "final":
      state.currentAssistant = null;
      break;
    case "stopped":
      addSystemNote("⏹ Агент остановлен.");
      break;
    case "limit":
      addSystemNote(ev.message);
      break;
    case "error":
      addSystemNote("Ошибка: " + ev.message);
      break;
    case "end":
      loadChats();
      break;
  }
}

function setRunning(v) {
  state.running = v;
  $("#btn-stop").hidden = !v;
  $("#btn-send").disabled = v;
}

$("#btn-stop").addEventListener("click", async () => {
  if (!state.conversationId) return;
  await api("/api/agent/stop", {
    method: "POST",
    body: JSON.stringify({ conversation_id: state.conversationId }),
  });
});

function showUsage(u) {
  const box = $("#usage");
  box.hidden = false;
  box.textContent = `Токены: ↑${u.input_tokens} ↓${u.output_tokens} · ≈ $${u.estimated_cost} ${u.currency}`;
}

// ------- Подтверждение опасного действия -------
let pendingCallId = null;
function showConfirm(ev) {
  pendingCallId = ev.id;
  $("#confirm-reason").textContent = ev.reason || "";
  $("#confirm-command").textContent = ev.preview || ev.name;
  $("#confirm-modal").hidden = false;
}
async function resolveConfirm(approved) {
  $("#confirm-modal").hidden = true;
  if (!pendingCallId) return;
  await api("/api/chat/confirm", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: state.conversationId,
      call_id: pendingCallId,
      approved,
    }),
  });
  pendingCallId = null;
}
$("#confirm-allow").addEventListener("click", () => resolveConfirm(true));
$("#confirm-cancel").addEventListener("click", () => resolveConfirm(false));

// ------- Git-панель -------
$("#btn-git").addEventListener("click", () => openGit());
$("#git-close").addEventListener("click", () => { $("#git-modal").hidden = true; });
$("#git-download-zip").addEventListener("click", downloadZip);
document.querySelectorAll(".git-tab").forEach((t) => {
  t.addEventListener("click", () => {
    document.querySelectorAll(".git-tab").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    renderGitTab(t.dataset.tab);
  });
});

function openGit() {
  if (!state.project) return;
  $("#git-project").textContent = state.project;
  $("#git-modal").hidden = false;
  document.querySelectorAll(".git-tab").forEach((x) => x.classList.remove("active"));
  document.querySelector('.git-tab[data-tab="status"]').classList.add("active");
  renderGitTab("status");
}

async function renderGitTab(tab) {
  const body = $("#git-body");
  body.innerHTML = "Загрузка…";
  if (tab === "status") {
    const r = await api("/api/git/status?project=" + encodeURIComponent(state.project));
    const s = await r.json();
    body.innerHTML = "";
    body.appendChild(el("div", "muted", "Ветка: " + (s.branch || "?")));
    const render = (arr, code, cls) => arr.forEach((f) =>
      body.appendChild(el("div", "git-status-line " + cls, code + " " + f)));
    render(s.modified, "M", "m");
    render(s.added, "A", "a");
    render(s.deleted, "D", "d");
    render(s.untracked, "?", "");
    if (!s.modified.length && !s.added.length && !s.deleted.length && !s.untracked.length)
      body.appendChild(el("div", "muted", "Нет изменений."));
  } else if (tab === "diff") {
    const r = await api("/api/git/diff?project=" + encodeURIComponent(state.project));
    const d = await r.json();
    body.innerHTML = "";
    const pre = el("pre");
    if (d.diff) renderDiff(pre, d.diff); else pre.textContent = "Нет изменений.";
    body.appendChild(pre);
  } else if (tab === "commit") {
    body.innerHTML = "";
    const inp = el("input", "git-commit-input");
    inp.placeholder = "fix: краткое описание изменений";
    const btn = el("button", "btn-danger", "Commit");
    btn.style.marginTop = "10px";
    btn.addEventListener("click", async () => {
      if (!inp.value.trim()) return;
      btn.disabled = true;
      const r = await api("/api/git/commit", {
        method: "POST",
        body: JSON.stringify({ project: state.project, message: inp.value.trim() }),
      });
      const res = await r.json();
      body.appendChild(el("div", res.ok ? "muted" : "error",
        res.ok ? "✓ " + (res.last_commit || "commit создан") : res.output));
      btn.disabled = false;
    });
    body.appendChild(inp);
    body.appendChild(btn);
  }
}

async function downloadZip() {
  const r = await api("/api/files/zip", {
    method: "POST",
    body: JSON.stringify({ project: state.project }),
  });
  if (!r.ok) return;
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = state.project + ".zip";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

boot();
