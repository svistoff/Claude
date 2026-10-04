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
      response_format: { type: 'json_object' }
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

// старые звонки хранят {state: yes|partial|no}, новые — {status: PASS|FAIL|PARTIAL|NA|UNCERTAIN}
function statusOf(item) {
  if (item.status) return item.status;
  if (item.state === 'yes') return 'PASS';
  if (item.state === 'partial') return 'PARTIAL';
  if (item.state === 'no') return 'FAIL';
  return 'UNCERTAIN';
}

// NA/UNCERTAIN не считаются ни выполнением, ни невыполнением — исключаются
// из знаменателя статистики (см. тех. задание "контекстная оценка", разделы 36-37)
function checklistFunnel(calls) {
  const byText = new Map();
  for (const c of calls) {
    if (!c.checklist_results) continue;
    for (const item of JSON.parse(c.checklist_results)) {
      if (!byText.has(item.text)) byText.set(item.text, { pass: 0, partial: 0, fail: 0, na: 0, uncertain: 0 });
      const status = statusOf(item);
      const agg = byText.get(item.text);
      if (status === 'PASS') agg.pass++;
      else if (status === 'PARTIAL') agg.partial++;
      else if (status === 'FAIL') agg.fail++;
      else if (status === 'NA') agg.na++;
      else agg.uncertain++;
    }
  }
  return Array.from(byText.entries()).map(([text, agg]) => {
    const applicable = agg.pass + agg.partial + agg.fail;
    const pct = applicable ? Math.round(((agg.pass + agg.partial * 0.5) / applicable) * 100) : 0;
    return { text, pct, applicable, ...agg };
  }).sort((a, b) => a.pct - b.pct);
}

function funnelTable(funnel) {
  const rows = funnel.map(f => `
    <tr><td>${esc(f.text)}</td>
    <td>${f.applicable ? `<div class="bar"><div class="bar-fill" style="width:${f.pct}%"></div></div>${f.pct}%` : '<span class="muted">не применялось</span>'}</td>
    <td>✅${f.pass} ⚠️${f.partial} ❌${f.fail}${f.na ? ` ➖${f.na}` : ''}${f.uncertain ? ` ❓${f.uncertain}` : ''}</td></tr>`).join('');
  return `<table><tr><th>Пункт</th><th>Выполнение (из применимых)</th><th>Детали</th></tr>${rows || '<tr><td colspan="3">Нет данных</td></tr>'}</table>`;
}

function narrativeBlocks(n) {
  return `
    <h2>Сильные стороны</h2><p>${esc(n.strengths)}</p>
    <h2>Слабые места</h2><p>${esc(n.weaknesses)}</p>
    <h2>Рекомендации</h2><p>${esc(n.recommendations)}</p>
    <h2>Вывод для владельца</h2><p>${esc(n.conclusion)}</p>`;
}

// та же тепловая шкала (красный->жёлтый->зелёный), что и в интерфейсе — вместо
// голой дроби "из применимых баллов", см. public/index.html's qualityColor()
function qualityColor(pct) {
  const stops = pct <= 50 ? [[0xdd,0x33,0x33],[0xc9,0x8a,0x00]] : [[0xc9,0x8a,0x00],[0x2a,0x9d,0x5c]];
  const t = pct <= 50 ? pct / 50 : (pct - 50) / 50;
  const [r1,g1,b1] = stops[0], [r2,g2,b2] = stops[1];
  const r = Math.round(r1 + (r2-r1)*t), g = Math.round(g1 + (g2-g1)*t), b = Math.round(b1 + (b2-b1)*t);
  return `rgb(${r},${g},${b})`;
}
function qualityBadge(score, total) {
  if (score == null || !total) return '—';
  const pct = Math.round((score / total) * 100);
  return `<span style="font-weight:600;color:${qualityColor(pct)}">${pct}%</span>`;
}

