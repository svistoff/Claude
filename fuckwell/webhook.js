// Вебхук МегаФон ВАТС: POST /api/megafon (application/x-www-form-urlencoded).
// cmd=event — события звонка в реальном времени, cmd=history — итог звонка
// (длительность, статус, запись) — здесь запускается ИИ-анализ.
// Один callid приходит несколько раз — строка дополняется, не затирается.
// Токен сверяется в постоянном времени и не пишется в лог.

const crypto = require('crypto');
const db = require('../db');
const { normalizePhone, resolveCall, getSettings, toDbString } = require('./util');
const { enqueueAnalysis, shouldAnalyze } = require('./ai');

const SECRET_KEYS = new Set(['crm_token', 'token', 'api_key', 'x-api-key']);
const redact = data => Object.fromEntries(Object.entries(data).map(([k, v]) => [k, SECRET_KEYS.has(k.toLowerCase()) ? '***' : v]));

function tokenOk(received) {
  const expected = getSettings().megafon_crm_token;
  if (!expected || !received) return false;
  const a = Buffer.from(String(received)), b = Buffer.from(expected);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

// 'YYYYmmddTHHMMSSZ' или ISO -> "YYYY-MM-DD HH:MM:SS" UTC
function parseStart(value) {
  const v = String(value || '').trim();
  if (!v) return null;
  const compact = v.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/);
  const d = compact ? new Date(Date.UTC(+compact[1], +compact[2] - 1, +compact[3], +compact[4], +compact[5], +compact[6])) : new Date(v);
  return isNaN(d.getTime()) ? null : toDbString(d);
}

const toInt = v => { const n = Math.trunc(Number(v)); return Number.isFinite(n) && v !== '' && v != null ? n : null; };

function numberIdFor(diversion, clientPhone) {
  const resolved = resolveCall(diversion, clientPhone || '');
  const phone = resolved ? resolved.number : diversion;
  const row = db.prepare('SELECT id FROM fw_numbers WHERE phone = ?').get(phone);
  return row ? row.id : null;
}

// после добавления/изменения номера — перепривязать уже накопленные звонки
function relinkAllCalls() {
  const update = db.prepare('UPDATE fw_calls SET number_id = ? WHERE id = ?');
  let changed = 0;
  db.transaction(() => {
    for (const c of db.prepare('SELECT id, number_id, diversion, client_phone FROM fw_calls WHERE diversion IS NOT NULL').all()) {
      const numberId = numberIdFor(c.diversion, c.client_phone);
      if (numberId !== c.number_id) { update.run(numberId, c.id); changed++; }
    }
  })();
  return changed;
}

function upsertCall(data, cmd) {
  const callId = data.callid || '';
  db.prepare('INSERT OR IGNORE INTO fw_calls (call_id) VALUES (?)').run(callId);
  const call = db.prepare('SELECT * FROM fw_calls WHERE call_id = ?').get(callId);
  const upd = {};

  const clientPhone = normalizePhone(data.phone);
  const diversion = normalizePhone(data.diversion);
  const callType = String(data.type || '').trim();
  let direction = String(data.direction || '').trim().toLowerCase();
  if (!['in', 'out'].includes(direction) && ['in', 'out'].includes(callType.toLowerCase())) direction = callType.toLowerCase();

  if (clientPhone) upd.client_phone = clientPhone;
  if (diversion) {
    upd.diversion = diversion;
    // номер клиента приходит не в каждом вебхуке — берём уже сохранённый
    const numberId = numberIdFor(diversion, clientPhone || call.client_phone);
    if (numberId) upd.number_id = numberId;
  }
  if (data.telnum_name) upd.telnum_name = data.telnum_name;
  if (direction) upd.direction = direction;

  if (cmd === 'event' && callType) {
    upd.event_type = callType;
    // на недозвоны МегаФон шлёт только event=CANCELLED без history — фиксируем
    // пропущенный сам; пришедшая позже history перезапишет статус
    if (callType.toUpperCase() === 'CANCELLED' && (direction || call.direction) === 'in' && !call.status) upd.status = 'missed';
  }
  if (cmd === 'history') {
    if (data.status) upd.status = data.status;
    const duration = toInt(data.duration); if (duration !== null) upd.duration = duration;
    const wait = toInt(data.wait); if (wait !== null) upd.wait = wait;
    const started = parseStart(data.start); if (started) upd.started_at = started;
    const link = data.link || data.record; if (link) upd.recording_url = link;
  }
  upd.raw_payload = JSON.stringify(redact(data));

  const cols = Object.keys(upd);
  db.prepare(`UPDATE fw_calls SET ${cols.map(c => `${c} = ?`).join(', ')}, updated_at = datetime('now') WHERE call_id = ?`)
    .run(...cols.map(c => upd[c]), callId);
  return db.prepare('SELECT * FROM fw_calls WHERE call_id = ?').get(callId);
}

function megafonWebhook(req, res) {
  const data = Object.fromEntries(Object.entries(req.body || {}).map(([k, v]) => [k, String(v)]));
  if (!tokenOk(data.crm_token)) {
    console.warn('[fuckwell] отклонён вебхук МегаФона: неверный crm_token');
    return res.status(401).json({ status: 'error', detail: 'unauthorized' });
  }
  const cmd = String(data.cmd || '').trim().toLowerCase();
  console.log(`[fuckwell] МегаФон cmd=${cmd || '?'} ${JSON.stringify(redact(data))}`);

  if (cmd === 'contact') return res.json({ contact_name: '', responsible: '' });
  if (cmd !== 'event' && cmd !== 'history') return res.json({ status: 'ok' });
  if (!data.callid) return res.json({ status: 'ok' });

  let call;
  try {
    call = upsertCall(data, cmd);
  } catch (err) {
    console.error('[fuckwell] ошибка сохранения звонка:', err.message);
    return res.status(500).json({ status: 'error' });
  }
  if (cmd === 'history' && shouldAnalyze(call)) enqueueAnalysis(call.call_id);
  res.json({ status: 'ok' });
}

module.exports = { megafonWebhook, relinkAllCalls };
