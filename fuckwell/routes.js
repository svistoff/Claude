// API раздела «Fuckwell» (/api/fw/*, только владелец).

const express = require('express');
const multer = require('multer');
const XLSX = require('xlsx');
const db = require('../db');
const {
  normalizePhone, phoneKey, lineRole, realClientPhone, resolveCall, ROLE_LABELS, SALONS, syncKnownNumbers,
  getSettings, excludedKeys, toLocal, resolvePeriod, daysBetween, safeTz
} = require('./util');
const { enqueueAnalysis } = require('./ai');
const { relinkAllCalls } = require('./webhook');

const router = express.Router();
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 30 * 1024 * 1024 } });

const tz = () => safeTz(getSettings().display_tz);
const MOMENT = 'COALESCE(c.started_at, c.created_at)';

// прямые номера салонов в рекламе не указываются — только принимают переадресацию
// с анкет, поэтому звонки, набранные прямо на них, не входят ни в статистику, ни в список
const NOT_SALON_LINE = ` AND (c.number_id IS NULL OR c.number_id NOT IN (SELECT id FROM fw_numbers WHERE kind = 'salon'))`;

// плюс звонки с исключённых номеров клиентов (тестовые прозвоны) в статистику не идут
function excludedClause() {
  const keys = [...excludedKeys()];
  if (!keys.length) return { sql: NOT_SALON_LINE, params: [] };
  return { sql: `${NOT_SALON_LINE} AND (c.client_phone IS NULL OR substr(c.client_phone, -10) NOT IN (${keys.map(() => '?').join(',')}))`, params: keys };
}

function periodFromQuery(q, defaultDays) {
  return resolvePeriod(q.date_from, q.date_to, tz(), defaultDays);
}

function formatCallRow(c, zone) {
  const signals = c.signals ? (() => { try { return JSON.parse(c.signals); } catch { return null; } })() : null;
  const role = lineRole(c.client_phone);
  return {
    id: c.id, call_id: c.call_id, number_id: c.number_id, number_name: c.number_name, number_phone: c.number_phone,
    number_salon: c.number_salon, number_kind: c.number_kind,
    client_phone: c.client_phone, client_real_phone: realClientPhone(c.client_phone), line: role ? ROLE_LABELS[role] : null,
    diversion: c.diversion, telnum_name: c.telnum_name, direction: c.direction, status: c.status,
    duration: c.duration, wait: c.wait, recording_url: c.recording_url,
    time_local: toLocal(c.started_at || c.created_at, zone), started_known: !!c.started_at,
    analysis: c.a_status ? {
      status: c.a_status, visit_probability: c.visit_probability, ai_comment: c.ai_comment,
      signals, error: c.a_error, analyzed_at: toLocal(c.analyzed_at, zone)
    } : null
  };
}

const CALL_SELECT = `
  SELECT c.*, n.name AS number_name, n.phone AS number_phone, n.salon AS number_salon, n.kind AS number_kind,
    a.status AS a_status, a.visit_probability, a.ai_comment, a.signals, a.error AS a_error, a.analyzed_at
  FROM fw_calls c
  LEFT JOIN fw_numbers n ON n.id = c.number_id
  LEFT JOIN fw_analyses a ON a.call_id = c.call_id`;

