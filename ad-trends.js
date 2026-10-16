// Тренд анкет: какие анкеты со временем теряют звонки и кандидаты на замену.
//
// Недели — скользящие 7-дневные окна от "сейчас" назад (а не календарные), чтобы
// последняя неделя всегда была полной и не выглядела провалом в понедельник утром.
// Падение анкеты сравнивается не с её прошлым "в лоб", а с поправкой на всю сеть:
// если на этой неделе меньше звонят во все анкеты сразу (сезон, праздники, сбой
// площадки или телефонии) — это не повод менять конкретную анкету.

const db = require('./db');
const { fetchWithTimeout } = require('./ai-processing');

const WEEKS = 8;
const BASELINE_WEEKS = 4;
const DAY_MS = 24 * 3600 * 1000;
const DROP_THRESHOLD = -0.4;
const MIN_BASELINE_CALLS = 3; // ниже — слишком мало звонков, проценты будут шумом
const FALLING_VS_NETWORK = -0.15;
const MIN_ANALYZED_FOR_CONV = 8;
const MIN_NETWORK_ANALYZED_FOR_CONV = 20;
const INSIGHT_EVERY_DAYS = 7;

function tzOffset() {
  return db.prepare('SELECT uis_timezone_offset_hours FROM telephony_settings WHERE id = 1').get().uis_timezone_offset_hours || 0;
}
const toStr = d => d.toISOString().slice(0, 19).replace('T', ' ');

function weekWindows() {
  const localNow = Date.now() + tzOffset() * 3600000;
  const windows = [];
  for (let i = WEEKS - 1; i >= 0; i--) {
    const from = new Date(localNow - (i + 1) * 7 * DAY_MS);
    const till = new Date(localNow - i * 7 * DAY_MS);
    windows.push({
      from: toStr(from), till: toStr(till),
      label: `${from.toISOString().slice(8, 10)}.${from.toISOString().slice(5, 7)}–${till.toISOString().slice(8, 10)}.${till.toISOString().slice(5, 7)}`
    });
  }
  return windows;
}

const sum = arr => arr.reduce((a, b) => a + b, 0);
const mean = arr => arr.length ? sum(arr) / arr.length : null;

