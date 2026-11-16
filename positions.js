// «Позиции» (/api/positions, только владелец): позиции сайтов в Яндексе
// из posmon (отдельное Python-приложение на том же сервере, stat.xmassage.vip).
//
// CRM каждые 30 минут забирает с posmon (http://127.0.0.1:8600/api/export —
// отдаётся только локальным запросам) проекты, сайты, запросы, профили и
// историю позиций и хранит у себя копию в таблицах pm_*. Удалённое в posmon
// здесь не стирается, а помечается deleted=1 — история сохраняется.

const express = require('express');
const http = require('http');
const https = require('https');
const db = require('./db');

const router = express.Router();
const POSMON_URL = (process.env.POSMON_URL || 'http://127.0.0.1:8600').replace(/\/+$/, '');
const SYNC_EVERY_MS = 30 * 60 * 1000;
const DAY = 86400000;

db.exec(`
CREATE TABLE IF NOT EXISTS pm_projects (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT,
  active INTEGER NOT NULL DEFAULT 1, depth INTEGER, created_at TEXT,
  deleted INTEGER NOT NULL DEFAULT 0, synced_at TEXT
);
CREATE TABLE IF NOT EXISTS pm_sites (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, name TEXT NOT NULL, url TEXT,
  domain TEXT NOT NULL, match_mode TEXT, active INTEGER NOT NULL DEFAULT 1, comment TEXT,
  created_at TEXT, deleted INTEGER NOT NULL DEFAULT 0, synced_at TEXT
);
CREATE TABLE IF NOT EXISTS pm_queries (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, query TEXT NOT NULL, group_name TEXT,
  priority TEXT, active INTEGER NOT NULL DEFAULT 1, is_local INTEGER NOT NULL DEFAULT 0, comment TEXT,
  created_at TEXT, deleted INTEGER NOT NULL DEFAULT 0, synced_at TEXT
);
CREATE TABLE IF NOT EXISTS pm_profiles (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, name TEXT NOT NULL, type TEXT, region TEXT,
  device TEXT, source TEXT, active INTEGER NOT NULL DEFAULT 1, last_checked_at TEXT,
  deleted INTEGER NOT NULL DEFAULT 0, synced_at TEXT
);
CREATE TABLE IF NOT EXISTS pm_history (
  query_id INTEGER NOT NULL, site_id INTEGER NOT NULL, profile_id INTEGER NOT NULL,
  date TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'seo', project_id INTEGER NOT NULL,
  position INTEGER, business_position INTEGER, visual_position INTEGER, ads_above INTEGER, status TEXT,
  PRIMARY KEY (query_id, site_id, profile_id, date, mode)
);
CREATE INDEX IF NOT EXISTS idx_pm_history_proj ON pm_history(project_id, profile_id, mode, date);
CREATE TABLE IF NOT EXISTS pm_sync (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  last_attempt_at TEXT, last_ok_at TEXT, last_error TEXT, base_url TEXT
);
INSERT OR IGNORE INTO pm_sync (id) VALUES (1);
`);

const esc = v => String(v ?? '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
const iso = t => new Date(t).toISOString().slice(0, 10);
const parse = d => Date.parse(d + 'T00:00:00Z');
const bool = v => (v ? 1 : 0);
const now = () => new Date().toISOString().replace('T', ' ').slice(0, 19);

// ---------- синхронизация ----------
function fetchJson(url, timeoutMs = 60000) {
  return new Promise((resolve, reject) => {
    const lib = url.startsWith('https:') ? https : http;
    const req = lib.get(url, { timeout: timeoutMs }, res => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', c => { body += c; });
      res.on('end', () => {
        if (res.statusCode !== 200) return reject(new Error(`posmon ответил ${res.statusCode}`));
        try { resolve(JSON.parse(body)); } catch (e) { reject(new Error('posmon вернул не JSON')); }
      });
    });
    req.on('timeout', () => req.destroy(new Error('posmon не ответил вовремя')));
    req.on('error', reject);
  });
}