function computeStats(p) {
  const ex = excludedClause();
  const where = `${MOMENT} >= ? AND ${MOMENT} <= ?${ex.sql}`;
  const params = [p.utcFrom, p.utcTo, ...ex.params];
  const totals = db.prepare(`
    SELECT COUNT(*) AS total,
      SUM(CASE WHEN lower(c.status) = 'success' THEN 1 ELSE 0 END) AS accepted,
      SUM(CASE WHEN lower(c.status) = 'missed' THEN 1 ELSE 0 END) AS missed,
      AVG(CASE WHEN lower(c.status) = 'success' THEN c.duration END) AS avg_dur
    FROM fw_calls c WHERE ${where}
  `).get(...params);
  const numbers = db.prepare(`
    SELECT n.id, n.name, n.phone, n.comment, n.active, n.salon, n.kind, COUNT(c.id) AS total,
      COALESCE(SUM(CASE WHEN lower(c.status) = 'success' THEN 1 ELSE 0 END), 0) AS accepted,
      COALESCE(SUM(CASE WHEN lower(c.status) = 'missed' THEN 1 ELSE 0 END), 0) AS missed
    FROM fw_numbers n LEFT JOIN fw_calls c ON c.number_id = n.id AND ${where}
    WHERE n.kind != 'salon'
    GROUP BY n.id ORDER BY total DESC, n.name
  `).all(...params);
  // по салонам: входящие на анкеты салона, исходящие отдельно
  const IN = `COALESCE(c.direction, 'in') != 'out'`;
  const salonRows = db.prepare(`
    SELECT COALESCE(n.salon, 'Салон не определён') AS salon,
      SUM(CASE WHEN ${IN} THEN 1 ELSE 0 END) AS incoming,
      SUM(CASE WHEN ${IN} AND lower(c.status) = 'success' THEN 1 ELSE 0 END) AS accepted,
      SUM(CASE WHEN ${IN} AND lower(c.status) = 'missed' THEN 1 ELSE 0 END) AS missed,
      SUM(CASE WHEN c.direction = 'out' THEN 1 ELSE 0 END) AS outgoing
    FROM fw_calls c LEFT JOIN fw_numbers n ON n.id = c.number_id
    WHERE ${where} GROUP BY 1
  `).all(...params);
  const salonMap = new Map(salonRows.map(r => [r.salon, r]));
  const salons = [...SALONS, ...salonRows.map(r => r.salon).filter(x => !SALONS.includes(x))].map(salon =>
    salonMap.get(salon) || { salon, incoming: 0, accepted: 0, missed: 0, outgoing: 0 });
  const ai = db.prepare(`
    SELECT COUNT(*) AS cnt, AVG(a.visit_probability) AS avg_prob
    FROM fw_analyses a JOIN fw_calls c ON c.call_id = a.call_id
    WHERE a.status = 'done' AND ${where}
  `).get(...params);
  return {
    date_from: p.from, date_to: p.to,
    total: totals.total || 0, accepted: totals.accepted || 0, missed: totals.missed || 0,
    avg_duration_sec: Math.round(totals.avg_dur || 0),
    numbers, salons, ai_analyzed: ai.cnt || 0,
    ai_avg_probability: ai.avg_prob == null ? null : Math.round(ai.avg_prob * 10) / 10
  };
}

router.get('/stats', (req, res) => res.json(computeStats(periodFromQuery(req.query, 30))));

router.get('/calls', (req, res) => {
  const p = periodFromQuery(req.query, 30);
  const limit = Math.min(1000, Math.max(1, Number(req.query.limit) || 300));
  const zone = tz();
  const rows = db.prepare(`${CALL_SELECT} WHERE ${MOMENT} >= ? AND ${MOMENT} <= ?${NOT_SALON_LINE} ORDER BY ${MOMENT} DESC LIMIT ?`)
    .all(p.utcFrom, p.utcTo, limit);
  res.json({ date_from: p.from, date_to: p.to, calls: rows.map(r => formatCallRow(r, zone)) });
});

router.post('/calls/:callId/reanalyze', (req, res) => {
  const a = db.prepare('SELECT status FROM fw_analyses WHERE call_id = ?').get(req.params.callId);
  if (!db.prepare('SELECT 1 FROM fw_calls WHERE call_id = ?').get(req.params.callId)) return res.status(404).json({ error: 'Звонок не найден' });
  if (a) db.prepare(`UPDATE fw_analyses SET status = 'pending', error = NULL WHERE call_id = ?`).run(req.params.callId);
  enqueueAnalysis(req.params.callId);
  res.json({ ok: true });
});

