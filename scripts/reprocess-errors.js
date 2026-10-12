// Повторная обработка звонков, упавших в status='error' — в отличие от
// scripts/reanalyze-calls.js, здесь НЕТ сохранённой расшифровки (транскрибация
// сама и упала), поэтому processCall вызывается без reuseTranscript: запись
// скачивается и транскрибируется заново (платно, как обычная обработка).
// Нужен после разовых сбоев вроде "кончились кредиты OpenAI" — ЮИС звонки
// принял нормально, но ИИ их не разобрал, и они зависли в error навсегда
// (автоматический опрос подхватывает только status='new').
//
// Использование:
//   node scripts/reprocess-errors.js --days 7            — только показать, что попадёт под обработку
//   node scripts/reprocess-errors.js --days 7 --confirm  — реально обработать

const db = require('../db');
const { processCall } = require('../ai-processing');

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
  const args = process.argv.slice(2);
  const confirm = args.includes('--confirm');
  const daysIdx = args.indexOf('--days');
  const days = daysIdx !== -1 && args[daysIdx + 1] ? Number(args[daysIdx + 1]) : 7;
  if (!Number.isFinite(days) || days <= 0) {
    console.error('Укажите корректное число дней: --days 7');
    process.exit(1);
  }

  const rows = db.prepare(`
    SELECT id, salon_id, started_at, error_message FROM calls
    WHERE status = 'error' AND started_at >= datetime('now', ?)
    ORDER BY id
  `).all(`-${days} days`);

  if (rows.length === 0) {
    console.log(`Звонков со статусом "ошибка" за последние ${days} дн. не найдено.`);
    return;
  }

  console.log(`Найдено звонков со статусом "ошибка" за последние ${days} дн.: ${rows.length}`);
  const sample = new Map();
  for (const r of rows) sample.set(r.error_message, (sample.get(r.error_message) || 0) + 1);
  console.log('Причины:');
  for (const [msg, count] of sample) console.log(`  ${count}x: ${msg}`);

  if (!confirm) {
    console.log('\n[СУХОЙ ПРОГОН] Ничего не обработано. Запустите с флагом --confirm, чтобы обработать (платно — заново скачивание+транскрибация).');
    return;
  }

  let ok = 0, failed = 0;
  for (const [i, r] of rows.entries()) {
    try {
      await processCall(r.id);
      ok++;
      console.log(`[${i + 1}/${rows.length}] OK #${r.id}`);
    } catch (err) {
      failed++;
      console.error(`[${i + 1}/${rows.length}] ОШИБКА #${r.id}: ${err.message}`);
    }
    await sleep(500); // не долбить OpenAI пачкой параллельных запросов
  }
  console.log(`\nГотово: успешно ${ok}, с ошибкой ${failed}, всего ${rows.length}.`);
}

main().catch(err => { console.error('Ошибка пересчёта:', err); process.exit(1); });