const TABLES = {
  projects: ['pm_projects', ['id', 'name', 'description', 'active', 'depth', 'created_at']],
  sites: ['pm_sites', ['id', 'project_id', 'name', 'url', 'domain', 'match_mode', 'active', 'comment', 'created_at']],
  queries: ['pm_queries', ['id', 'project_id', 'query', 'group_name', 'priority', 'active', 'is_local', 'comment', 'created_at']],
  profiles: ['pm_profiles', ['id', 'project_id', 'name', 'type', 'region', 'device', 'source', 'active', 'last_checked_at']],
};
const BOOL_FIELDS = new Set(['active', 'is_local']);

function applyExport(data) {
  const stamp = now();
  const result = { projects: 0, sites: 0, queries: 0, profiles: 0, history: 0 };
  db.transaction(() => {
    for (const [key, [table, fields]] of Object.entries(TABLES)) {
      const rows = Array.isArray(data[key]) ? data[key] : [];
      const upsert = db.prepare(`INSERT INTO ${table} (${fields.join(', ')}, deleted, synced_at)
        VALUES (${fields.map(f => '@' + f).join(', ')}, 0, @synced_at)
        ON CONFLICT(id) DO UPDATE SET ${fields.filter(f => f !== 'id').map(f => `${f} = excluded.${f}`).join(', ')},
          deleted = 0, synced_at = excluded.synced_at`);
      for (const r of rows) {
        const row = { synced_at: stamp };
        for (const f of fields) row[f] = BOOL_FIELDS.has(f) ? bool(r[f]) : (r[f] ?? null);
        upsert.run(row);
      }
      result[key] = rows.length;
      // Удалённое в posmon помечаем, но не стираем. Пустой ответ при непустой
      // копии (например, posmon переехал на новую пустую базу) ничего не помечает.
      const have = db.prepare(`SELECT COUNT(*) n FROM ${table} WHERE deleted = 0`).get().n;
      if (rows.length || !have) {
        db.prepare(`UPDATE ${table} SET deleted = 1 WHERE deleted = 0 AND (synced_at IS NULL OR synced_at <> ?)`).run(stamp);
      }
    }
    const hist = Array.isArray(data.history) ? data.history : [];
    const up = db.prepare(`INSERT INTO pm_history (query_id, site_id, profile_id, date, mode, project_id,
        position, business_position, visual_position, ads_above, status)
      VALUES (@query_id, @site_id, @profile_id, @date, @mode, @project_id,
        @position, @business_position, @visual_position, @ads_above, @status)
      ON CONFLICT(query_id, site_id, profile_id, date, mode) DO UPDATE SET
        project_id = excluded.project_id, position = excluded.position,
        business_position = excluded.business_position, visual_position = excluded.visual_position,
        ads_above = excluded.ads_above, status = excluded.status`);
    for (const h of hist) {
      if (!h.date || h.query_id == null || h.site_id == null || h.profile_id == null) continue;
      up.run({
        query_id: h.query_id, site_id: h.site_id, profile_id: h.profile_id,
        date: String(h.date).slice(0, 10), mode: h.mode || 'seo', project_id: h.project_id,
        position: h.position ?? null, business_position: h.business_position ?? null,
        visual_position: h.visual_position ?? null, ads_above: h.ads_above ?? null, status: h.status ?? null,
      });
    }
    result.history = hist.length;
  })();
  return result;
}

let syncing = null;
async function syncNow() {
  if (syncing) return syncing;
  syncing = (async () => {
    db.prepare('UPDATE pm_sync SET last_attempt_at = ? WHERE id = 1').run(now());
    try {
      const last = db.prepare('SELECT MAX(date) d FROM pm_history').get().d;
      // История догружается с запасом в 3 дня (пересчёты/догоняющие прогоны).
      const since = last ? iso(parse(last) - 3 * DAY) : null;
      const data = await fetchJson(`${POSMON_URL}/api/export${since ? '?since=' + since : ''}`);
      const res = applyExport(data);
      db.prepare('UPDATE pm_sync SET last_ok_at = ?, last_error = NULL, base_url = COALESCE(?, base_url) WHERE id = 1')
        .run(now(), data.base_url || null);
      return { ok: true, ...res };
    } catch (e) {
      db.prepare('UPDATE pm_sync SET last_error = ? WHERE id = 1').run(String(e.message || e));
      console.error('[positions] синхронизация с posmon не удалась:', e.message || e);
      return { ok: false, error: String(e.message || e) };
    } finally {
      syncing = null;
    }
  })();
  return syncing;
}