// матрица «анкета × день» в часовом поясе отображения
router.get('/anketa-daily', (req, res) => {
  const p = periodFromQuery(req.query, 14);
  const zone = tz();
  const ex = excludedClause();
  const calls = db.prepare(`
    SELECT c.number_id, c.status, ${MOMENT} AS moment FROM fw_calls c
    WHERE c.number_id IS NOT NULL AND ${MOMENT} >= ? AND ${MOMENT} <= ?${ex.sql}
  `).all(p.utcFrom, p.utcTo, ...ex.params);
  const days = daysBetween(p.from, p.to);
  // прямые номера салонов — не анкеты, их звонки видны в разбивке по салонам
  const byId = new Map(db.prepare(`SELECT * FROM fw_numbers WHERE kind = 'anketa' ORDER BY name`).all().map(n => [n.id, {
    id: n.id, name: n.name, phone: n.phone, comment: n.comment, active: !!n.active, salon: n.salon,
    by_day: Object.fromEntries(days.map(d => [d, 0])), total: 0, accepted: 0, missed: 0
  }]));
  const colTotals = Object.fromEntries(days.map(d => [d, 0]));
  for (const c of calls) {
    const row = byId.get(c.number_id);
    if (!row) continue;
    const day = toLocal(c.moment, zone).slice(0, 10);
    if (day in row.by_day) { row.by_day[day]++; colTotals[day]++; }
    row.total++;
    if ((c.status || '').toLowerCase() === 'success') row.accepted++;
    if ((c.status || '').toLowerCase() === 'missed') row.missed++;
  }
  const anketas = [...byId.values()].sort((a, b) => b.total - a.total || a.name.localeCompare(b.name));
  const salonTotals = new Map();
  for (const a of anketas) {
    const key = a.salon || 'Салон не определён';
    if (!salonTotals.has(key)) salonTotals.set(key, { salon: key, total: 0, by_day: Object.fromEntries(days.map(d => [d, 0])) });
    const st = salonTotals.get(key);
    st.total += a.total;
    for (const d of days) st.by_day[d] += a.by_day[d];
  }
  const salons = [...salonTotals.values()].sort((a, b) => (SALONS.indexOf(a.salon) + 1 || 99) - (SALONS.indexOf(b.salon) + 1 || 99));
  res.json({ date_from: p.from, date_to: p.to, days, anketas, salons, col_totals: colTotals, grand_total: Object.values(colTotals).reduce((s, v) => s + v, 0) });
});

// ---------- номера ----------
router.get('/numbers', (req, res) => res.json(db.prepare('SELECT * FROM fw_numbers ORDER BY name').all()));

router.post('/numbers', (req, res) => {
  const { name, phone, comment, salon, kind } = req.body || {};
  const norm = normalizePhone(phone);
  if (!String(name || '').trim() || !norm) return res.status(400).json({ error: 'Укажите имя и корректный номер' });
  if (db.prepare('SELECT 1 FROM fw_numbers WHERE phone = ?').get(norm)) return res.status(409).json({ error: 'Такой номер уже есть' });
  const info = db.prepare('INSERT INTO fw_numbers (name, phone, comment, salon, kind) VALUES (?, ?, ?, ?, ?)')
    .run(String(name).trim(), norm, comment || null, salon || null, kind === 'salon' ? 'salon' : 'anketa');
  syncKnownNumbers();
  relinkAllCalls();
  res.json(db.prepare('SELECT * FROM fw_numbers WHERE id = ?').get(info.lastInsertRowid));
});

