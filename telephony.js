// Приём звонков UIS (Data API, get.calls_report) — плюс логика пропущенных
// звонков и привязки перезвонов.
//
// Один опрос раз в poll_interval_sec забирает ВСЕ звонки аккаунта за период
// одним запросом (без фильтра по номеру), а дальше каждый звонок раскладывается
// по объектам локально — по карте "номер -> объект" (см. lib.getSalonPhoneMap).
// Так сделано потому, что на объект может приходить несколько разных номеров
// (например, с разных рекламных площадок с переадресацией на один салон) —
// фильтрация по единственному "своему" номеру объекта теряла бы такие звонки.
// Звонки на номера, которых нет ни у одного объекта в карте, просто пропускаются.

const fetch = require('node-fetch');
const db = require('./db');
const { normalizePhone, findOrCreateClient, getSalonPhoneMap, getSharedIvrNumberSet, getExcludedNumberSet, getActionNameSalonMap } = require('./lib');

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
  if (json.error) {
    const details = json.error.data ? ` | data: ${JSON.stringify(json.error.data)}` : '';
    throw new Error(`UIS API error: ${json.error.message || JSON.stringify(json.error)}${details}`);
  }
  return json.result;
}

// UIS ждёт даты в формате "YYYY-MM-DD HH:mm:ss" (без "T"/"Z") — это же формат,
// который отдаёт SQLite для datetime('now'), поэтому используем его везде.
// ВАЖНО: сами значения — не UTC, а в часовом поясе аккаунта UIS (подтверждено
// на практике: Екатеринбург, UTC+5, без перехода на летнее время). Эта функция
// только форматирует Date в строку — сдвиг на офсет делают вызывающие места.
function toUisDateString(date) {
  return date.toISOString().slice(0, 19).replace('T', ' ');
}

// Переводит РЕАЛЬНЫЙ момент времени (мс с эпохи) в строку "который час сейчас
// у UIS" — используется для date_from/date_till, отправляемых В UIS, и при
// сохранении last_poll_at. Для арифметики НАД уже полученной от UIS строкой
// (например, "+10 минут от начала звонка") офсет второй раз применять не
// нужно — там уже находимся в системе координат UIS, просто считаем разницу.
function uisLocalStringFor(instantMs, offsetHours) {
  return toUisDateString(new Date(instantMs + offsetHours * 3600000));
}

async function fetchAllCalls(sinceStr, tillStr) {
  const result = await uisRequest('get.calls_report', {
    date_from: sinceStr,
    date_till: tillStr,
    fields: [
      'id', 'start_time', 'direction', 'is_lost', 'talk_duration',
      'contact_phone_number', 'virtual_phone_number', 'communication_number', 'call_records'
    ]
  });
  return (result && result.data) || [];
}

// call_records от UIS — это не прямая ссылка, а хэш-идентификатор записи
// (подтверждено на практике: массив вида ["2e675888ded89ed517d5c60e63a2d8c3"]).
// Реальный playback-URL собирается по схеме из документации UIS/Comagic:
// https://app.comagic.ru/system/media/talk/{call_session_id}/{hash}/
// где call_session_id — это то же самое поле "id" звонка в отчёте.
// Важно: именно https — http отдаёт 308 редирект на https (подтверждено на практике).
function extractRecordUrl(c) {
  const raw = c.call_records;
  if (raw == null) return null;
  const arr = Array.isArray(raw) ? raw : [raw];
  if (arr.length === 0) return null;
  const first = arr[0];
  const hash = typeof first === 'string' ? first : (first?.record_url || first?.url || first?.hash || null);
  if (!hash) return null;
  return `https://app.comagic.ru/system/media/talk/${c.id}/${hash}/`;
}