function startSync() {
  setTimeout(syncNow, 15000);
  setInterval(syncNow, SYNC_EVERY_MS);
}

// ---------- расчёты ----------
function metrics(positions) {
  const found = positions.filter(p => p != null).sort((a, b) => a - b);
  const total = positions.length;
  const avg = found.length ? found.reduce((s, p) => s + p, 0) / found.length : null;
  const mid = found.length ? (found.length % 2 ? found[(found.length - 1) / 2] : (found[found.length / 2 - 1] + found[found.length / 2]) / 2) : null;
  const top = n => found.filter(p => p <= n).length;
  return {
    total, found: found.length, coverage: total ? found.length / total : 0,
    average: avg == null ? null : Math.round(avg * 10) / 10, median: mid,
    top3: top(3), top10: top(10), top20: top(20), top50: top(50),
  };
}

function listProjects() {
  return db.prepare(`SELECT p.*,
      (SELECT COUNT(*) FROM pm_sites s WHERE s.project_id = p.id AND s.deleted = 0) sites,
      (SELECT COUNT(*) FROM pm_queries q WHERE q.project_id = p.id AND q.deleted = 0) queries,
      (SELECT MAX(date) FROM pm_history h WHERE h.project_id = p.id) last_date
    FROM pm_projects p ORDER BY p.deleted, p.active DESC, p.name`).all();
}

// Ближайшая дата с данными, не позже day (или самая ранняя, если раньше нет).
function pickDate(dates, day) {
  if (!dates.length) return null;
  let best = null;
  for (const d of dates) if (d <= day) best = d;
  return best || dates[0];
}

