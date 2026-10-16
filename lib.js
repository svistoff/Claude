const db = require('./db');

// Нормализация телефона для склейки клиентов и сопоставления перезвонов:
// оставляем только цифры, приводим ведущую "8" к "7".
function normalizePhone(phone) {
  if (!phone) return null;
  let digits = String(phone).replace(/\D/g, '');
  if (digits.length === 11 && digits[0] === '8') digits = '7' + digits.slice(1);
  if (digits.length === 10) digits = '7' + digits;
  return digits || null;
}

function findOrCreateClient(phone, name) {
  const norm = normalizePhone(phone);
  if (!norm) return null;
  const existing = db.prepare('SELECT * FROM clients WHERE phone = ?').get(norm);
  if (existing) {
    if (name && !existing.name) {
      db.prepare(`UPDATE clients SET name = ?, updated_at = datetime('now') WHERE id = ?`).run(name, existing.id);
    } else {
      db.prepare(`UPDATE clients SET updated_at = datetime('now') WHERE id = ?`).run(existing.id);
    }
    return existing.id;
  }
  const info = db.prepare('INSERT INTO clients (phone, name) VALUES (?, ?)').run(norm, name || null);
  return info.lastInsertRowid;
}

// Эффективный чек-лист объекта:
//  - checklist_mode = 'custom'  -> только пункты, привязанные лично к этому объекту
//  - checklist_mode = 'template' -> активные пункты общего шаблона своего типа
//                                    (кроме отключённых override'ом) + личные добавки объекта
function getEffectiveChecklist(salon) {
  if (typeof salon === 'number') salon = db.prepare('SELECT * FROM salons WHERE id = ?').get(salon);
  if (!salon) return [];

  if (salon.checklist_mode === 'custom') {
    return db.prepare(`
      SELECT * FROM checklist_items WHERE salon_id = ? AND active = 1 ORDER BY position, id
    `).all(salon.id);
  }

  return db.prepare(`
    SELECT * FROM checklist_items ci
    WHERE ci.active = 1
      AND (
        ci.salon_id = ?
        OR (
          ci.salon_id IS NULL AND ci.template = ?
          AND NOT EXISTS (
            SELECT 1 FROM checklist_overrides co
            WHERE co.salon_id = ? AND co.item_id = ci.id AND co.disabled = 1
          )
        )
      )
    ORDER BY ci.salon_id IS NOT NULL, ci.position, ci.id
  `).all(salon.id, salon.type, salon.id);
}

// Чек-лист для звонков на анкетный/рекламный номер (см. ad_phone_numbers) —
// администратор заранее знает от ЮИС, что это не обычный звонок в объект, и
// не обязан вести его по скрипту конкретного салона/сауны. Единый на всю
// сеть, без привязки к объекту и без override'ов — объект тут не при чём.
function getAnketaChecklist() {
  return db.prepare(`
    SELECT * FROM checklist_items WHERE template = 'anketa' AND salon_id IS NULL AND active = 1 ORDER BY position, id
  `).all();
}

// Набор нормализованных анкетных/рекламных номеров (см. ad_phone_numbers) —
// используется, чтобы понять, что звонок пришёл не "в объект", а "в анкету"
// (calls.dialed_number у таких звонков совпадает с одним из этих номеров).
function getAdPhoneNumberSet() {
  const rows = db.prepare('SELECT phone FROM ad_phone_numbers').all();
  return new Set(rows.map(r => r.phone).filter(Boolean));
}

// Карта "нормализованный номер -> salon_id" по всем активным объектам:
// основной номер салона + все доп. номера (например, с рекламных площадок
// с переадресацией на этот салон). Используется телефонией, чтобы разложить
// звонки по объектам вне зависимости от того, по какому именно из номеров
// клиент дозвонился.
function getSalonPhoneMap() {
  const map = new Map();
  const salons = db.prepare('SELECT * FROM salons WHERE active = 1').all();
  const extra = db.prepare('SELECT * FROM salon_phone_numbers').all();
  for (const s of salons) {
    for (const raw of [s.phone, s.uis_line_id]) {
      const norm = normalizePhone(raw);
      if (norm) map.set(norm, s.id);
    }
  }
  for (const row of extra) {
    const norm = normalizePhone(row.phone);
    if (norm) map.set(norm, row.salon_id);
  }
  return map;
}

// Номера с общим голосовым меню на несколько объектов ("нажмите 1 — Жара,
// нажмите 2 — VIP") — по самому номеру объект не определить, для них
// используется отдельная логика через get.call_legs_report (см. telephony.js).
function getSharedIvrNumberSet() {
  const rows = db.prepare('SELECT phone FROM shared_ivr_numbers').all();
  return new Set(rows.map(r => normalizePhone(r.phone)).filter(Boolean));
}