router.put('/numbers/:id', (req, res) => {
  const row = db.prepare('SELECT * FROM fw_numbers WHERE id = ?').get(req.params.id);
  if (!row) return res.status(404).json({ error: 'Номер не найден' });
  const body = req.body || {};
  let phone = row.phone;
  if (body.phone !== undefined) {
    phone = normalizePhone(body.phone);
    if (!phone) return res.status(400).json({ error: 'Некорректный номер' });
    if (db.prepare('SELECT 1 FROM fw_numbers WHERE phone = ? AND id != ?').get(phone, row.id)) return res.status(409).json({ error: 'Такой номер уже есть' });
  }
  const name = body.name !== undefined ? String(body.name).trim() : row.name;
  if (!name) return res.status(400).json({ error: 'Имя не может быть пустым' });
  db.prepare('UPDATE fw_numbers SET name = ?, phone = ?, comment = ?, active = ?, salon = ?, kind = ? WHERE id = ?').run(
    name, phone, body.comment !== undefined ? (body.comment || null) : row.comment,
    body.active !== undefined ? (body.active ? 1 : 0) : row.active,
    body.salon !== undefined ? (body.salon || null) : row.salon,
    body.kind !== undefined ? (body.kind === 'salon' ? 'salon' : 'anketa') : row.kind, row.id
  );
  if (phone !== row.phone) relinkAllCalls();
  res.json(db.prepare('SELECT * FROM fw_numbers WHERE id = ?').get(row.id));
});

router.delete('/numbers/:id', (req, res) => {
  db.prepare('DELETE FROM fw_numbers WHERE id = ?').run(req.params.id);
  relinkAllCalls();
  res.json({ ok: true });
});

// ---------- исключённые номера ----------
router.get('/excluded', (req, res) => res.json(db.prepare('SELECT * FROM fw_excluded ORDER BY id').all()));

router.post('/excluded', (req, res) => {
  const norm = normalizePhone(req.body?.phone);
  const key = phoneKey(norm);
  if (key.length < 10) return res.status(400).json({ error: 'Некорректный номер' });
  if (db.prepare('SELECT 1 FROM fw_excluded WHERE key = ?').get(key)) return res.status(409).json({ error: 'Такой номер уже в списке' });
  const info = db.prepare('INSERT INTO fw_excluded (phone, key, comment) VALUES (?, ?, ?)').run(norm, key, req.body?.comment || null);
  res.json(db.prepare('SELECT * FROM fw_excluded WHERE id = ?').get(info.lastInsertRowid));
});

router.delete('/excluded/:id', (req, res) => {
  db.prepare('DELETE FROM fw_excluded WHERE id = ?').run(req.params.id);
  res.json({ ok: true });
});

// ---------- разбор выгрузки «История внешних звонков» (xlsx) из кабинета МегаФона ----------
// Файл разбирается в памяти и никуда не сохраняется.
const META_LABELS = new Set(['дата отчета:', 'звонки:', 'с:', 'по:']);
function classify(callType) {
  const t = String(callType || '').trim().toLowerCase();
  if (t.includes('пропущ')) return 'missed';
  if (t.includes('исход')) return 'outgoing';
  return 'incoming';
}