function computeProject(projectId, q = {}) {
  const project = db.prepare('SELECT * FROM pm_projects WHERE id = ?').get(projectId);
  if (!project) return { error: 'Проект не найден' };
  const mode = q.mode === 'battle' ? 'battle' : 'seo';

  const profiles = db.prepare(`SELECT pr.id, pr.name, pr.device, pr.source, pr.active, pr.deleted,
      (SELECT MAX(date) FROM pm_history h WHERE h.profile_id = pr.id AND h.mode = ?) last_date
    FROM pm_profiles pr WHERE pr.project_id = ? ORDER BY pr.deleted, pr.active DESC, pr.id`).all(mode, projectId);
  const withData = profiles.filter(p => p.last_date);
  let profile = profiles.find(p => String(p.id) === String(q.profile));
  if (!profile) profile = withData.sort((a, b) => (b.last_date > a.last_date ? 1 : -1))[0] || profiles[0] || null;

  // У проекта, удалённого в posmon (архив), показываем его сохранённые сайты и запросы.
  const alive = project.deleted ? '' : 'AND deleted = 0';
  const sites = db.prepare(`SELECT id, name, domain, url, active FROM pm_sites
    WHERE project_id = ? ${alive} ORDER BY active DESC, id`).all(projectId);
  const queries = db.prepare(`SELECT id, query, group_name, active FROM pm_queries
    WHERE project_id = ? ${alive} AND active = 1 ORDER BY COALESCE(group_name, ''), query`).all(projectId);

  const base = { project, mode, profiles, profile, sites, queries, dates: [], start: null, end: null };
  if (!profile) return { ...base, siteStats: [], rows: [], series: { dates: [], bySite: {} } };

  const dates = db.prepare(`SELECT DISTINCT date FROM pm_history
    WHERE project_id = ? AND profile_id = ? AND mode = ? ORDER BY date`).all(projectId, profile.id, mode).map(r => r.date);
  if (!dates.length) return { ...base, siteStats: [], rows: [], series: { dates: [], bySite: {} } };

  const lastDate = dates[dates.length - 1];
  const end = pickDate(dates, q.to && /^\d{4}-\d{2}-\d{2}$/.test(q.to) ? q.to : lastDate);
  const days = Math.max(1, Math.min(366, Number(q.days) || 7));
  const fromWanted = q.from && /^\d{4}-\d{2}-\d{2}$/.test(q.from) ? q.from : iso(parse(end) - days * DAY);
  const start = pickDate(dates, fromWanted <= end ? fromWanted : end);

  const snap = db.prepare(`SELECT query_id, site_id, position, MAX(date) d FROM pm_history
    WHERE project_id = ? AND profile_id = ? AND mode = ? AND date <= ? GROUP BY query_id, site_id`);
  const toMap = rows => new Map(rows.map(r => [r.query_id + '|' + r.site_id, r.position]));
  const endMap = toMap(snap.all(projectId, profile.id, mode, end));
  const startMap = toMap(snap.all(projectId, profile.id, mode, start));

  const siteStats = sites.map(s => {
    const endPos = queries.map(qr => endMap.get(qr.id + '|' + s.id) ?? null);
    const startPos = queries.map(qr => startMap.get(qr.id + '|' + s.id) ?? null);
    return { site: s, end: metrics(endPos), start: metrics(startPos) };
  });

  const rows = queries.map(qr => ({
    query: qr,
    cells: sites.map(s => {
      const k = qr.id + '|' + s.id;
      const e = endMap.has(k) ? endMap.get(k) : undefined;
      const b = startMap.has(k) ? startMap.get(k) : undefined;
      // delta > 0 — сайт поднялся (позиция стала меньше)
      const delta = e != null && b != null ? b - e : null;
      return { end: e ?? null, start: b ?? null, delta, checked: e !== undefined,
        entered: e != null && b === null, left: e === null && b != null };
    }),
  }));

  const seriesRows = db.prepare(`SELECT site_id, date, AVG(position) avg, SUM(CASE WHEN position <= 10 THEN 1 ELSE 0 END) top10
    FROM pm_history WHERE project_id = ? AND profile_id = ? AND mode = ? AND date BETWEEN ? AND ? AND position IS NOT NULL
    GROUP BY site_id, date ORDER BY date`).all(projectId, profile.id, mode, start, end);
  const seriesDates = dates.filter(d => d >= start && d <= end);
  const bySite = {};
  for (const r of seriesRows) (bySite[r.site_id] ||= {})[r.date] = { avg: Math.round(r.avg * 10) / 10, top10: r.top10 };

  return { ...base, dates, start, end, siteStats, rows, series: { dates: seriesDates, bySite } };
}

// ---------- SVG-график средней позиции ----------
const COLORS = ['#8b5cf6', '#2a9d5c', '#e8833a', '#3b82f6', '#d33', '#0ea5a4', '#a16207', '#db2777'];
function avgChartSvg(d, { width = 760, height = 220 } = {}) {
  const dates = d.series.dates;
  const sites = d.sites.filter(s => d.series.bySite[s.id]);
  if (dates.length < 2 || !sites.length) return '';
  const vals = sites.flatMap(s => Object.values(d.series.bySite[s.id]).map(v => v.avg));
  const lo = Math.max(1, Math.floor(Math.min(...vals)) - 1), hi = Math.ceil(Math.max(...vals)) + 1;
  const L = 34, R = 10, T = 10, B = 26, w = width - L - R, h = height - T - B;
  const x = i => L + (dates.length === 1 ? w / 2 : (i / (dates.length - 1)) * w);
  const y = v => T + ((v - lo) / Math.max(1, hi - lo)) * h; // 1-е место сверху
  const ticks = [];
  const step = Math.max(1, Math.ceil((hi - lo) / 5));
  for (let v = lo; v <= hi; v += step) ticks.push(`<line x1="${L}" x2="${width - R}" y1="${y(v)}" y2="${y(v)}" stroke="#eee"/><text x="${L - 6}" y="${y(v) + 4}" font-size="10" text-anchor="end" fill="#6b7280">${v}</text>`);
  const every = Math.ceil(dates.length / 8);
  const xl = dates.map((dt, i) => (i % every === 0 || i === dates.length - 1)
    ? `<text x="${x(i)}" y="${height - 8}" font-size="10" text-anchor="middle" fill="#6b7280">${dt.slice(8, 10)}.${dt.slice(5, 7)}</text>` : '').join('');
  const lines = sites.map((s, si) => {
    const color = COLORS[si % COLORS.length];
    const pts = dates.map((dt, i) => { const v = d.series.bySite[s.id][dt]; return v ? [x(i), y(v.avg)] : null; }).filter(Boolean);
    return `<polyline fill="none" stroke="${color}" stroke-width="2" points="${pts.map(p => p.join(',')).join(' ')}"/>`
      + pts.map(p => `<circle cx="${p[0]}" cy="${p[1]}" r="2.5" fill="${color}"/>`).join('');
  }).join('');
  const legend = sites.map((s, si) => `<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px;font-size:12px"><span style="width:10px;height:10px;border-radius:2px;background:${COLORS[si % COLORS.length]}"></span>${esc(s.name)}</span>`).join('');
  return `<svg viewBox="0 0 ${width} ${height}" style="width:100%;height:auto;max-width:${width}px" role="img" aria-label="Средняя позиция по дням">${ticks.join('')}${xl}${lines}</svg><div>${legend}</div>`;
}