function callsTable(calls) {
  const rows = calls.slice(0, 100).map(c => {
    let criticalCount = 0;
    try { criticalCount = c.critical_errors ? JSON.parse(c.critical_errors).length : 0; } catch { /* noop */ }
    return `
    <tr>
      <td>${esc(c.started_at)}</td><td>${esc(c.salon_name || '')}</td>
      <td>${esc(c.matched_admin_name || c.detected_admin_name || '—')}</td>
      <td>${qualityBadge(c.checklist_score, c.checklist_total)}</td>
      <td>${criticalCount ? `⚠️${criticalCount}` : '—'}</td>
      <td>${esc(c.outcome || '—')}</td><td>${esc(c.summary || '')}</td>
    </tr>`;
  }).join('');
  return `<table><tr><th>Дата</th><th>Объект</th><th>Администратор</th><th>Чек-лист</th><th>Крит. ошибки</th><th>Исход</th><th>Резюме</th></tr>
    ${rows || '<tr><td colspan="7">Нет звонков за период</td></tr>'}</table>`;
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
  // администратор не привязан к объекту — работает по всей сети,
  // поэтому в подписи отчёта перечисляем объекты, где реально были звонки за период
  const admin = db.prepare('SELECT * FROM admins WHERE id = ?').get(adminId);
  if (!admin) throw new Error('Администратор не найден');

  const calls = answeredCallsQuery('c.matched_admin_id = ? AND c.started_at >= ?', [adminId, periodStart(period)]);
  const avgPct = calls.length ? Math.round(calls.reduce((s, c) => s + (c.checklist_score / (c.checklist_total || 1)), 0) / calls.length * 100) : 0;
  const noIntro = calls.filter(c => c.checklist_results && JSON.parse(c.checklist_results).some(i => /представ/i.test(i.text) && i.state === 'no')).length;
  const bookings = calls.filter(c => c.outcome === 'booking').length;
  const funnel = checklistFunnel(calls);
  const salonsTouched = [...new Set(calls.map(c => c.salon_name))].join(', ') || 'нет звонков за период';
  const narrative = await generateNarrative({ calls, contextLabel: `администратора ${admin.name} (${salonsTouched})` });

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
  return page(`Отчёт по администратору: ${admin.name}`, `Объекты: ${esc(salonsTouched)} · Период: ${period === 'month' ? 'месяц' : 'неделя'}`, body);
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

  // администратор больше не привязан к объекту — считаем тех, кто реально
  // принимал звонки этого объекта за период (по calls, а не по admins.salon_id)
  const byAdmin = db.prepare(`
    SELECT a.name, COUNT(c.id) AS calls_count, AVG(c.checklist_score * 1.0 / NULLIF(c.checklist_total,0)) AS avg_pct
    FROM calls c JOIN admins a ON a.id = c.matched_admin_id
    WHERE c.salon_id = ? AND c.status = 'done' AND c.started_at >= ?
    GROUP BY a.id ORDER BY calls_count DESC
  `).all(salonId, since);

  const funnel = checklistFunnel(calls);
  const narrative = await generateNarrative({ calls, contextLabel: `по объекту «${salon.name}»` });

  const adminRows = byAdmin.map(a => `<tr><td>${esc(a.name)}</td><td>${a.calls_count}</td><td>${a.avg_pct ? Math.round(a.avg_pct * 100) + '%' : '—'}</td></tr>`).join('');

  const body = `
    <h2>KPI</h2>${kpiBlock([
      ['Звонков', calls.length], ['Пропущено', missed],
      ['Перезвонили вовремя', onTime], ['Перезвонили позже', late], ['Не перезвонили', none],
      ['Конверсия в запись', conversion + '%']
    ])}
    <h2>Администраторы, принимавшие звонки</h2>
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

async function renderAdNumbersReport(period) {
  const since = periodStart(period);
  const rows = db.prepare(`
    SELECT an.id, an.phone, an.label, an.note, COUNT(c.id) AS calls
    FROM ad_phone_numbers an
    LEFT JOIN calls c ON c.dialed_number = an.phone AND c.started_at >= ?
    GROUP BY an.id
    ORDER BY calls DESC, an.label
  `).all(since);

  const totalCalls = rows.reduce((s, r) => s + r.calls, 0);
  const working = rows.filter(r => r.calls > 0).length;
  const maxVal = Math.max(1, ...rows.map(r => r.calls));

  const tableRows = rows.map(r => `
    <tr><td>${esc(r.label)}</td><td>${esc(r.phone)}</td>
    <td><div class="bar"><div class="bar-fill" style="width:${Math.round(r.calls / maxVal * 100)}%"></div></div>${r.calls}</td>
    <td>${r.note ? esc(r.note) : '—'}</td></tr>`).join('');

  // Динамика по дням для каждой анкеты отдельно — суммы выше не показывают,
  // подействовало ли изменение ставки/цены на конкретную анкету в конкретный
  // день; выходные подсвечены для сверки эффекта по будням/выходным.
  const dayRows = db.prepare(`
    SELECT an.id AS ad_id, substr(c.started_at,1,10) AS day, COUNT(*) AS calls
    FROM ad_phone_numbers an
    JOIN calls c ON c.dialed_number = an.phone AND c.started_at >= ?
    GROUP BY an.id, day
  `).all(since);

  const days = [];
  const cur = new Date(since.slice(0, 10) + 'T00:00:00Z');
  const endDay = new Date();
  while (cur <= endDay) { days.push(cur.toISOString().slice(0, 10)); cur.setUTCDate(cur.getUTCDate() + 1); }

  const countsByKey = new Map(dayRows.map(r => [`${r.ad_id}|${r.day}`, r.calls]));
  const isWeekend = d => { const wd = new Date(d + 'T00:00:00Z').getUTCDay(); return wd === 0 || wd === 6; };
  const dailyHeader = `<tr><th>Метка</th>${days.map(d => `<th style="text-align:center;${isWeekend(d) ? 'background:#fdf3d8' : ''}">${d.slice(8, 10)}.${d.slice(5, 7)}</th>`).join('')}</tr>`;
  const dailyBodyRows = rows.map(r => {
    const cells = days.map(d => {
      const c = countsByKey.get(`${r.id}|${d}`) || 0;
      return `<td style="text-align:center;${isWeekend(d) ? 'background:#fdf3d8' : ''}">${c || ''}</td>`;
    }).join('');
    return `<tr><td>${esc(r.label)}<br><span style="color:#888;font-size:11px">${esc(r.phone)}</span></td>${cells}</tr>`;
  }).join('');

  const body = `
    <h2>KPI</h2>${kpiBlock([
      ['Номеров в пуле', rows.length],
      ['Дали хотя бы один звонок', working],
      ['Всего звонков', totalCalls]
    ])}
    <h2>Звонки по анкетам/площадкам</h2>
    <table><tr><th>Метка</th><th>Номер</th><th>Звонков</th><th>Заметка</th></tr>
      ${tableRows || '<tr><td colspan="4">Номера ещё не добавлены (Настройки → Номера и анкеты)</td></tr>'}</table>
    <h2>Динамика по дням (каждая анкета отдельно)</h2>
    <div style="overflow-x:auto"><table>${rows.length ? dailyHeader + dailyBodyRows : '<tr><td>Номера ещё не добавлены</td></tr>'}</table></div>
  `;
  return page('Отчёт по анкетам и номерам', `Период: ${period === 'month' ? 'месяц' : 'неделя'}`, body);
}

module.exports = { renderAdminReport, renderSalonReport, renderNetworkReport, renderClientsReport, renderAdNumbersReport };
