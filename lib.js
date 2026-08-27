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

// Администратор привязан ровно к одному объекту (через users -> admins.user_id).
function adminForUser(userId) {
  return db.prepare('SELECT * FROM admins WHERE user_id = ?').get(userId);
}

function canAccessSalon(user, salonId) {
  if (user.role === 'admin') return true;
  const admin = adminForUser(user.id);
  return !!admin && admin.salon_id === Number(salonId);
}

module.exports = { normalizePhone, findOrCreateClient, getEffectiveChecklist, getSalonPhoneMap, adminForUser, canAccessSalon };