// ---------- API ----------
router.get('/status', (req, res) => {
  const s = db.prepare('SELECT * FROM pm_sync WHERE id = 1').get();
  const counts = {
    projects: db.prepare('SELECT COUNT(*) n FROM pm_projects WHERE deleted = 0').get().n,
    sites: db.prepare('SELECT COUNT(*) n FROM pm_sites WHERE deleted = 0').get().n,
    queries: db.prepare('SELECT COUNT(*) n FROM pm_queries WHERE deleted = 0').get().n,
    history: db.prepare('SELECT COUNT(*) n FROM pm_history').get().n,
  };
  res.json({ ...s, counts, posmon_url: s.base_url || 'https://stat.xmassage.vip' });
});

router.post('/sync', async (req, res) => {
  const r = await syncNow();
  res.status(r.ok ? 200 : 502).json(r);
});

router.get('/projects', (req, res) => res.json(listProjects()));

router.get('/projects/:id', (req, res) => {
  const d = computeProject(Number(req.params.id), req.query);
  if (d.error) return res.status(404).json(d);
  res.json({ ...d, chart_svg: avgChartSvg(d) });
});

// ---------- отчёт для печати / PDF ----------
const ruDate = d => (d ? `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(0, 4)}` : '—');
const pos = v => (v == null ? '—' : v);
const pct = v => Math.round(v * 100) + '%';
function deltaHtml(delta, cls = 'ch') {
  if (delta == null || delta === 0) return '';
  return `<span class="${cls} ${delta > 0 ? 'up' : 'down'}">${delta > 0 ? '▲' : '▼'}${Math.abs(delta)}</span>`;
}
function avgDelta(st) {
  if (st.start.average == null || st.end.average == null) return null;
  return Math.round((st.start.average - st.end.average) * 10) / 10;
}

