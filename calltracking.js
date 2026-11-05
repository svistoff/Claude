// Раздел «Коллтрекинг» (/api/tracking/*, только владелец): сайты с
// динамическим коллтрекингом UIS и разбивка звонков по сайтам, источникам,
// кампаниям, поисковым запросам и страницам входа.

const express = require('express');
const db = require('./db');
const { normalizeDomain } = require('./telephony');

const router = express.Router();

function tzOffsetHours() {
  return db.prepare('SELECT uis_timezone_offset_hours FROM telephony_settings WHERE id = 1').get().uis_timezone_offset_hours || 0;
}

// calls.started_at хранится во времени аккаунта UIS — границы считаем так же
function rangeFromQuery(q) {
  const dateRe = /^\d{4}-\d{2}-\d{2}$/;
  if (dateRe.test(q.date_from || '') && dateRe.test(q.date_till || '')) {
    const [a, b] = q.date_from <= q.date_till ? [q.date_from, q.date_till] : [q.date_till, q.date_from];
    return { from: a + ' 00:00:00', till: b + ' 23:59:59' };
  }
  const localNow = new Date(Date.now() + tzOffsetHours() * 3600000);
  const toStr = d => d.toISOString().slice(0, 19).replace('T', ' ');
  const days = { today: 0, week: 7, month: 30 }[q.period] ?? 7;
  const from = days === 0
    ? new Date(Date.UTC(localNow.getUTCFullYear(), localNow.getUTCMonth(), localNow.getUTCDate()))
    : new Date(localNow.getTime() - days * 86400000);
  return { from: toStr(from), till: toStr(localNow) };
}

// ---------- сайты ----------
router.get('/sites', (req, res) => {
  res.json(db.prepare(`
    SELECT ts.*, s.name AS salon_name FROM tracking_sites ts
    LEFT JOIN salons s ON s.id = ts.salon_id ORDER BY ts.domain
  `).all());
});

function siteBody(body) {
  const domain = normalizeDomain(body.domain);
  if (!domain || !/^[a-zа-яё0-9.-]+\.[a-zа-яё0-9-]+$/i.test(domain)) return { error: 'Укажите домен сайта, например example.ru' };
  const salonId = body.salon_id ? Number(body.salon_id) : null;
  if (salonId && !db.prepare('SELECT 1 FROM salons WHERE id = ?').get(salonId)) return { error: 'Салон не найден' };
  return { domain, name: String(body.name || '').trim() || null, salonId, note: String(body.note || '').trim() || null };
}

router.post('/sites', (req, res) => {
  const v = siteBody(req.body || {});
  if (v.error) return res.status(400).json({ error: v.error });
  if (db.prepare('SELECT 1 FROM tracking_sites WHERE domain = ?').get(v.domain)) return res.status(400).json({ error: 'Такой сайт уже добавлен' });
  const info = db.prepare('INSERT INTO tracking_sites (domain, name, salon_id, note) VALUES (?, ?, ?, ?)').run(v.domain, v.name, v.salonId, v.note);
  res.json(db.prepare('SELECT * FROM tracking_sites WHERE id = ?').get(info.lastInsertRowid));
});

router.put('/sites/:id', (req, res) => {
  const row = db.prepare('SELECT * FROM tracking_sites WHERE id = ?').get(req.params.id);
  if (!row) return res.status(404).json({ error: 'Сайт не найден' });
  const v = siteBody({ ...row, ...req.body });
  if (v.error) return res.status(400).json({ error: v.error });
  if (db.prepare('SELECT 1 FROM tracking_sites WHERE domain = ? AND id != ?').get(v.domain, row.id)) return res.status(400).json({ error: 'Такой сайт уже добавлен' });
  db.prepare('UPDATE tracking_sites SET domain = ?, name = ?, salon_id = ?, note = ? WHERE id = ?').run(v.domain, v.name, v.salonId, v.note, row.id);
  res.json(db.prepare('SELECT * FROM tracking_sites WHERE id = ?').get(row.id));
});

router.delete('/sites/:id', (req, res) => {
  db.prepare('DELETE FROM tracking_sites WHERE id = ?').run(req.params.id);
  res.json({ ok: true });
});

