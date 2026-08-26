// HTML-отчёты по салону и по сотруднику — по аналогии с reports.js из исходного
// проекта: без серверного генератора PDF (чтобы не тащить Chromium/шрифты на VPS) —
// отдаём HTML-страницу с кнопкой печати в PDF, кириллица и вёрстка не зависят от
// серверных библиотек. Переиспользует тот же ключ/модель OpenAI, что и ai-processing.js.

const fetch = require('node-fetch');
const db = require('./db');

const OPENAI_BASE = 'https://api.openai.com/v1';

function periodStart(period) {
  const days = period === 'month' ? 30 : 7;
  const d = new Date(Date.now() - days * 24 * 60 * 60 * 1000);
  return d.toISOString();
}

function getAiSettings() {
  return db.prepare('SELECT * FROM ai_settings WHERE id = 1').get();
}

function computeKpi(calls) {
  const total = calls.length;
  const avgDuration = total ? Math.round(calls.reduce((s, c) => s + c.duration_sec, 0) / total) : 0;
  return { total, avgDuration };
}

function computeChecklistFunnel(calls) {
  const byText = new Map();
  for (const c of calls) {
    if (!c.checklist_results) continue;
    const items = JSON.parse(c.checklist_results);
    for (const item of items) {
      if (!byText.has(item.text)) byText.set(item.text, { total: 0, passed: 0 });
      const agg = byText.get(item.text);
      agg.total++;
      if (item.passed) agg.passed++;
    }
  }
  return Array.from(byText.entries()).map(([text, agg]) => ({
    text,
    passRate: agg.total ? Math.round((agg.passed / agg.total) * 100) : 0
  }));
}

async function generateNarrative({ calls, contextLabel }) {
  const settings = getAiSettings();
  if (!settings.openai_api_key || calls.length === 0) {
    return { strengths: '—', weaknesses: '—', recommendations: '—', conclusion: 'Недостаточно данных за период.' };
  }

  const digest = calls.slice(0, 60).map(c => `Звонок #${c.id} (${c.started_at}): ${c.summary || '(нет резюме)'}`).join('\n');

  const resp = await fetch(`${OPENAI_BASE}/chat/completions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${settings.openai_api_key}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: settings.analysis_model,
      messages: [
        {
          role: 'system',
          content: `Ты готовишь отчёт для руководителя сети массажных салонов по звонкам ${contextLabel} за период.
Отвечай строго JSON: {"strengths": string, "weaknesses": string, "recommendations": string, "conclusion": string}.
Пиши по-русски, кратко и предметно, опираясь только на переданные резюме звонков.`
        },
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

  try {
    return JSON.parse(json.choices[0].message.content);
  } catch {
    return { strengths: '—', weaknesses: '—', recommendations: '—', conclusion: 'Не удалось разобрать ответ ИИ.' };
  }
}

function layout({ title, kpi, funnel, narrative, calls, subtitleRows }) {
  const row = (label, value) => `<tr><td>${label}</td><td><b>${value}</b></td></tr>`;
  const funnelRows = funnel.map(f => `
    <tr><td>${escapeHtml(f.text)}</td><td>
      <div class="bar"><div class="bar-fill" style="width:${f.passRate}%"></div></div>
      ${f.passRate}%
    </td></tr>`).join('');

  const callRows = calls.slice(0, 100).map(c => `
    <tr>
      <td>${c.started_at}</td>
      <td>${escapeHtml(c.salon_name || '')}</td>
      <td>${escapeHtml(c.matched_user_name || c.detected_staff_name || '—')}</td>
      <td>${c.duration_sec}s</td>
      <td>${escapeHtml(c.summary || '')}</td>
    </tr>`).join('');

  return `<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>${escapeHtml(title)}</title>
<style>
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; max-width: 900px; margin: 24px auto; color: #1a1a1a; }
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
  <h1>${escapeHtml(title)}</h1>
  <p>${subtitleRows}</p>

  <h2>KPI</h2>
  <div class="kpi">
    <div>Звонков<br><b>${kpi.total}</b></div>
    <div>Средняя длительность<br><b>${kpi.avgDuration}s</b></div>
  </div>

  <h2>Чек-лист (доля выполненных пунктов)</h2>
  <table>${funnelRows || '<tr><td>Нет данных</td></tr>'}</table>

  <h2>Сильные стороны</h2><p>${escapeHtml(narrative.strengths)}</p>
  <h2>Слабые места</h2><p>${escapeHtml(narrative.weaknesses)}</p>
  <h2>Рекомендации</h2><p>${escapeHtml(narrative.recommendations)}</p>
  <h2>Вывод для руководителя</h2><p>${escapeHtml(narrative.conclusion)}</p>

  <h2>Звонки за период</h2>
  <table>
    <tr><th>Дата</th><th>Салон</th><th>Сотрудник</th><th>Длительность</th><th>Резюме</th></tr>
    ${callRows || '<tr><td colspan="5">Нет звонков за период</td></tr>'}
  </table>

  <button onclick="window.print()">Сохранить в PDF</button>
</body></html>`;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
}

async function renderSalonReport(salonId, period) {
  const salon = db.prepare('SELECT * FROM salons WHERE id = ?').get(salonId);
  if (!salon) throw new Error('Салон не найден');

  const calls = db.prepare(`
    SELECT c.*, s.name AS salon_name, u.full_name AS matched_user_name
    FROM calls c JOIN salons s ON s.id = c.salon_id
    LEFT JOIN users u ON u.id = c.matched_user_id
    WHERE c.salon_id = ? AND c.status = 'done' AND c.started_at >= ?
    ORDER BY c.started_at DESC
  `).all(salonId, periodStart(period));

  const kpi = computeKpi(calls);
  const funnel = computeChecklistFunnel(calls);
  const narrative = await generateNarrative({ calls, contextLabel: `по салону «${salon.name}»` });

  return layout({
    title: `Отчёт по салону «${salon.name}»`,
    subtitleRows: `Период: ${period === 'month' ? 'месяц' : 'неделя'} · Телефон: ${escapeHtml(salon.phone)}`,
    kpi, funnel, narrative, calls
  });
}

async function renderStaffReport(userId, period) {
  const user = db.prepare('SELECT * FROM users WHERE id = ?').get(userId);
  if (!user) throw new Error('Сотрудник не найден');

  const calls = db.prepare(`
    SELECT c.*, s.name AS salon_name, u.full_name AS matched_user_name
    FROM calls c JOIN salons s ON s.id = c.salon_id
    LEFT JOIN users u ON u.id = c.matched_user_id
    WHERE c.matched_user_id = ? AND c.status = 'done' AND c.started_at >= ?
    ORDER BY c.started_at DESC
  `).all(userId, periodStart(period));

  const kpi = computeKpi(calls);
  const funnel = computeChecklistFunnel(calls);
  const narrative = await generateNarrative({ calls, contextLabel: `сотрудника ${user.full_name}` });

  return layout({
    title: `Отчёт по сотруднику: ${user.full_name}`,
    subtitleRows: `Период: ${period === 'month' ? 'месяц' : 'неделя'}`,
    kpi, funnel, narrative, calls
  });
}

module.exports = { renderSalonReport, renderStaffReport };