router.post('/analysis/upload', upload.single('file'), (req, res) => {
  if (!req.file || !/\.xlsx?m?$/i.test(req.file.originalname || '')) {
    return res.status(400).json({ error: 'Нужен файл .xlsx (выгрузка «История внешних звонков» из кабинета МегаФон)' });
  }
  let rows;
  try {
    const wb = XLSX.read(req.file.buffer, { type: 'buffer' });
    rows = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { header: 1, defval: null, raw: false });
  } catch {
    return res.status(400).json({ error: 'Не удалось прочитать файл — точно xlsx из кабинета МегаФон?' });
  }

  const meta = {};
  let headerIdx = -1, cols = {};
  for (let i = 0; i < Math.min(rows.length, 30) && headerIdx === -1; i++) {
    const row = rows[i] || [];
    const first = String(row[0] ?? '').trim().toLowerCase();
    if (META_LABELS.has(first) && row[1]) meta[first.replace(/:$/, '')] = String(row[1]);
    if (row.some(v => String(v ?? '').trim().toLowerCase() === 'тип звонка')) {
      headerIdx = i;
      row.forEach((v, j) => { if (v != null) cols[String(v).trim()] = j; });
    }
  }
  if (headerIdx === -1 || !('Через' in cols) || !('Клиент' in cols) || !('Тип звонка' in cols)) {
    return res.status(400).json({ error: 'Не нашёл нужные колонки (Тип звонка / Клиент / Через) — формат файла отличается от выгрузки МегаФона' });
  }

  const excl = excludedKeys();
  const totals = { total: 0, incoming: 0, outgoing: 0, missed: 0, matched: 0, unmatched: 0 };
  const agg = new Map(), unmatched = new Map();
  let excludedCount = 0, directCount = 0;
  for (const row of rows.slice(headerIdx + 1)) {
    if (!row || row.every(v => v == null)) continue;
    const via = row[cols['Через']], client = row[cols['Клиент']];
    if (!via) continue;
    if (excl.size && excl.has(phoneKey(client))) { excludedCount++; continue; }
    const resolved = resolveCall(String(via), String(client || ''));
    if (resolved && resolved.role === -1) { directCount++; continue; }
    const kind = classify(row[cols['Тип звонка']]);
    totals.total++; totals[kind]++;
    if (!resolved) {
      const k = normalizePhone(via) || String(via);
      unmatched.set(k, (unmatched.get(k) || 0) + 1);
      totals.unmatched++;
      continue;
    }
    totals.matched++;
    const key = `${resolved.salon}|${resolved.group}|${resolved.role}`;
    if (!agg.has(key)) agg.set(key, { ...resolved, phone: resolved.number, total: 0, incoming: 0, outgoing: 0, missed: 0 });
    const b = agg.get(key);
    b.total++; b[kind]++;
  }

  const byPhone = new Map(db.prepare('SELECT * FROM fw_numbers').all().map(n => [n.phone, n]));
  const numbers = [...agg.values()].map(b => {
    const n = byPhone.get(b.phone);
    return { ...b, id: n ? n.id : null, name: n && n.name ? n.name : b.label, comment: n ? n.comment : null };
  }).sort((a, b) => b.total - a.total);
  const bySalon = new Map();
  for (const b of numbers) {
    if (!bySalon.has(b.salon)) bySalon.set(b.salon, { salon: b.salon, total: 0, incoming: 0, outgoing: 0, missed: 0 });
    const s = bySalon.get(b.salon);
    for (const k of ['total', 'incoming', 'outgoing', 'missed']) s[k] += b[k];
  }
  res.json({
    filename: req.file.originalname, period: meta, totals, numbers,
    by_salon: [...bySalon.values()].sort((a, b) => b.total - a.total),
    unmatched: [...unmatched].map(([phone, count]) => ({ phone, count })).sort((a, b) => b.count - a.count),
    excluded_calls: excludedCount, direct_salon_calls: directCount
  });
});