function projectSection(d) {
  if (!d.end) {
    return `<h2>${esc(d.project.name)}</h2><p class="muted">Нет данных о позициях${d.profile ? ` для профиля «${esc(d.profile.name)}»` : ''}.</p>`;
  }
  const sitesTable = `<table><tr><th style="text-align:left">Сайт</th><th>Средняя позиция</th><th>Найдено запросов</th>
      <th>ТОП-3</th><th>ТОП-10</th><th>ТОП-20</th><th>ТОП-50</th></tr>
    ${d.siteStats.map(st => `<tr><td class="name">${esc(st.site.name)}<div class="ch">${esc(st.site.domain)}</div></td>
      <td><b>${st.end.average ?? '—'}</b>${deltaHtml(avgDelta(st))}<div class="ch">было ${st.start.average ?? '—'}</div></td>
      <td>${st.end.found} из ${st.end.total}<div class="ch">${pct(st.end.coverage)}</div></td>
      ${['top3', 'top10', 'top20', 'top50'].map(k => `<td><b>${st.end[k]}</b>${deltaHtml(st.end[k] - st.start[k])}</td>`).join('')}</tr>`).join('')}
  </table>`;
  const head = d.sites.map(s => `<th>${esc(s.name)}</th>`).join('');
  const body = d.rows.map(r => `<tr><td class="name q">${esc(r.query.query)}${r.query.group_name ? `<div class="ch">${esc(r.query.group_name)}</div>` : ''}</td>
    ${r.cells.map(c => `<td class="${c.end == null ? 'miss' : c.end <= 3 ? 'p3' : c.end <= 10 ? 'p10' : c.end <= 20 ? 'p20' : ''}">${pos(c.end)}${c.entered ? '<span class="ch up">новый</span>' : c.left ? '<span class="ch down">выпал</span>' : deltaHtml(c.delta)}</td>`).join('')}</tr>`).join('');
  const chart = avgChartSvg(d);
  return `<h2>${esc(d.project.name)}</h2>
  <div class="muted">Профиль: ${esc(d.profile.name)} · ${d.mode === 'battle' ? 'боевая выдача' : 'органика'} · сравнение ${ruDate(d.start)} → ${ruDate(d.end)}</div>
  ${sitesTable}
  ${chart ? `<h3>Средняя позиция по дням (чем ниже линия — тем выше сайт)</h3>${chart}` : ''}
  <h3>Позиции по запросам на ${ruDate(d.end)}</h3>
  <table class="qt"><tr><th style="text-align:left">Запрос</th>${head}</tr>${body}</table>`;
}

router.get('/report', (req, res) => {
  const ids = req.query.project && req.query.project !== 'all'
    ? [Number(req.query.project)]
    : listProjects().filter(p => !p.deleted && p.active).map(p => p.id);
  const sections = ids.map(id => computeProject(id, req.query)).filter(d => !d.error);
  const periodText = sections.find(s => s.end) ? `${ruDate(sections.find(s => s.end).start)} — ${ruDate(sections.find(s => s.end).end)}` : '';
  res.send(`<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Позиции сайтов в Яндексе${periodText ? ' — ' + periodText : ''}</title>
<style>
  @page { size: A4 portrait; margin: 12mm; }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; color: #1a1c1f; max-width: 1000px; margin: 20px auto; padding: 0 16px; }
  h1 { font-size: 22px; margin: 0 0 4px; } .muted { color: #6b7280; font-size: 12px; margin-bottom: 8px; }
  h2 { font-size: 17px; margin: 26px 0 6px; border-bottom: 2px solid #8b5cf6; padding-bottom: 4px; }
  h3 { font-size: 14px; margin: 18px 0 6px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { padding: 5px; border-bottom: 1px solid #eee; text-align: center; vertical-align: top; }
  th { font-size: 11px; color: #6b7280; } td.name { text-align: left; font-weight: 600; } td.q { font-weight: 400; }
  .ch { display: block; font-size: 10px; color: #6b7280; } .ch.up { color: #2a9d5c; } .ch.down { color: #d33; }
  td.p3 { background: #c8efd6; } td.p10 { background: #e3f6ea; } td.p20 { background: #f4fbf6; } td.miss { color: #aaa; }
  button { margin-top: 20px; padding: 10px 18px; font-size: 14px; cursor: pointer; }
  @media print { button { display: none; } body { margin: 0; padding: 0; } tr { break-inside: avoid; } }
</style></head><body>
<h1>Позиции сайтов в Яндексе</h1>
<div class="muted">Екатеринбург · данные мониторинга posmon · ▲ — сайт поднялся, ▼ — опустился (на сколько мест) · «—» — нет в ТОП-50</div>
${sections.length ? sections.map(projectSection).join('') : '<p>Проектов пока нет — данные из posmon ещё не загружены.</p>'}
<button onclick="window.print()">Сохранить в PDF</button>
</body></html>`);
});

module.exports = router;
module.exports.syncNow = syncNow;
module.exports.startSync = startSync;
module.exports.applyExport = applyExport;
module.exports.computeProject = computeProject;