// Номера заведомо чужого бизнеса на том же аккаунте UIS — их не нужно ни
// сохранять, ни даже упоминать в логах непривязанных номеров.
function getExcludedNumberSet() {
  const rows = db.prepare('SELECT phone FROM excluded_call_numbers').all();
  return new Set(rows.map(r => normalizePhone(r.phone)).filter(Boolean));
}

// Номера звонящих, чьи звонки вообще не учитываются (например, тестовые
// звонки владельца проверить связь с админом) — см. excluded_caller_numbers.
function getExcludedCallerNumberSet() {
  const rows = db.prepare('SELECT phone FROM excluded_caller_numbers').all();
  return new Set(rows.map(r => normalizePhone(r.phone)).filter(Boolean));
}

// Карта "метка UIS (employee_full_name из get.calls_report ИЛИ action_name
// плеча из get.call_legs_report) -> salon_id". У одного салона бывает
// несколько разных меток (разные источники трафика называют его по-разному,
// например "Чайковского (Жара) (amoCRM)" и просто "Жара"), поэтому это
// отдельная таблица salon_uis_labels, а не одно поле салона.
function getActionNameSalonMap() {
  const map = new Map();
  const rows = db.prepare(`
    SELECT sl.label, sl.salon_id FROM salon_uis_labels sl
    JOIN salons s ON s.id = sl.salon_id WHERE s.active = 1
  `).all();
  for (const r of rows) map.set(r.label.trim().toLowerCase(), r.salon_id);
  return map;
}

function getForwardingRules() {
  return db.prepare('SELECT * FROM salon_forwarding').all();
}

// Куда переадресован объект в момент startedAt ("YYYY-MM-DD HH:mm:ss" в часовом
// поясе UIS — том же, в котором время показывается в списке звонков) или null.
// День недели берётся по дате самого звонка, в т.ч. для окна через полночь.
function forwardTargetFor(rules, salonId, startedAt) {
  if (!startedAt) return null;
  const weekday = ((new Date(startedAt.slice(0, 10) + 'T00:00:00Z').getUTCDay() + 6) % 7) + 1;
  const t = startedAt.slice(11, 16);
  for (const r of rules) {
    if (r.salon_id !== salonId || !r.weekdays.split(',').map(Number).includes(weekday)) continue;
    const inWindow = r.time_from === r.time_till ? true
      : r.time_from < r.time_till ? (t >= r.time_from && t < r.time_till)
      : (t >= r.time_from || t < r.time_till);
    if (inWindow) return r.target_salon_id;
  }
  return null;
}

// Пересчитывает переадресацию входящих звонков начиная с sinceStr по текущим
// правилам: переносит попавшие под правило и возвращает обратно те, что
// были перенесены по уже удалённому/изменённому правилу.
function reapplyForwarding(sinceStr) {
  const rules = getForwardingRules();
  const calls = db.prepare(`
    SELECT id, salon_id, forwarded_from_salon_id, started_at FROM calls
    WHERE direction = 'in' AND started_at >= ?
  `).all(sinceStr);
  const update = db.prepare('UPDATE calls SET salon_id = ?, forwarded_from_salon_id = ? WHERE id = ?');
  let moved = 0, restored = 0;
  db.transaction(() => {
    for (const c of calls) {
      const original = c.forwarded_from_salon_id ?? c.salon_id;
      const target = forwardTargetFor(rules, original, c.started_at);
      const wantSalon = target ?? original;
      const wantFrom = target ? original : null;
      if (wantSalon === c.salon_id && wantFrom === c.forwarded_from_salon_id) continue;
      update.run(wantSalon, wantFrom, c.id);
      if (target) moved++; else restored++;
    }
  })();
  return { moved, restored };
}

// Администратор привязан ровно к одному объекту (через users -> admins.user_id).
function adminForUser(userId) {
  return db.prepare('SELECT * FROM admins WHERE user_id = ?').get(userId);
}

function canAccessSalon(user, salonId) {
  if (user.role === 'admin') return true;
  const admin = adminForUser(user.id);
  return !!admin && admin.salon_id === Number(salonId);
}

module.exports = {
  normalizePhone, findOrCreateClient, getEffectiveChecklist, getAnketaChecklist, getSalonPhoneMap,
  getSharedIvrNumberSet, getExcludedNumberSet, getExcludedCallerNumberSet, getAdPhoneNumberSet,
  getActionNameSalonMap, adminForUser, canAccessSalon, getForwardingRules, forwardTargetFor, reapplyForwarding
};
