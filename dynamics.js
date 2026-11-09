// Отчёт «Динамика» (/api/dynamics, только владелец): входящие звонки по
// салонам по неделям (пн–вс) или месяцам — всего и из них с анкет — плюс
// вручную внесённый недельный расход на анкеты и цена звонка.

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

router.get('/', (req, res) => {
  const granularity = req.query.granularity === 'month' ? 'month' : 'week';
  const dateRe = /^\d{4}-\d{2}-\d{2}$/;
  const today = todayLocal();
  let from, till;
  if (dateRe.test(req.query.date_from || '') && dateRe.test(req.query.date_till || '')) {
    [from, till] = req.query.date_from <= req.query.date_till ? [req.query.date_from, req.query.date_till] : [req.query.date_till, req.query.date_from];
  } else if (granularity === 'month') {
    const d = new Date(parse(today));
    from = iso(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - 11, 1));
    till = today;
  } else {
    from = iso(parse(mondayOf(today)) - 11 * 7 * DAY);
    till = today;
  }
  const periods = buildPeriods(granularity, from, till);
  if (periods.length > 120) return res.status(400).json({ error: 'Слишком длинный период — выберите меньше дат или помесячно' });
  const index = new Map(periods.map((p, i) => [p.key, i]));
  const bucket = day => index.get(granularity === 'month' ? monthOf(day) : mondayOf(day));

  // только входящие звонки гостей; «с анкет» — на номера из пула анкет/рекламы
  const calls = db.prepare(`
    SELECT c.salon_id, substr(c.started_at, 1, 10) AS day,
      EXISTS (SELECT 1 FROM ad_phone_numbers an WHERE an.phone = c.dialed_number) AS is_ad
    FROM calls c WHERE c.direction = 'in' AND c.started_at >= ? AND c.started_at <= ?
  `).all(from + ' 00:00:00', till + ' 23:59:59');

  const empty = () => periods.map(() => ({ total: 0, ads: 0 }));
  const bySalon = new Map();
  const totals = empty();
  for (const c of calls) {
    const i = bucket(c.day);
    if (i === undefined) continue;
    if (!bySalon.has(c.salon_id)) bySalon.set(c.salon_id, empty());
    const cell = bySalon.get(c.salon_id)[i];
    cell.total++; totals[i].total++;
    if (c.is_ad) { cell.ads++; totals[i].ads++; }
  }
  const salons = db.prepare('SELECT id, name, active FROM salons ORDER BY name').all()
    .filter(s => s.active || bySalon.has(s.id))
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
  if (!req.query.date_from) {
    while (skip < periods.length - 1 && !totals[skip].total && spend[skip] == null) skip++;
  }
  const cut = arr => arr.slice(skip);
  res.json({
    granularity, from: periods[skip].from, till, periods: cut(periods),
    salons: salons.map(s => ({ ...s, cells: cut(s.cells) })), totals: cut(totals), spend: cut(spend)
  });
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
