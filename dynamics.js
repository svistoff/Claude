// «Отчёт для шефа» (/api/dynamics, только владелец): входящие звонки
// с анкетных (платных) номеров по салонам по неделям (пн–вс) или месяцам,
// плюс вручную внесённый общий недельный расход на анкеты и цена звонка.

const express = require('express');
const db = require('./db');

const router = express.Router();
const DAY = 86400000;

db.exec(`
CREATE TABLE IF NOT EXISTS weekly_spend (
  week_start TEXT PRIMARY KEY,   -- понедельник недели, ГГГГ-ММ-ДД
  amount REAL NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
`);

const iso = t => new Date(t).toISOString().slice(0, 10);
const parse = d => Date.parse(d + 'T00:00:00Z');
function mondayOf(day) {
  const t = parse(day);
  return iso(t - ((new Date(t).getUTCDay() + 6) % 7) * DAY);
}
const monthOf = day => day.slice(0, 7) + '-01';

function todayLocal() {
  const offset = db.prepare('SELECT uis_timezone_offset_hours FROM telephony_settings WHERE id = 1').get().uis_timezone_offset_hours || 0;
  return iso(Date.now() + offset * 3600000);
}

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const ddmm = d => `${d.slice(8, 10)}.${d.slice(5, 7)}`;

// периоды диапазона; крайние могут быть неполными, если даты выбраны вручную
function buildPeriods(granularity, from, till) {
  const periods = [];
  let start = granularity === 'month' ? monthOf(from) : mondayOf(from);
  while (start <= till) {
    let next;
    if (granularity === 'month') {
      const d = new Date(parse(start));
      next = iso(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1));
    } else {
      next = iso(parse(start) + 7 * DAY);
    }
    const pFrom = start < from ? from : start;
    const lastDay = iso(parse(next) - DAY);
    const pTill = lastDay > till ? till : lastDay;
    const full = pFrom === start && pTill === lastDay;
    const label = granularity === 'month'
      ? `${MONTHS[Number(start.slice(5, 7)) - 1]} ${start.slice(0, 4)}`
      : `${ddmm(pFrom)}–${ddmm(pTill)}`;
    periods.push({ key: start, from: pFrom, till: pTill, label, full });
    start = next;
  }
  return periods;
}

// расчёт отчёта — общий для экрана и печатной (PDF) версии
function computeDynamics(query) {
  const granularity = query.granularity === 'month' ? 'month' : 'week';
  const dateRe = /^\d{4}-\d{2}-\d{2}$/;
  const today = todayLocal();
  let from, till;
  if (dateRe.test(query.date_from || '') && dateRe.test(query.date_till || '')) {
    [from, till] = query.date_from <= query.date_till ? [query.date_from, query.date_till] : [query.date_till, query.date_from];
  } else if (granularity === 'month') {
    const d = new Date(parse(today));
    from = iso(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - 11, 1));
    till = today;
  } else {
    from = iso(parse(mondayOf(today)) - 11 * 7 * DAY);
    till = today;
  }
  const periods = buildPeriods(granularity, from, till);
  if (periods.length > 120) return { error: 'Слишком длинный период — выберите меньше дат или помесячно' };
  const index = new Map(periods.map((p, i) => [p.key, i]));
  const bucket = day => index.get(granularity === 'month' ? monthOf(day) : mondayOf(day));

  // только входящие звонки на номера из пула анкет (Настройки -> «Номера и анкеты»)
  const calls = db.prepare(`
    SELECT c.salon_id, substr(c.started_at, 1, 10) AS day
    FROM calls c WHERE c.direction = 'in' AND c.started_at >= ? AND c.started_at <= ?
      AND EXISTS (SELECT 1 FROM ad_phone_numbers an WHERE an.phone = c.dialed_number)
  `).all(from + ' 00:00:00', till + ' 23:59:59');

  const empty = () => periods.map(() => ({ total: 0 }));
  const bySalon = new Map();
  const totals = empty();
  for (const c of calls) {
    const i = bucket(c.day);
    if (i === undefined) continue;
    if (!bySalon.has(c.salon_id)) bySalon.set(c.salon_id, empty());
    const cell = bySalon.get(c.salon_id)[i];
    cell.total++; totals[i].total++;
  }
  const salons = db.prepare('SELECT id, name FROM salons ORDER BY name').all()
    .filter(s => bySalon.has(s.id))
    .map(s => ({ id: s.id, name: s.name, cells: bySalon.get(s.id) || empty() }));

  // расход вносится по неделям; в помесячном режиме неделя относится к месяцу своего понедельника
  const spendRows = db.prepare('SELECT week_start, amount FROM weekly_spend WHERE week_start >= ? AND week_start <= ?')
    .all(granularity === 'month' ? from : mondayOf(from), till);
  const spend = periods.map(() => null);
  for (const r of spendRows) {
    const i = granularity === 'month' ? index.get(monthOf(r.week_start)) : index.get(r.week_start);
    if (i !== undefined) spend[i] = (spend[i] || 0) + r.amount;
  }

  // в режиме по умолчанию не показываем пустые периоды до начала данных
  let skip = 0;
  if (!query.date_from) {
    while (skip < periods.length - 1 && !totals[skip].total && spend[skip] == null) skip++;
  }
  const cut = arr => arr.slice(skip);
  return {
    granularity, from: periods[skip].from, till, periods: cut(periods),
    salons: salons.map(s => ({ ...s, cells: cut(s.cells) })), totals: cut(totals), spend: cut(spend)
  };
}