function computeAdTrends() {
  const windows = weekWindows();
  const numbers = db.prepare('SELECT * FROM ad_phone_numbers ORDER BY label, phone').all();
  const stmt = db.prepare(`
    SELECT an.id AS ad_id, COUNT(c.id) AS calls,
      SUM(CASE WHEN c.outcome = 'booking' THEN 1 ELSE 0 END) AS bookings,
      SUM(CASE WHEN c.status = 'done' THEN 1 ELSE 0 END) AS analyzed
    FROM ad_phone_numbers an
    JOIN calls c ON c.dialed_number = an.phone AND c.started_at >= ? AND c.started_at < ?
    GROUP BY an.id
  `);
  const perWindow = windows.map(w => new Map(stmt.all(w.from, w.till).map(r => [r.ad_id, r])));

  const last = WEEKS - 1;
  const baseIdx = Array.from({ length: BASELINE_WEEKS }, (_, k) => last - BASELINE_WEEKS + k);
  const convIdx = Array.from({ length: BASELINE_WEEKS }, (_, k) => last - BASELINE_WEEKS + 1 + k);

  const rows = numbers.map(n => {
    // окно до даты размещения анкеты не считаем вовсе (null), а не нулём
    const valid = windows.map(w => !n.placed_at || n.placed_at <= w.from.slice(0, 10));
    const pick = field => perWindow.map((m, i) => valid[i] ? (m.get(n.id)?.[field] || 0) : null);
    const counts = pick('calls'), bookings = pick('bookings'), analyzed = pick('analyzed');
    const baseValues = baseIdx.map(i => counts[i]).filter(v => v !== null);
    const convB = sum(convIdx.map(i => bookings[i] ?? 0));
    const convA = sum(convIdx.map(i => analyzed[i] ?? 0));
    return {
      id: n.id, label: n.label, phone: n.phone, note: n.note, placed_at: n.placed_at,
      counts, last: counts[last], baseline: baseValues.length >= 2 ? mean(baseValues) : null,
      stable: baseIdx.every(i => valid[i]),
      validWeeks: valid.filter(Boolean).length,
      bookings4w: convB, analyzed4w: convA, conv: convA ? convB / convA : null
    };
  });

  // поправка на сеть — только по анкетам, у которых есть и база, и последняя неделя
  const stableRows = rows.filter(r => r.stable && r.baseline !== null && r.last !== null);
  const netLast = sum(stableRows.map(r => r.last));
  const netBase = sum(stableRows.map(r => r.baseline));
  const networkRatio = netBase > 0 ? netLast / netBase : 1;
  const netB = sum(rows.map(r => r.bookings4w)), netA = sum(rows.map(r => r.analyzed4w));
  const networkConv = netA >= MIN_NETWORK_ANALYZED_FOR_CONV ? netB / netA : null;

  for (const r of rows) {
    r.rawChange = r.baseline ? r.last / r.baseline - 1 : null;
    const expected = r.baseline !== null ? r.baseline * networkRatio : null;
    r.expected = expected;
    r.adjChange = expected ? r.last / expected - 1 : null;
    r.flags = [];

    if (r.validWeeks < 3 || r.last === null) {
      const since = r.placed_at
        ? db.prepare('SELECT COUNT(*) AS c FROM calls WHERE dialed_number = ? AND started_at >= ?').get(r.phone, r.placed_at).c
        : null;
      r.flags.push({
        level: 'new',
        text: r.placed_at ? `мало данных — размещена ${r.placed_at.slice(8, 10)}.${r.placed_at.slice(5, 7)}, звонков с тех пор: ${since}` : 'мало данных'
      });
    } else {
      if (r.last === 0 && netLast > 0) r.flags.push({ level: 'red', text: '0 звонков за 7 дней' });
      const tail = r.counts.slice(-4);
      if (tail.every(v => v !== null) && tail[0] > tail[1] && tail[1] > tail[2] && tail[2] > tail[3]
          && r.adjChange !== null && r.adjChange <= FALLING_VS_NETWORK) {
        r.flags.push({ level: 'red', text: 'падает 3 недели подряд' });
      }
      if (r.adjChange !== null && r.adjChange <= DROP_THRESHOLD && r.baseline >= MIN_BASELINE_CALLS && r.last > 0) {
        r.flags.push({ level: 'yellow', text: `${Math.round(r.adjChange * 100)}% к своему среднему (с поправкой на сеть)` });
      }
      if (networkConv !== null && r.analyzed4w >= MIN_ANALYZED_FOR_CONV && r.conv < networkConv / 2) {
        r.flags.push({ level: 'yellow', text: `мало записей: ${Math.round(r.conv * 100)}% против ${Math.round(networkConv * 100)}% по сети` });
      }
      if (r.adjChange !== null && r.adjChange >= 0.4 && r.baseline >= MIN_BASELINE_CALLS) {
        r.flags.push({ level: 'green', text: `растёт: +${Math.round(r.adjChange * 100)}%` });
      }
    }
    r.status = r.flags.some(f => f.level === 'red') ? 'red'
      : r.flags.some(f => f.level === 'yellow') ? 'yellow'
      : r.flags.some(f => f.level === 'new') ? 'new' : 'green';
  }

  const order = { red: 0, yellow: 1, new: 2, green: 3 };
  rows.sort((a, b) => order[a.status] - order[b.status] || (a.adjChange ?? 0) - (b.adjChange ?? 0) || a.label.localeCompare(b.label));

  return {
    windows,
    network: { last: netLast, baseline: netBase, ratio: networkRatio, change: networkRatio - 1, conv: networkConv },
    rows
  };
}

function latestInsight() {
  const row = db.prepare('SELECT * FROM ad_trend_insights ORDER BY id DESC LIMIT 1').get();
  if (!row) return null;
  try { return { ...JSON.parse(row.content), created_at: row.created_at }; }
  catch { return null; }
}

