// HTML-отчёты (кнопка «Сохранить в PDF» / печать браузера — без Chromium на VPS).
// Четыре вида: по администратору, по объекту, по сети, по клиентам.

const fetch = require('node-fetch');
const db = require('./db');

const OPENAI_BASE = 'https://api.openai.com/v1';

// calls.started_at приходит от UIS в формате "YYYY-MM-DD HH:mm:ss" (см. telephony.js) —
// используем тот же формат здесь, иначе строковое сравнение в SQL съедет на границе периода.
function periodStart(period) {
  const days = period === 'month' ? 30 : 7;
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString().slice(0, 19).replace('T', ' ');
}

function getAiSettings() {
  return db.prepare('SELECT * FROM ai_settings WHERE id = 1').get();
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
}

async function generateNarrative({ calls, contextLabel }) {
  const settings = getAiSettings();
  if (!settings.openai_api_key || calls.length === 0) {
    return { strengths: '—', weaknesses: '—', recommendations: '—', conclusion: 'Недостаточно данных за период.' };
  }
  const digest = calls.slice(0, 60).map(c => `Звонок #${c.id} (${c.started_at}), чек-лист ${c.checklist_score}/${c.checklist_total}: ${c.summary || '(нет резюме)'}`).join('\n');

  const resp = await fetch(`${OPENAI_BASE}/chat/completions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${settings.openai_api_key}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: settings.analysis_model,
      messages: [
        { role: 'system', content: `Ты готовишь отчёт для владельца сети массажных салонов и сауны по звонкам ${contextLabel} за период. Отвечай строго JSON: {"strengths": string, "weaknesses": string, "recommendations": string, "conclusion": string}. Кратко и предметно, только по переданным данным, по-русски.` },
        { role: 'user', content: digest }
      ],
      response_format: { type: 'json_object' },
      temperature: 0.3
    })
  });
  const json = await resp.json();
  if (!resp.ok) throw new Error(json.error?.message || 'Ошибка OpenAI');
  const costUsd = ((json.usage?.prompt_tokens || 0) * 0.15 + (json.usage?.completion_tokens || 0) * 0.6) / 1_000_000;
  db.prepare('INSERT INTO ai_usage (call_id, kind, cost_usd) VALUES (NULL, ?, ?)').run('report', costUsd);
  try { return JSON.parse(json.choices[0].message.content); }
  catch { return { strengths: '—', weaknesses: '—', recommendations: '—', conclusion: 'Не удалось разобрать ответ ИИ.' }; }
}

function page(title, subtitle, bodyHtml) {
  return `<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>${esc(title)}</title>
<style>
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; max-width: 960px; margin: 24px auto; color: #1a1a1a; }
  h1 { font-size: 22px; } h2 { font-size: 16px; margin-top: 28px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  td, th { padding: 6px 8px; border-bottom: 1px solid #eee; font-size: 13px; text-align: left; vertical-align: top; }
  .bar { display:inline-block; width:120px; height:8px; background:#eee; border-radius:4px; overflow:hidden; vertical-align:middle; margin-right:6px; }
  .bar-fill { height:100%; background:#4a7; }
  .kpi { display:flex; gap:16px; flex-wrap:wrap; }
  .kpi div { background:#f6f6f6; border-radius:8px; padding:12px 16px; min-width:140px; }
  button { margin-top: 24px; padding: 10px 18px; font-size: 14px; cursor: pointer; }
  @media print { button { display: none; } }
</style></head>
<body>
  <h1>${esc(title)}</h1>
  <p>${subtitle}</p>
  ${bodyHtml}
  <button onclick="window.print()">Сохранить в PDF</button>
</body></html>`;
}

function kpiBlock(items) {
  return `<div class="kpi">${items.map(([label, value]) => `<div>${esc(label)}<br><b>${esc(value)}</b></div>`).join('')}</div>`;
}

function checklistFunnel(calls) {
  const byText = new Map();
  for (const c of calls) {
    if (!c.checklist_results) continue;
    for (const item of JSON.parse(c.checklist_results)) {
      if (!byText.has(item.text)) byText.set(item.text, { yes: 0, partial: 0, no: 0 });
      byText.get(item.text)[item.state]++;
    }
  }
  return Array.from(byText.entries()).map(([text, agg]) => {
    const total = agg.yes + agg.partial + agg.no;
    const pct = total ? Math.round(((agg.yes + agg.partial * 0.5) / total) * 100) : 0;
    return { text, pct, ...agg };
  }).sort((a, b) => a.pct - b.pct);
}

function funnelTable(funnel) {
  const rows = funnel.map(f => `
    <tr><td>${esc(f.text)}</td>
    <td><div class="bar"><div class="bar-fill" style="width:${f.pct}%"></div></div>${f.pct}%</td>
    <td>✅${f.yes} ⚠️${f.partial} ❌${f.no}</td></tr>`).join('');
  return `<table><tr><th>Пункт</th><th>Выполнение</th><th>Детали</th></tr>${rows || '<tr><td colspan="3">Нет данных</td></tr>'}</table>`;
}

function narrativeBlocks(n) {
  return `
    <h2>Сильные стороны</h2><p>${esc(n.strengths)}</p>
    <h2>Слабые места</h2><p>${esc(n.weaknesses)}</p>
    <h2>Рекомендации</h2><p>${esc(n.recommendations)}</p>
    <h2>Вывод для владельца</h2><p>${esc(n.conclusion)}</p>`;
}

function callsTable(calls) {
  const rows = calls.slice(0, 100).map(c => `
    <tr>
      <td>${esc(c.started_at)}</td><td>${esc(c.salon_name || '')}</td>
      <td>${esc(c.matched_admin_name || c.detected_admin_name || '—')}</td>
      <td>${c.checklist_score ?? '—'}/${c.checklist_total ?? '—'}</td>
      <td>${esc(c.outcome || '—')}</td><td>${esc(c.summary || '')}</td>
    </tr>`).join('');
  return `<table><tr><th>Дата</th><th>Объект</th><th>Администратор</th><th>Чек-лист</th><th>Исход</th><th>Резюме</th></tr>
    ${rows || '<tr><td colspan="6">Нет звонков за период</td></tr>'}</table>`;
}

function answeredCallsQuery(where, params) {
  return db.prepare(`
    SELECT c.*, s.name AS salon_name, a.name AS matched_admin_name
    FROM calls c JOIN salons s ON s.id = c.salon_id
    LEFT JOIN admins a ON a.id = c.matched_admin_id
    WHERE c.status = 'done' AND ${where}
    ORDER BY c.started_at DESC
  `).all(...params);
}

async function renderAdminReport(adminId, period) {
  const admin = db.prepare('SELECT a.*, s.name AS salon_name FROM admins a JOIN salons s ON s.id = a.salon_id WHERE a.id = ?').get(adminId);
  if (!admin) throw new Error('Администратор не найден');

  const calls = answeredCallsQuery('c.matched_admin_id = ? AND c.started_at >= ?', [adminId, periodStart(period)]);
  const avgPct = calls.length ? Math.round(calls.reduce((s, c) => s + (c.checklist_score / (c.checklist_total || 1)), 0) / calls.length * 100) : 0;
  const noIntro = calls.filter(c => c.checklist_results && JSON.parse(c.checklist_results).some(i => /представ/i.test(i.text) && i.state === 'no')).length;
  const bookings = calls.filter(c => c.outcome === 'booking').length;
  const funnel = checklistFunnel(calls);
  const narrative = await generateNarrative({ calls, contextLabel: `администратора ${admin.name} (${admin.salon_name})` });

  const body = `
    <h2>KPI</h2>${kpiBlock([
      ['Звонков принято', calls.length],
      ['Средний % чек-листа', avgPct + '%'],
      ['Записей оформлено', bookings],
      ['Не представилась', noIntro]
    ])}
    <h2>Проблемные пункты чек-листа</h2>${funnelTable(funnel)}
    ${narrativeBlocks(narrative)}
    <h2>Звонки за период</h2>${callsTable(calls)}
  `;
  return page(`Отчёт по администратору: ${admin.name}`, `Объект: ${esc(admin.salon_name)} · Период: ${period === 'month' ? 'месяц' : 'неделя'}`, body);
}

async function renderSalonReport(salonId, period) {
  const salon = db.prepare('SELECT * FROM salons WHERE id = ?').get(salonId);
  if (!salon) throw new Error('Объект не найден');
  const since = periodStart(period);

  const calls = answeredCallsQuery('c.salon_id = ? AND c.started_at >= ?', [salonId, since]);
  const missed = db.prepare(`SELECT COUNT(*) AS c FROM calls WHERE salon_id=? AND direction='in' AND is_answered=0 AND started_at >= ?`).get(salonId, since).c;
  const onTime = db.prepare(`SELECT COUNT(*) AS c FROM calls WHERE salon_id=? AND direction='in' AND is_answered=0 AND callback_status='on_time' AND started_at >= ?`).get(salonId, since).c;
  const late = db.prepare(`SELECT COUNT(*) AS c FROM calls WHERE salon_id=? AND direction='in' AND is_answered=0 AND callback_status='late' AND started_at >= ?`).get(salonId, since).c;
  const none = db.prepare(`SELECT COUNT(*) AS c FROM calls WHERE salon_id=? AND direction='in' AND is_answered=0 AND callback_status='none' AND started_at >= ?`).get(salonId, since).c;
  const bookings = calls.filter(c => c.outcome === 'booking').length;
  const conversion = calls.length ? Math.round((bookings / calls.length) * 100) : 0;

  const byAdmin = db.prepare(`
    SELECT a.name, COUNT(c.id) AS calls_count, AVG(c.checklist_score * 1.0 / NULLIF(c.checklist_total,0)) AS avg_pct
    FROM admins a LEFT JOIN calls c ON c.matched_admin_id = a.id AND c.status='done' AND c.started_at >= ?
    WHERE a.salon_id = ? GROUP BY a.id ORDER BY calls_count DESC
  `).all(since, salonId);

  const funnel = checklistFunnel(calls);
  const narrative = await generateNarrative({ calls, contextLabel: `по объекту «${salon.name}»` });

  const adminRows = byAdmin.map(a => `<tr><td>${esc(a.name)}</td><td>${a.calls_count}</td><td>${a.avg_pct ? Math.round(a.avg_pct * 100) + '%' : '—'}</td></tr>`).join('');

  const body = `
    <h2>KPI</h2>${kpiBlock([
      ['Звонков', calls.length], ['Пропущено', missed],
      ['Перезвонили вовремя', onTime], ['Перезвонили позже', late], ['Не перезвонили', none],
      ['Конверсия в запись', conversion + '%']
    ])}
    <h2>Администраторы объекта</h2>
    <table><tr><th>Имя</th><th>Звонков</th><th>Средний % чек-листа</th></tr>${adminRows || '<tr><td colspan="3">Нет данных</td></tr>'}</table>
    <h2>Проблемные пункты чек-листа</h2>${funnelTable(funnel)}
    ${narrativeBlocks(narrative)}
    <h2>Звонки за период</h2>${callsTable(calls)}
  `;
  return page(`Отчёт по объекту «${salon.name}»`, `Тип: ${salon.type === 'sauna' ? 'сауна' : 'салон'} · Период: ${period === 'month' ? 'месяц' : 'неделя'}`, body);
}

async function renderNetworkReport(period) {
  const since = periodStart(period);
  const salons = db.prepare('SELECT * FROM salons WHERE active = 1').all();
  const calls = answeredCallsQuery('c.started_at >= ?', [since]);
  const missed = db.prepare(`SELECT COUNT(*) AS c FROM calls WHERE direction='in' AND is_answered=0 AND started_at >= ?`).get(since).c;
  const none = db.prepare(`SELECT COUNT(*) AS c FROM calls WHERE direction='in' AND is_answered=0 AND callback_status='none' AND started_at >= ?`).get(since).c;
  const bookings = calls.filter(c => c.outcome === 'booking').length;

  const perSalon = salons.map(s => {
    const sc = calls.filter(c => c.salon_id === s.id);
    const sMissed = db.prepare(`SELECT COUNT(*) AS c FROM calls WHERE salon_id=? AND direction='in' AND is_answered=0 AND started_at >= ?`).get(s.id, since).c;
    const sBookings = sc.filter(c => c.outcome === 'booking').length;
    return { name: s.name, calls: sc.length, missed: sMissed, bookings: sBookings, conv: sc.length ? Math.round(sBookings / sc.length * 100) : 0 };
  });

  const narrative = await generateNarrative({ calls, contextLabel: 'по всей сети (5 объектов)' });
  const rows = perSalon.map(s => `<tr><td>${esc(s.name)}</td><td>${s.calls}</td><td>${s.missed}</td><td>${s.bookings}</td><td>${s.conv}%</td></tr>`).join('');

  const body = `
    <h2>KPI сети</h2>${kpiBlock([
      ['Звонков', calls.length], ['Пропущено', missed], ['Не перезвонили', none],
      ['Записей', bookings], ['Конверсия', calls.length ? Math.round(bookings / calls.length * 100) + '%' : '0%']
    ])}
    <h2>Сравнение объектов</h2>
    <table><tr><th>Объект</th><th>Звонков</th><th>Пропущено</th><th>Записей</th><th>Конверсия</th></tr>${rows}</table>
    ${narrativeBlocks(narrative)}
  `;
  return page('Сводный отчёт по сети', `Период: ${period === 'month' ? 'месяц' : 'неделя'}`, body);
}

async function renderClientsReport(period) {
  const since = periodStart(period);
  const clients = db.prepare(`
    SELECT cl.*,
      (SELECT COUNT(*) FROM calls c WHERE c.client_id = cl.id AND c.started_at >= ?) AS calls_in_period,
      (SELECT COUNT(*) FROM visits v WHERE v.client_id = cl.id AND v.arrived = 1) AS visits_count,
      (SELECT COUNT(*) FROM bookings b WHERE b.client_id = cl.id) AS bookings_count
    FROM clients cl
  `).all(since);

  const activeInPeriod = clients.filter(c => c.calls_in_period > 0);
  const newClients = activeInPeriod.filter(c => c.visits_count === 0 && c.bookings_count <= 1).length;
  const repeat = activeInPeriod.length - newClients;

  const arrivedTotal = db.prepare(`SELECT COUNT(*) AS c FROM visits WHERE arrived = 1 AND visited_date >= date(?)`).get(since).c;
  const bookedTotal = db.prepare(`SELECT COUNT(*) AS c FROM bookings WHERE created_at >= ?`).get(since).c;
  const arrivalRate = bookedTotal ? Math.round((arrivedTotal / bookedTotal) * 100) : 0;

  const top = db.prepare(`
    SELECT cl.phone, cl.name, COUNT(v.id) AS visits FROM clients cl
    JOIN visits v ON v.client_id = cl.id AND v.arrived = 1
    GROUP BY cl.id ORDER BY visits DESC LIMIT 15
  `).all();

  const sleeping = db.prepare(`
    SELECT cl.phone, cl.name, MAX(v.visited_date) AS last_visit FROM clients cl
    JOIN visits v ON v.client_id = cl.id AND v.arrived = 1
    GROUP BY cl.id HAVING julianday('now') - julianday(last_visit) > 60
    ORDER BY last_visit ASC LIMIT 15
  `).all();

  const topRows = top.map(c => `<tr><td>${esc(c.name || '—')}</td><td>${esc(c.phone)}</td><td>${c.visits}</td></tr>`).join('');
  const sleepingRows = sleeping.map(c => `<tr><td>${esc(c.name || '—')}</td><td>${esc(c.phone)}</td><td>${esc(c.last_visit)}</td></tr>`).join('');

  const body = `
    <h2>KPI</h2>${kpiBlock([
      ['Новых клиентов', newClients], ['Повторных', repeat],
      ['Доля дошедших', arrivalRate + '%']
    ])}
    <h2>Топ клиентов по визитам</h2>
    <table><tr><th>Имя</th><th>Телефон</th><th>Визитов</th></tr>${topRows || '<tr><td colspan="3">Нет данных</td></tr>'}</table>
    <h2>«Спящие» клиенты (готовы к реактивации)</h2>
    <table><tr><th>Имя</th><th>Телефон</th><th>Последний визит</th></tr>${sleepingRows || '<tr><td colspan="3">Нет данных</td></tr>'}</table>
  `;
  return page('Отчёт по клиентам', `Период: ${period === 'month' ? 'месяц' : 'неделя'}`, body);
}

module.exports = { renderAdminReport, renderSalonReport, renderNetworkReport, renderClientsReport };