router.get('/', (req, res) => {
  const d = computeDynamics(req.query);
  if (d.error) return res.status(400).json(d);
  res.json(d);
});

// ---------- печатная версия (браузер -> «Сохранить в PDF») ----------
const esc = v => String(v ?? '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
const money = v => v == null ? '—' : Math.round(v).toLocaleString('ru-RU') + ' ₽';
const ruDate = d => `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(0, 4)}`;
function weekShort(p) {
  return p.from.slice(5, 7) === p.till.slice(5, 7)
    ? `${p.from.slice(8, 10)}–${p.till.slice(8, 10)}.${p.till.slice(5, 7)}`
    : `${p.from.slice(8, 10)}.${p.from.slice(5, 7)}–${p.till.slice(8, 10)}.${p.till.slice(5, 7)}`;
}
function change(cur, prev) {
  if (!prev) return '';
  const pct = Math.round((cur - prev) / prev * 100);
  if (!pct) return '<div class="ch">0%</div>';
  return `<div class="ch ${pct > 0 ? 'up' : 'down'}">${pct > 0 ? '▲' : '▼'}${Math.abs(pct)}%</div>`;
}

router.get('/print', (req, res) => {
  const d = computeDynamics(req.query);
  if (d.error) return res.status(400).send(esc(d.error));
  const week = d.granularity === 'week';
  // выбранный период: из параметра selected, иначе последний завершённый
  let sel = d.periods.findIndex(p => p.key === req.query.selected);
  if (sel === -1) { sel = d.periods.length - 1; while (sel > 0 && !d.periods[sel].full) sel--; }
  const P = d.periods[sel];
  const name = week ? `Неделя ${weekShort(P)}` : P.label;
  const calls = d.totals[sel].total, spend = d.spend[sel];
  const prev = sel > 0 ? d.totals[sel - 1].total : null;
  const prevChange = prev ? Math.round((calls - prev) / prev * 100) : null;
  const prevOf = (arr, i) => i && d.periods[i].full ? arr[i - 1] : null;
  const maxV = Math.max(1, ...d.totals.map(t => t.total));
  const label = p => week ? weekShort(p) : p.label;

  const bars = d.totals.map((t, i) => `<div class="bar ${i === sel ? 'sel' : ''}">
      <div class="v">${t.total}</div><div class="b" style="height:${Math.round(t.total / maxV * 90)}px"></div>
      <div class="l">${esc(week ? weekShort(d.periods[i]) : d.periods[i].label.split(' ')[0])}</div></div>`).join('');
  const th = d.periods.map((p, i) => `<th class="${i === sel ? 'sel' : ''}">${esc(label(p))}${p.full ? '' : '<div class="ch">неполн.</div>'}</th>`).join('');
  const cell = (c, pr, i) => `<td class="${i === sel ? 'sel' : ''}"><b>${c.total || '·'}</b>${pr ? change(c.total, pr.total) : ''}</td>`;
  const rows = d.salons.map(s => `<tr><td class="name">${esc(s.name)}</td>${s.cells.map((c, i) => cell(c, prevOf(s.cells, i), i)).join('')}</tr>`).join('');
  const total = `<tr class="total"><td class="name">Всего с анкет</td>${d.totals.map((c, i) => cell(c, prevOf(d.totals, i), i)).join('')}</tr>`;
  const spendRow = `<tr><td class="name">Потрачено на анкеты</td>${d.spend.map((v, i) => `<td class="${i === sel ? 'sel' : ''}">${money(v)}</td>`).join('')}</tr>`;
  const costRow = `<tr><td class="name">Цена звонка с анкеты</td>${d.spend.map((v, i) => `<td class="${i === sel ? 'sel' : ''}">${v != null && d.totals[i].total ? money(v / d.totals[i].total) : '—'}</td>`).join('')}</tr>`;

  res.send(`<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Отчёт для шефа — ${esc(name)}</title>
<style>
  @page { size: A4 landscape; margin: 12mm; }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; color: #1a1c1f; max-width: 1100px; margin: 20px auto; padding: 0 16px; }
  h1 { font-size: 22px; margin: 0 0 4px; } .muted { color: #6b7280; font-size: 12px; }
  h2 { font-size: 15px; margin: 22px 0 8px; border-bottom: 1px solid #e3e5e9; padding-bottom: 4px; }
  .kpi { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 14px; }
  .kpi div { background: #f3f0fb; border-radius: 10px; padding: 12px 16px; min-width: 170px; }
  .kpi b { display: block; font-size: 24px; margin-top: 2px; }
  .chart { display: flex; gap: 6px; align-items: flex-end; height: 165px; }
  .bar { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; }
  .bar .b { width: 60%; max-width: 34px; background: #c4b5fd; border-radius: 4px 4px 0 0; }
  .bar.sel .b { background: #8b5cf6; } .bar .v { font-size: 11px; font-weight: 600; } .bar .l { font-size: 10px; color: #6b7280; white-space: nowrap; margin-top: 3px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { padding: 6px 5px; border-bottom: 1px solid #eee; text-align: center; vertical-align: top; }
  th { font-size: 11px; color: #6b7280; white-space: nowrap; } td.name { text-align: left; font-weight: 600; white-space: nowrap; }
  .sel { background: #f3f0fb; } tr.total td { border-top: 2px solid #ccc; }
  .ch { font-size: 10px; color: #6b7280; } .ch.up { color: #2a9d5c; } .ch.down { color: #d33; }
  button { margin-top: 20px; padding: 10px 18px; font-size: 14px; cursor: pointer; }
  @media print {
    button { display: none; }
    body { margin: 0; padding: 0; }
    h2 { margin: 12px 0 6px; } .kpi { margin-top: 10px; } .kpi div { padding: 8px 14px; }
    .chart { height: 130px; } th, td { padding: 4px 4px; }
  }
</style></head><body>
<h1>Отчёт для шефа — звонки с платных анкет</h1>
<div class="muted">${esc(name)}${P.full ? '' : ' (ещё идёт)'} · динамика ${ruDate(d.from)} — ${ruDate(d.till)}, ${week ? 'по неделям (пн–вс)' : 'по месяцам'}</div>
<div class="kpi">
  <div>Звонков с анкет<b>${calls}</b>${prevChange == null ? '' : `<span class="ch ${prevChange > 0 ? 'up' : prevChange < 0 ? 'down' : ''}">${prevChange > 0 ? '▲' : prevChange < 0 ? '▼' : ''}${Math.abs(prevChange)}% к ${week ? 'прошлой неделе' : 'прошлому месяцу'}</span>`}</div>
  <div>Потрачено на анкеты<b>${money(spend)}</b></div>
  <div>Цена звонка с анкеты<b>${spend != null && calls ? money(spend / calls) : '—'}</b></div>
</div>
<h2>Звонки с анкет ${week ? 'по неделям' : 'по месяцам'}</h2>
<div class="chart">${bars}</div>
<h2>По салонам</h2>
<table><tr><th style="text-align:left">Салон</th>${th}</tr>${rows}${total}${spendRow}${costRow}</table>
<p class="muted">Входящие звонки на номера анкет; салон — тот, что выбран у номера анкеты. Выделен период, за который итоги вверху.${week ? '' : ' Расход за месяц — сумма недель, понедельник которых приходится на этот месяц.'}</p>
<button onclick="window.print()">Сохранить в PDF</button>
</body></html>`);
});

router.put('/spend/:weekStart', (req, res) => {
  const week = req.params.weekStart;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(week) || mondayOf(week) !== week) return res.status(400).json({ error: 'Неделя задаётся датой понедельника' });
  const raw = req.body?.amount;
  if (raw === null || raw === '' || raw === undefined) {
    db.prepare('DELETE FROM weekly_spend WHERE week_start = ?').run(week);
    return res.json({ ok: true, amount: null });
  }
  const amount = Number(String(raw).replace(/\s/g, '').replace(',', '.'));
  if (!Number.isFinite(amount) || amount < 0) return res.status(400).json({ error: 'Сумма должна быть числом' });
  db.prepare(`INSERT INTO weekly_spend (week_start, amount) VALUES (?, ?)
    ON CONFLICT(week_start) DO UPDATE SET amount = excluded.amount, updated_at = datetime('now')`).run(week, amount);
  res.json({ ok: true, amount });
});

module.exports = router;
