const db = require('./db');

// Эффективный чек-лист салона = активные глобальные пункты (кроме отключённых
// override'ом для этого салона) + активные пункты, добавленные именно этому салону.
function getEffectiveChecklist(salonId) {
  return db.prepare(`
    SELECT ci.id, ci.text, ci.position, (ci.salon_id IS NOT NULL) AS is_local
    FROM checklist_items ci
    WHERE ci.active = 1
      AND (
        ci.salon_id = ?
        OR (
          ci.salon_id IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM checklist_overrides co
            WHERE co.salon_id = ? AND co.item_id = ci.id AND co.disabled = 1
          )
        )
      )
    ORDER BY ci.position ASC, ci.id ASC
  `).all(salonId, salonId);
}

function userSalonIds(userId) {
  return db.prepare('SELECT salon_id FROM user_salons WHERE user_id = ?').all(userId).map(r => r.salon_id);
}

function canAccessSalon(user, salonId) {
  if (user.role === 'admin') return true;
  const row = db.prepare('SELECT 1 FROM user_salons WHERE user_id = ? AND salon_id = ?').get(user.id, salonId);
  return !!row;
}

module.exports = { getEffectiveChecklist, userSalonIds, canAccessSalon };