function trendDigest(trends) {
  const pct = v => v === null ? 'н/д' : `${v >= 0 ? '+' : ''}${Math.round(v * 100)}%`;
  const lines = trends.rows.map(r => [
    `«${r.label}» (${r.phone})`,
    `звонки по неделям от старой к новой: [${r.counts.map(v => v === null ? '—' : v).join(', ')}]`,
    `последние 7 дней: ${r.last ?? 'н/д'}`,
    `среднее за 4 предыдущие недели: ${r.baseline === null ? 'н/д' : r.baseline.toFixed(1)}`,
    `изменение с поправкой на сеть: ${pct(r.adjChange)}`,
    `записей за 4 недели: ${r.bookings4w} из ${r.analyzed4w} разобранных звонков`,
    `флаги: ${r.flags.map(f => f.text).join('; ') || 'нет'}`
  ].join(', '));
  return `Вся сеть анкет: последние 7 дней ${trends.network.last} звонков, среднее за 4 предыдущие недели ${trends.network.baseline.toFixed(1)} (${pct(trends.network.change)}), `
    + `конверсия в запись по сети ${trends.network.conv === null ? 'н/д' : Math.round(trends.network.conv * 100) + '%'}.\n\n`
    + lines.join('\n');
}

async function generateAdInsight() {
  const settings = db.prepare('SELECT * FROM ai_settings WHERE id = 1').get();
  if (!settings.openai_api_key) throw new Error('Не задан ключ OpenAI в настройках');
  const trends = computeAdTrends();
  if (!trends.rows.length) throw new Error('Список анкет пуст');

  const system = `Ты — маркетинг-аналитик сети массажных салонов и сауны. У сети много рекламных анкет на площадках, у каждой свой номер для звонков, поэтому по звонкам видно, какая анкета работает. Владелец хочет понять, какие анкеты пора заменить.
Правила:
- опирайся только на переданные цифры, ничего не придумывай;
- учитывай общий фон: если просела вся сеть, это не вина конкретной анкеты — смотри на изменение «с поправкой на сеть»;
- не предлагай менять анкеты с флагом «мало данных» и анкеты с единичными звонками, где проценты — шум;
- кроме количества звонков учитывай, сколько из них дошло до записи;
- пиши коротко и предметно, по-русски, называй анкеты по их метке.
Ответ строго JSON: {"summary": string (2-4 предложения — общая картина), "replace": [{"label": string, "reason": string}] (кого заменить в первую очередь), "watch": [{"label": string, "reason": string}] (к кому присмотреться, но менять пока рано)}.`;

  const resp = await fetchWithTimeout('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: { Authorization: `Bearer ${settings.openai_api_key}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: settings.analysis_model,
      messages: [{ role: 'system', content: system }, { role: 'user', content: trendDigest(trends) }],
      response_format: { type: 'json_object' }
    })
  }, 120_000);
  const json = await resp.json();
  if (!resp.ok) throw new Error(`OpenAI: ${json.error?.message || resp.status}`);

  let parsed;
  try { parsed = JSON.parse(json.choices?.[0]?.message?.content || '{}'); }
  catch { throw new Error('ИИ вернул невалидный ответ'); }
  const clean = list => (Array.isArray(list) ? list : [])
    .filter(x => x && x.label).map(x => ({ label: String(x.label), reason: String(x.reason || '') }));
  const content = { summary: String(parsed.summary || ''), replace: clean(parsed.replace), watch: clean(parsed.watch) };

  const costUsd = ((json.usage?.prompt_tokens || 0) * 0.15 + (json.usage?.completion_tokens || 0) * 0.6) / 1_000_000;
  db.prepare('INSERT INTO ai_usage (call_id, kind, cost_usd) VALUES (NULL, ?, ?)').run('ad_insight', costUsd);
  db.prepare('INSERT INTO ad_trend_insights (content) VALUES (?)').run(JSON.stringify(content));
  return latestInsight();
}

// раз в час проверяем, не пора ли обновить еженедельный вывод ИИ
function startWeeklyInsights() {
  const tick = async () => {
    try {
      const settings = db.prepare('SELECT openai_api_key FROM ai_settings WHERE id = 1').get();
      if (!settings.openai_api_key) return;
      if (!db.prepare('SELECT 1 FROM ad_phone_numbers LIMIT 1').get()) return;
      const fresh = db.prepare(`SELECT 1 FROM ad_trend_insights WHERE created_at >= datetime('now', ?)`).get(`-${INSIGHT_EVERY_DAYS} days`);
      if (fresh) return;
      await generateAdInsight();
      console.log('[ad-trends] обновлён еженедельный вывод ИИ по анкетам');
    } catch (err) {
      console.error('[ad-trends] не удалось обновить вывод ИИ:', err.message);
    }
  };
  setTimeout(tick, 60_000);
  setInterval(tick, 3600_000);
}

module.exports = { computeAdTrends, latestInsight, generateAdInsight, startWeeklyInsights };