// Для номеров с общим голосовым меню (см. shared_ivr_numbers) сам звонок не
// говорит, в какой салон его перевело меню — это видно только по "плечам"
// звонка (get.call_legs_report): исходящее плечо, которое реально соединилось
// (is_failed=false, есть connect_time), несёт поле action_name — название
// сценария/группы в UIS, которое администратор сопоставил с салоном
// (salons.uis_action_name) в интерфейсе. Подтверждено на практике: campaign_id
// для таких звонков всегда -1 (кампании в UIS не настроены), поэтому action_name
// с плеча — единственный надёжный сигнал.
async function fetchCallLegs(callSessionId, startTimeStr) {
  const tillStr = toUisDateString(new Date(new Date(startTimeStr).getTime() + 10 * 60000));
  try {
    const result = await uisRequest('get.call_legs_report', {
      date_from: startTimeStr,
      date_till: tillStr,
      filter: { field: 'call_session_id', operator: '=', value: callSessionId }
    });
    return (result && result.data) || [];
  } catch (err) {
    // call_session_id может оказаться нефильтруемым полем у этого метода —
    // тогда берём узкое окно по времени и отбираем нужную сессию сами
    const result = await uisRequest('get.call_legs_report', { date_from: startTimeStr, date_till: tillStr });
    const all = (result && result.data) || [];
    return all.filter(l => String(l.call_session_id) === String(callSessionId));
  }
}

function pickResolvingLeg(legs) {
  return legs.find(l => l.direction === 'out' && !l.is_failed && l.connect_time) || null;
}

// Возвращает { salon, actionName } — actionName возвращается даже когда salon
// не нашёлся, чтобы можно было залогировать реальное значение из UIS и
// подсказать владельцу, что вписать в карточку салона.
async function resolveSalonByLegs(call, actionNameMap, salonsById) {
  try {
    const legs = await fetchCallLegs(call.id, call.start_time);
    const leg = pickResolvingLeg(legs);
    if (!leg || !leg.action_name) return { salon: null, actionName: null };
    const salonId = actionNameMap.get(leg.action_name.trim().toLowerCase());
    return { salon: salonId ? salonsById.get(salonId) : null, actionName: leg.action_name };
  } catch (err) {
    console.error(`[telephony] Не удалось получить плечи звонка #${call.id}:`, err.message);
    return { salon: null, actionName: null };
  }
}

// Забирает и раскладывает звонки за период [sinceStr, tillStr] по объектам.
// Используется и обычным опросом, и ручным backfill за произвольный период.
async function ingestCalls(sinceStr, tillStr) {
  const salonsById = new Map(db.prepare('SELECT * FROM salons WHERE active = 1').all().map(s => [s.id, s]));
  const phoneMap = getSalonPhoneMap();
  const sharedIvrNumbers = getSharedIvrNumberSet();
  const excludedNumbers = getExcludedNumberSet();
  const actionNameMap = getActionNameSalonMap();

  const calls = await fetchAllCalls(sinceStr, tillStr);
  // сортируем по времени начала, чтобы пропущенный всегда сохранялся раньше перезвона
  calls.sort((a, b) => new Date(a.start_time) - new Date(b.start_time));

  // Номер, на который поступил звонок, может быть либо "родным" виртуальным
  // номером UIS (virtual_phone_number), либо чужим номером, перенесённым в
  // UIS через SIP-реквизиты (в этом случае заполнено communication_number,
  // а virtual_phone_number может быть пустым) — проверяем оба поля.
  const unmatchedNumbers = new Set();
  let matched = 0;
  for (const c of calls) {
    const candidate = normalizePhone(c.virtual_phone_number) || normalizePhone(c.communication_number);

    // аккаунт UIS общий с другим бизнесом — его номера пропускаем молча,
    // даже не логируя как "непривязанные" (не наши данные)
    if (candidate && excludedNumbers.has(candidate)) continue;

    let salon = candidate ? salonsById.get(phoneMap.get(candidate)) : null;

    if (!salon && candidate && sharedIvrNumbers.has(candidate)) {
      const resolved = await resolveSalonByLegs(c, actionNameMap, salonsById);
      salon = resolved.salon;
      if (!salon) {
        const numberDesc = c.virtual_phone_number || c.communication_number;
        if (resolved.actionName) {
          console.log(`[telephony] Звонок на общий номер меню ${numberDesc} (id=${c.id}): плечо ушло в сценарий UIS "${resolved.actionName}", но ни один салон не сопоставлен с этим названием — впишите "${resolved.actionName}" в поле "Название сценария в UIS" нужного салона.`);
        } else {
          console.log(`[telephony] Звонок на общий номер меню ${numberDesc} (id=${c.id}): не нашлось успешного исходящего плеча с action_name (клиент мог положить трубку в меню, не дозвонившись до салона).`);
        }
      }
    }

    if (!salon) {
      if (c.virtual_phone_number || c.communication_number) {
        unmatchedNumbers.add(`${c.virtual_phone_number || '—'} / ${c.communication_number || '—'}`);
      }
      continue;
    }
    saveCall(salon, c);
    matched++;
  }
  if (unmatchedNumbers.size > 0) {
    console.log(`[telephony] Звонки на номера, не привязанные ни к одному объекту (virtual_phone_number / communication_number): ${Array.from(unmatchedNumbers).join('; ')} — добавьте нужный номер в "Салоны" → "Номера" либо в "Общие номера меню".`);
  }
  return { total: calls.length, matched, unmatchedNumbers: Array.from(unmatchedNumbers) };
}

