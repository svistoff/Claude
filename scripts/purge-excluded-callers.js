// Разовая чистка истории: удаляет звонки, которые уже лежат в базе, но
// пришли с номеров, добавленных в "Тестовые номера" (excluded_caller_numbers)
// ПОСЛЕ того, как эти звонки были приняты. Сам приём звонков (telephony.js,
// scripts/import-uis-csv.js) такие номера уже фильтрует и новых звонков с
// них не сохраняет — этот скрипт only подчищает то, что успело попасть в
// базу раньше.
//
// Использование:
//   node scripts/purge-excluded-callers.js            — только показать, что нашлось
//   node scripts/purge-excluded-callers.js --confirm   — реально удалить
//
// Безопасно для ссылочной целостности: все внешние ключи на calls(id)
// (callback_call_id, ai_usage.call_id) стоят ON DELETE SET NULL.

const db = require('../db');
const { normalizePhone, getExcludedCallerNumberSet } = require('../lib');

function main() {
  const confirm = process.argv.includes('--confirm');
  const excluded = getExcludedCallerNumberSet();

  if (excluded.size === 0) {
    console.log('Список "Тестовые номера" пуст — нечего чистить.');
    return;
  }

  const rows = db.prepare('SELECT id, caller_phone, salon_id, started_at FROM calls').all();
  const toDelete = rows.filter(r => {
    const norm = normalizePhone(r.caller_phone);
    return norm && excluded.has(norm);
  });

  if (toDelete.length === 0) {
    console.log('Звонков с тестовых номеров в базе не найдено — чистить нечего.');
    return;
  }

  console.log(`Найдено звонков с тестовых номеров: ${toDelete.length}`);
  const byPhone = new Map();
  for (const r of toDelete) {
    const norm = normalizePhone(r.caller_phone);
    byPhone.set(norm, (byPhone.get(norm) || 0) + 1);
  }
  for (const [phone, count] of byPhone) console.log(`  ${phone}: ${count}`);

  console.log('\nПримеры (первые 10):');
  for (const r of toDelete.slice(0, 10)) {
    console.log(`  #${r.id} · salon_id=${r.salon_id} · ${r.started_at} · ${r.caller_phone}`);
  }

  if (!confirm) {
    console.log('\n[СУХОЙ ПРОГОН] Ничего не удалено. Запустите с флагом --confirm, чтобы удалить эти звонки.');
    return;
  }

  const del = db.prepare('DELETE FROM calls WHERE id = ?');
  const info = db.transaction(() => {
    let n = 0;
    for (const r of toDelete) { del.run(r.id); n++; }
    return n;
  })();
  console.log(`\nУдалено звонков: ${info}`);
}

main();
