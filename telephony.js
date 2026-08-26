// Приём звонков из UIS (Data API, get.calls_report) — по одному номеру на салон.
// Логика 1:1 повторяет telephony.js из исходного проекта ЕКБ ГИД: опрос по расписанию,
// сопоставление номера линии/виртуального номера с сущностью в CRM (там — с контрагентом,
// здесь — номер УЖЕ и есть салон), запись звонков в базу, аудио не сохраняется физически —
// только временная ссылка на запись в UIS для этапа расшифровки.

const fetch = require('node-fetch');
const db = require('./db');

const DATA_API_URL = 'https://dataapi.uiscom.ru/v2.0';

let pollTimer = null;

function getSettings() {
  return db.prepare('SELECT * FROM telephony_settings WHERE id = 1').get();
}

async function uisRequest(method, params) {
  const settings = getSettings();
  const body = {
    jsonrpc: '2.0',
    id: Date.now(),
    method,
    params: {
      access_token: settings.uis_api_key,
      ...params
    }
  };
  const resp = await fetch(DATA_API_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const json = await resp.json();
  if (json.error) throw new Error(`UIS API error: ${json.error.message || JSON.stringify(json.error)}`);
  return json.result;
}

// Забираем звонки за последние N минут по номеру конкретного салона.
async function fetchCallsForSalon(salon, sinceIso) {
  const result = await uisRequest('get.calls_report', {
    date_from: sinceIso,
    date_till: new Date().toISOString(),
    filter: {
      // Если у салона указан uis_line_id — фильтруем по нему точнее, иначе по номеру.
      virtual_phone_number: salon.uis_line_id || salon.phone
    },
    fields: [
      'id', 'call_session_id', 'start_time', 'finish_time', 'direction',
      'is_lost', 'talk_duration', 'contact_phone_number', 'virtual_phone_number',
      'record_url'
    ]
  });
  return (result && result.data) || [];
}

async function pollOnce() {
  const settings = getSettings();
  if (!settings.enabled || !settings.uis_api_key) return;

  const salons = db.prepare('SELECT * FROM salons WHERE active = 1').all();
  const since = settings.last_poll_at || new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

  for (const salon of salons) {
    try {
      const calls = await fetchCallsForSalon(salon, since);
      for (const c of calls) {
        saveCall(salon, c);
      }
    } catch (err) {
      console.error(`[telephony] Ошибка получения звонков для салона "${salon.name}":`, err.message);
    }
  }

  db.prepare('UPDATE telephony_settings SET last_poll_at = ? WHERE id = 1').run(new Date().toISOString());
}

function saveCall(salon, c) {
  const uisCallId = String(c.call_session_id || c.id);
  const exists = db.prepare('SELECT id FROM calls WHERE uis_call_id = ?').get(uisCallId);
  if (exists) return;

  const isAnswered = !c.is_lost && Number(c.talk_duration) > 0;
  const info = db.prepare(`
    INSERT INTO calls (salon_id, uis_call_id, direction, caller_phone, started_at, duration_sec, is_answered, recording_url, status)
    VALUES (?, ?, 'in', ?, ?, ?, ?, ?, ?)
  `).run(
    salon.id,
    uisCallId,
    c.contact_phone_number || null,
    c.start_time || new Date().toISOString(),
    Number(c.talk_duration) || 0,
    isAnswered ? 1 : 0,
    c.record_url || null,
    isAnswered ? 'new' : 'skipped'
  );

  if (isAnswered) {
    const { processCall } = require('./ai-processing');
    processCall(info.lastInsertRowid).catch(err => {
      console.error(`[telephony] Ошибка ИИ-обработки звонка #${info.lastInsertRowid}:`, err.message);
    });
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  const tick = async () => {
    try {
      await pollOnce();
    } catch (err) {
      console.error('[telephony] Ошибка опроса UIS:', err.message);
    } finally {
      const settings = getSettings();
      pollTimer = setTimeout(tick, Math.max(60, settings.poll_interval_sec || 300) * 1000);
    }
  };
  tick();
}

module.exports = { startPolling, pollOnce };