async function pollOnce() {
  const settings = getTelephonySettings();
  if (!settings.enabled || !settings.uis_api_key) return;

  const offset = settings.uis_timezone_offset_hours;
  const since = settings.last_poll_at || uisLocalStringFor(Date.now() - 24 * 60 * 60 * 1000, offset);
  const till = uisLocalStringFor(Date.now(), offset);

  try {
    await ingestCalls(since, till);
    // окно опроса сдвигаем вперёд ТОЛЬКО при успешном запросе — иначе при
    // ошибке API интервал молча "проглатывается" и эти звонки уже никогда
    // не будут забраны обычным опросом (только через ручной backfill ниже)
    db.prepare(`UPDATE telephony_settings SET last_poll_at = ? WHERE id = 1`).run(till);
  } catch (err) {
    console.error('[telephony] Ошибка получения звонков:', err.message);
  }

  sweepExpiredCallbackWindows(settings.callback_window_min, offset);
}

// Ручная дозагрузка за произвольный период — например, если обычный опрос
// не работал какое-то время (ошибка ключа, отладка и т.п.) и часть звонков
// не попала в окно, т.к. last_poll_at продолжал жить своей жизнью.
// UIS ограничивает период одного запроса тремя месяцами.
async function backfill(sinceStr, tillStr) {
  const settings = getTelephonySettings();
  if (!settings.uis_api_key) throw new Error('Не задан ключ UIS API');
  return ingestCalls(sinceStr, tillStr);
}

function saveCall(salon, c) {
  const uisCallId = String(c.id);
  if (db.prepare('SELECT id FROM calls WHERE uis_call_id = ?').get(uisCallId)) return;

  const direction = c.direction === 'out' ? 'out' : 'in';
  const isLost = c.is_lost === true || c.is_lost === 1 || c.is_lost === '1';
  const isAnswered = !isLost && Number(c.talk_duration) > 0;
  const callerPhone = c.contact_phone_number || null;
  const clientId = callerPhone ? findOrCreateClient(callerPhone) : null;

  let status;
  if (direction === 'in') status = isAnswered ? 'new' : 'missed';
  else status = isAnswered ? 'new' : 'skipped';

  const dialedNumber = c.virtual_phone_number || c.communication_number || null;

  const info = db.prepare(`
    INSERT INTO calls (salon_id, client_id, uis_call_id, direction, caller_phone, dialed_number, started_at, duration_sec, is_answered, recording_url, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    salon.id, clientId, uisCallId, direction, callerPhone, dialedNumber,
    c.start_time || uisLocalStringFor(Date.now(), getTelephonySettings().uis_timezone_offset_hours), Number(c.talk_duration) || 0,
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
function sweepExpiredCallbackWindows(windowMin, offsetHours) {
  const threshold = uisLocalStringFor(Date.now() - windowMin * 60000, offsetHours);
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

module.exports = { startPolling, pollOnce, backfill };
