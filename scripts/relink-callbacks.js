// Пересчёт перезвонов по уже накопленным звонкам — после перехода на поиск
// перезвона по всей сети (переадресация Рай/НУАР -> 8 Марта) и исправления
// ошибки, из-за которой перезвон находился только к самому последнему
// пропущенному объекта. Трогает только пропущенные, к которым перезвон ещё
// не привязан; уже привязанные перезвоны не меняются.
//
// Использование:
//   node scripts/relink-callbacks.js --days 30            — только показать
//   node scripts/relink-callbacks.js --days 30 --confirm  — записать

const db = require('../db');
const { relinkCallbacks } = require('../telephony');

const args = process.argv.slice(2);
const confirm = args.includes('--confirm');
const daysIdx = args.indexOf('--days');
const days = daysIdx !== -1 && args[daysIdx + 1] ? Number(args[daysIdx + 1]) : 30;
if (!Number.isFinite(days) || days <= 0) {
  console.error('Укажите корректное число дней: --days 30');
  process.exit(1);
}

const offset = db.prepare('SELECT uis_timezone_offset_hours FROM telephony_settings WHERE id = 1').get().uis_timezone_offset_hours || 0;
const since = new Date(Date.now() + offset * 3600000 - days * 24 * 3600000).toISOString().slice(0, 19).replace('T', ' ');
const salonName = new Map(db.prepare('SELECT id, name FROM salons').all().map(s => [s.id, s.name]));

const links = relinkCallbacks(since, { dryRun: !confirm });
const cross = links.filter(l => l.missedSalonId !== l.outSalonId);

console.log(`Пропущенных за ${days} дн., к которым найден перезвон: ${links.length}`);
console.log(`  из них вовремя: ${links.filter(l => l.status === 'on_time').length}, позже окна: ${links.filter(l => l.status === 'late').length}`);
console.log(`  перезвонили с ДРУГОГО объекта: ${cross.length}`);
const pairs = new Map();
for (const l of cross) {
  const key = `${salonName.get(l.missedSalonId)} -> перезвонил ${salonName.get(l.outSalonId)}`;
  pairs.set(key, (pairs.get(key) || 0) + 1);
}
for (const [k, n] of pairs) console.log(`    ${n}x: ${k}`);

console.log(confirm
  ? '\nЗаписано.'
  : '\n[СУХОЙ ПРОГОН] Ничего не изменено. Запустите с флагом --confirm, чтобы записать.');