// ---------- сводка ----------
// входящие звонки с добавленных сайтов за период (site — фильтр по одному сайту)
function scope(q) {
  const { from, till } = rangeFromQuery(q);
  const site = q.site ? normalizeDomain(q.site) : null;
  const where = `c.direction = 'in' AND c.started_at >= ? AND c.started_at <= ?
    AND c.tracking_site IN (SELECT domain FROM tracking_sites)${site ? ' AND c.tracking_site = ?' : ''}`;
  return { from, till, where, params: site ? [from, till, site] : [from, till] };
}

const METRICS = `
  COUNT(*) AS calls,
  SUM(CASE WHEN c.is_answered = 1 THEN 1 ELSE 0 END) AS answered,
  SUM(CASE WHEN c.is_answered = 0 THEN 1 ELSE 0 END) AS missed,
  SUM(CASE WHEN c.is_answered = 0 AND c.callback_status IN ('on_time', 'late') THEN 1 ELSE 0 END) AS called_back,
  SUM(CASE WHEN c.status = 'done' AND c.outcome = 'booking' THEN 1 ELSE 0 END) AS bookings,
  SUM(CASE WHEN c.status = 'done' THEN 1 ELSE 0 END) AS analyzed`;

function groupBy(sc, expr, limit = 30) {
  return db.prepare(`
    SELECT COALESCE(NULLIF(TRIM(${expr}), ''), '—') AS label, ${METRICS}
    FROM calls c WHERE ${sc.where}
    GROUP BY 1 ORDER BY calls DESC LIMIT ${limit}
  `).all(...sc.params);
}

const J = key => `json_extract(c.tracking, '$.${key}')`;

router.get('/overview', (req, res) => {
  const sc = scope(req.query);
  const totals = db.prepare(`SELECT ${METRICS} FROM calls c WHERE ${sc.where}`).get(...sc.params);
  const sites = db.prepare(`
    SELECT ts.id, ts.domain, ts.name, s.name AS salon_name, ${METRICS.replace(/COUNT\(\*\)/, 'COUNT(c.id)')}
    FROM tracking_sites ts
    LEFT JOIN salons s ON s.id = ts.salon_id
    LEFT JOIN calls c ON c.tracking_site = ts.domain AND c.direction = 'in' AND c.started_at >= ? AND c.started_at <= ?
    ${req.query.site ? 'WHERE ts.domain = ?' : ''}
    GROUP BY ts.id ORDER BY calls DESC, ts.domain
  `).all(sc.from, sc.till, ...(req.query.site ? [normalizeDomain(req.query.site)] : []));
  // домены, с которых приходили звонки, но которые ещё не добавлены в список
  const unknownSites = db.prepare(`
    SELECT c.tracking_site AS domain, COUNT(*) AS calls FROM calls c
    WHERE c.direction = 'in' AND c.started_at >= ? AND c.started_at <= ?
      AND c.tracking_site IS NOT NULL AND c.tracking_site NOT IN (SELECT domain FROM tracking_sites)
    GROUP BY c.tracking_site ORDER BY calls DESC LIMIT 20
  `).all(sc.from, sc.till);
  res.json({
    from: sc.from, till: sc.till, totals, sites, unknown_sites: unknownSites,
    sources: groupBy(sc, `COALESCE(${J('source')}, '') || CASE WHEN ${J('channel')} IS NOT NULL THEN ' / ' || ${J('channel')} ELSE '' END`),
    campaigns: groupBy(sc, `COALESCE(${J('campaign_name')}, ${J('utm_campaign')})`),
    utm: groupBy(sc, `COALESCE(${J('utm_source')}, '') || CASE WHEN ${J('utm_medium')} IS NOT NULL THEN ' / ' || ${J('utm_medium')} ELSE '' END`),
    queries: groupBy(sc, `COALESCE(${J('search_query')}, ${J('utm_term')})`),
    pages: groupBy(sc, J('entrance_page')),
    visitors: groupBy(sc, J('visitor_type'), 5)
  });
});

router.get('/calls', (req, res) => {
  const sc = scope(req.query);
  const rows = db.prepare(`
    SELECT c.id, c.started_at, c.caller_phone, c.is_answered, c.callback_status, c.status, c.outcome,
      c.tracking_site, c.tracking, s.name AS salon_name, cl.name AS client_name
    FROM calls c JOIN salons s ON s.id = c.salon_id
    LEFT JOIN clients cl ON cl.id = c.client_id
    WHERE ${sc.where} ORDER BY c.started_at DESC LIMIT 1000
  `).all(...sc.params);
  res.json(rows.map(r => ({ ...r, tracking: r.tracking ? JSON.parse(r.tracking) : null })));
});

module.exports = router;