// ---------- печатный отчёт за период (браузер -> «Сохранить в PDF») ----------
const esc = s => String(s ?? '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
const fmtDur = s => `${String(Math.floor((s || 0) / 60)).padStart(2, '0')}:${String((s || 0) % 60).padStart(2, '0')}`;
const fmtDate = d => `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(0, 4)}`;

router.get('/report', (req, res) => {
  const p = periodFromQuery(req.query, 30);
  const s = computeStats(p);
  const zone = tz();
  const analyzed = db.prepare(`${CALL_SELECT} WHERE a.status = 'done' AND ${MOMENT} >= ? AND ${MOMENT} <= ?${NOT_SALON_LINE} ORDER BY ${MOMENT} DESC LIMIT 50`)
    .all(p.utcFrom, p.utcTo).map(r => formatCallRow(r, zone));
  const pct = s.total ? Math.round(s.accepted / s.total * 100) : 0;
  res.send(`<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Fuckwell — отчёт</title>
<style>
  body{font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:960px;margin:24px auto;color:#1d1d1f;padding:0 16px}
  h1{font-size:22px} h2{font-size:16px;margin-top:28px;border-bottom:1px solid #e5e5ea;padding-bottom:4px}
  table{width:100%;border-collapse:collapse;margin-top:8px} td,th{padding:6px 8px;border-bottom:1px solid #eee;font-size:13px;text-align:left;vertical-align:top}
  .kpi{display:flex;gap:12px;flex-wrap:wrap} .kpi div{background:#f5f5f7;border-radius:10px;padding:12px 16px;min-width:140px}
  .kpi b{font-size:22px} .muted{color:#6e6e73;font-size:12px}
  button{margin-top:24px;padding:10px 18px;font-size:14px;cursor:pointer} @media print{button{display:none}}
</style></head><body>
<h1>Fuckwell — отчёт по звонкам</h1>
<p class="muted">Период: ${fmtDate(s.date_from)} — ${fmtDate(s.date_to)}</p>
<div class="kpi">
  <div>Всего звонков<br><b>${s.total}</b></div>
  <div>Принято<br><b>${s.accepted}</b><br><span class="muted">${pct}% от всех</span></div>
  <div>Пропущено<br><b>${s.missed}</b></div>
  <div>Средний разговор<br><b>${fmtDur(s.avg_duration_sec)}</b></div>
  <div>Оценка ИИ, средняя<br><b>${s.ai_avg_probability == null ? '—' : s.ai_avg_probability + '%'}</b><br><span class="muted">разобрано ${s.ai_analyzed}</span></div>
</div>
<h2>По номерам</h2>
<table><tr><th>Номер</th><th>Всего</th><th>Принято</th><th>Пропущено</th></tr>
${s.numbers.filter(n => n.total).map(n => `<tr><td>${esc(n.name)}<br><span class="muted">${esc(n.phone)}</span></td><td>${n.total}</td><td>${n.accepted}</td><td>${n.missed}</td></tr>`).join('') || '<tr><td colspan="4">Нет звонков</td></tr>'}
</table>
<h2>Оценки ИИ (последние ${analyzed.length})</h2>
<table><tr><th>Время</th><th>Номер</th><th>Оценка</th><th>Комментарий</th></tr>
${analyzed.map(c => `<tr><td>${esc(c.time_local)}</td><td>${esc(c.number_name || c.telnum_name || '—')}</td><td>${c.analysis.visit_probability ?? '—'}%</td><td>${esc(c.analysis.ai_comment || '')}</td></tr>`).join('') || '<tr><td colspan="4">Нет разобранных звонков</td></tr>'}
</table>
<button onclick="window.print()">Сохранить в PDF</button>
</body></html>`);
});

// ---------- настройки ----------
router.get('/settings', (req, res) => {
  const s = getSettings();
  res.json({
    has_megafon_crm_token: !!s.megafon_crm_token, has_megafon_api_key: !!s.megafon_api_key, has_bridge_secret: !!s.bridge_secret,
    recording_proxy_url: s.recording_proxy_url || '', display_tz: s.display_tz, ai_min_duration_sec: s.ai_min_duration_sec
  });
});

router.put('/settings', (req, res) => {
  const b = req.body || {};
  const s = getSettings();
  const secret = (key) => (typeof b[key] === 'string' && b[key].trim()) ? b[key].trim() : s[key];
  const displayTz = b.display_tz ? safeTz(String(b.display_tz).trim()) : s.display_tz;
  const minDur = Number.isFinite(Number(b.ai_min_duration_sec)) ? Math.max(0, Math.trunc(Number(b.ai_min_duration_sec))) : s.ai_min_duration_sec;
  db.prepare(`UPDATE fw_settings SET megafon_crm_token = ?, megafon_api_key = ?, bridge_secret = ?, recording_proxy_url = ?, display_tz = ?, ai_min_duration_sec = ? WHERE id = 1`)
    .run(secret('megafon_crm_token'), secret('megafon_api_key'), secret('bridge_secret'),
      b.recording_proxy_url !== undefined ? (String(b.recording_proxy_url).trim() || null) : s.recording_proxy_url, displayTz, minDur);
  res.json({ ok: true });
});

// ---------- импорт данных из старой crm.fuckwell.ru (JSON, подготовленный из дампа PostgreSQL) ----------
// Повторный импорт безопасен: существующие номера/звонки/анализы не дублируются.
router.post('/import', upload.single('file'), (req, res) => {
  let data;
  try { data = JSON.parse(req.file.buffer.toString('utf8')); }
  catch { return res.status(400).json({ error: 'Нужен JSON-файл импорта Fuckwell' }); }
  if (!Array.isArray(data.phone_numbers) || !Array.isArray(data.calls)) return res.status(400).json({ error: 'В файле нет номеров/звонков — это не файл импорта Fuckwell' });

  const result = { numbers: 0, calls: 0, analyses: 0, excluded: 0, settings: 0 };
  db.transaction(() => {
    const idMap = new Map();
    for (const n of data.phone_numbers) {
      const phone = normalizePhone(n.phone);
      if (!phone) continue;
      const existing = db.prepare('SELECT id FROM fw_numbers WHERE phone = ?').get(phone);
      if (existing) { idMap.set(n.id, existing.id); continue; }
      const info = db.prepare(`INSERT INTO fw_numbers (name, phone, comment, active, created_at) VALUES (?, ?, ?, ?, COALESCE(?, datetime('now')))`)
        .run(n.name, phone, n.comment || null, n.active ? 1 : 0, n.created_at || null);
      idMap.set(n.id, info.lastInsertRowid);
      result.numbers++;
    }
    const insCall = db.prepare(`INSERT OR IGNORE INTO fw_calls (call_id, number_id, client_phone, diversion, telnum_name, direction, event_type, status,
      started_at, duration, wait, recording_url, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')), COALESCE(?, datetime('now')))`);
    for (const c of data.calls) {
      if (!c.call_id) continue;
      result.calls += insCall.run(c.call_id, c.phone_number_id != null ? (idMap.get(c.phone_number_id) ?? null) : null,
        c.client_phone, c.diversion, c.telnum_name, c.direction, c.event_type, c.status, c.started_at, c.duration, c.wait,
        c.recording_url, c.created_at || null, c.updated_at || null).changes;
    }
    const insAnalysis = db.prepare(`INSERT OR IGNORE INTO fw_analyses (call_id, status, visit_probability, ai_comment, signals, model, error, analyzed_at, created_at, updated_at)
      SELECT ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')), COALESCE(?, datetime('now')) WHERE EXISTS (SELECT 1 FROM fw_calls WHERE call_id = ?)`);
    for (const a of data.ai_analyses || []) {
      result.analyses += insAnalysis.run(a.call_id, a.status, a.visit_probability, a.ai_comment,
        a.signals ? JSON.stringify(a.signals) : null, a.model, a.error, a.analyzed_at, a.created_at || null, a.updated_at || null, a.call_id).changes;
    }
    for (const e of data.excluded_phones || []) {
      result.excluded += db.prepare('INSERT OR IGNORE INTO fw_excluded (phone, key, comment) VALUES (?, ?, ?)').run(e.phone, e.key, e.comment || null).changes;
    }
    // настройки из .env старой CRM — заполняем только пустые
    const s = getSettings(), incoming = data.settings || {};
    for (const key of ['megafon_crm_token', 'megafon_api_key', 'recording_proxy_url', 'bridge_secret']) {
      if (!s[key] && incoming[key]) { db.prepare(`UPDATE fw_settings SET ${key} = ? WHERE id = 1`).run(incoming[key]); result.settings++; }
    }
  })();
  syncKnownNumbers();
  relinkAllCalls();
  res.json(result);
});

module.exports = router;
