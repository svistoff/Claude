// Приём звонков UIS (Data API, get.calls_report) по номерам объектов сети,
// плюс логика пропущенных звонков и привязки перезвонов.
//
// Один опрос раз в poll_interval_sec покрывает все активные объекты (номера).
// Звонок относится к объекту по номеру: входящие — по номеру, на который
// позвонили; исходящие — по номеру, с которого звонили (т.е. по номеру самого
// объекта, который мы и опрашиваем).

const fetch = require('node-fetch');
const db = require('./db');
const { normalizePhone, findOrCreateClient } = require('./lib');

const DATA_API_URL = 'https://dataapi.uiscom.ru/v2.0';
const LOOKBACK_MS_FOR_CALLBACK_MATCH = 48 * 60 * 60 * 1000; // окно поиска пары «пропущен → перезвон»

let pollTimer = null;

function getTelephonySettings() {
  return db.prepare('SELECT * FROM telephony_settings WHERE id = 1').get();
}

async function uisRequest(method, params) {
  const settings = getTelephonySettings();
  const body = {
    jsonrpc: '2.0',
    id: Date.now(),
    method,
    params: { access_token: settings.uis_api_key, ...params }
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

// UIS ждёт даты в формате "YYYY-MM-DD HH:mm:ss" (без "T"/"Z") — это же формат,
// который отдаёт SQLite для datetime('now'), поэтому используем его везде.
function toUisDateString(date) {
  return date.toISOString().slice(0, 19).replace('T', ' ');
}

async function fetchCallsForSalon(salon, sinceStr) {
  const result = await uisRequest('get.calls_report', {
    date_from: sinceStr,
    date_till: toUisDateString(new Date()),
    filter: { field: 'virtual_phone_number', operator: '=', value: normalizePhone(salon.uis_line_id || salon.phone) },
    fields: [
      'id', 'start_time', 'direction', 'is_lost', 'talk_duration',
      'calling_phone_number', 'called_phone_number', 'virtual_phone_number', 'call_records'
    ]
  });
  return (result && result.data) || [];
}

function extractRecordUrl(c) {
  if (!Array.isArray(c.call_records) || c.call_records.length === 0) return null;
  const first = c.call_records[0];
  if (typeof first === 'string') return first;
  return first?.record_url || first?.url || null;
}

async function pollOnce() {
  const settings = getTelephonySettings();
  if (!settings.enabled || !settings.uis_api_key) return;

  const salons = db.prepare('SELECT * FROM salons WHERE active = 1').all();
  const since = settings.last_poll_at || toUisDateString(new Date(Date.now() - 24 * 60 * 60 * 1000));

  for (const salon of salons) {
    try {
      const calls = await fetchCallsForSalon(salon, since);
      // сортируем по времени начала, чтобы пропущенный всегда сохранялся раньше перезвона
      calls.sort((a, b) => new Date(a.start_time) - new Date(b.start_time));
      for (const c of calls) saveCall(salon, c);
    } catch (err) {
      console.error(`[telephony] Ошибка получения звонков для объекта "${salon.name}":`, err.message);
    }
  }

  sweepExpiredCallbackWindows(settings.callback_window_min);
  db.prepare(`UPDATE telephony_settings SET last_poll_at = ? WHERE id = 1`).run(toUisDateString(new Date()));
}

function saveCall(salon, c) {
  const uisCallId = String(c.id);
  if (db.prepare('SELECT id FROM calls WHERE uis_call_id = ?').get(uisCallId)) return;

  const direction = c.direction === 'out' ? 'out' : 'in';
  const isLost = c.is_lost === true || c.is_lost === 1 || c.is_lost === '1';
  const isAnswered = !isLost && Number(c.talk_duration) > 0;
  const callerPhone = (direction === 'in' ? c.calling_phone_number : c.called_phone_number) || null;
  const clientId = callerPhone ? findOrCreateClient(callerPhone) : null;

  let status;
  if (direction === 'in') status = isAnswered ? 'new' : 'missed';
  else status = isAnswered ? 'new' : 'skipped';

  const info = db.prepare(`
    INSERT INTO calls (salon_id, client_id, uis_call_id, direction, caller_phone, started_at, duration_sec, is_answered, recording_url, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    salon.id, clientId, uisCallId, direction, callerPhone,
    c.start_time || toUisDateString(new Date()), Number(c.talk_duration) || 0,
    isAnswered ? 1 : 0, extractRecordUrl(c), status
  );
  const callId = info.lastInsertRowid;

  if (direction === 'out') {
    linkCallbackIfMatches(salon, callId, callerPhone, c.start_time);
  }

  if (status === 'new') {
    const { processCall } = require('./ai-processing');
    processCall(callId).catch(err => console.error(`[telephony] Ошибка ИИ-обработки звонка #${callId}:`, err.message));
  }
}

// Ищем недавний неотвеченный входящий на этот объект с этого же номера клиента,
// ещё не связанный с перезвоном, и связываем его с этим исходящим звонком.
function linkCallbackIfMatches(salon, outCallId, callerPhone, outStartTime) {
  const norm = normalizePhone(callerPhone);
  if (!norm) return;

  const since = toUisDateString(new Date(new Date(outStartTime).getTime() - LOOKBACK_MS_FOR_CALLBACK_MATCH));
  const missed = db.prepare(`
    SELECT c.* FROM calls c
    WHERE c.salon_id = ? AND c.direction = 'in' AND c.is_answered = 0
      AND c.callback_call_id IS NULL AND c.started_at >= ? AND c.started_at <= ?
    ORDER BY c.started_at DESC LIMIT 1
  `).all(salon.id, since, outStartTime).find(m => normalizePhone(m.caller_phone) === norm);

  if (!missed) return;

  const minutes = Math.max(0, Math.round((new Date(outStartTime) - new Date(missed.started_at)) / 60000));
  const settings = getTelephonySettings();
  const callbackStatus = minutes <= settings.callback_window_min ? 'on_time' : 'late';

  db.prepare('UPDATE calls SET callback_call_id = ?, callback_status = ?, callback_minutes = ? WHERE id = ?')
    .run(outCallId, callbackStatus, minutes, missed.id);
}

// Пропущенные, чьё окно перезвона истекло без исходящего звонка, помечаем
// «не перезвонили»; если перезвон всё же случится позже, linkCallbackIfMatches
// найдёт их по callback_call_id IS NULL и перекроет статус на 'late'.
function sweepExpiredCallbackWindows(windowMin) {
  const threshold = toUisDateString(new Date(Date.now() - windowMin * 60000));
  db.prepare(`
    UPDATE calls SET callback_status = 'none'
    WHERE direction = 'in' AND is_answered = 0 AND callback_call_id IS NULL
      AND callback_status IS NULL AND started_at <= ?
  `).run(threshold);
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  const tick = async () => {
    try {
      await pollOnce();
    } catch (err) {
      console.error('[telephony] Ошибка опроса UIS:', err.message);
    } finally {
      const settings = getTelephonySettings();
      pollTimer = setTimeout(tick, Math.max(60, settings.poll_interval_sec || 300) * 1000);
    }
  };
  tick();
}

module.exports = { startPolling, pollOnce };
