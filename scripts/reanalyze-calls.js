// Пересчёт уже обработанных звонков по новой логике оценки (контекстная
// оценка: NA/UNCERTAIN, критические ошибки отдельно от рекомендаций — см.
// ai-processing.js) БЕЗ повторного скачивания записи и повторной
// транскрибации — расшифровка уже есть в calls.transcript, пересчитывается
// только сам ИИ-анализ и баллы чек-листа. Нужен, когда логика оценки
// поменялась и хочется применить её к уже принятым звонкам задним числом.
//
// Использование:
//   node scripts/reanalyze-calls.js --days 7            — только показать, что попадёт под пересчёт
//   node scripts/reanalyze-calls.js --days 7 --confirm  — реально пересчитать
//
// Работает последовательно (не параллельно) и с небольшой паузой между
// звонками, чтобы не упереться в лимиты OpenAI/UIS. Прогресс пишется в stdout.

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
    SELECT id, salon_id, started_at FROM calls
    WHERE status = 'done' AND transcript IS NOT NULL AND started_at >= datetime('now', ?)
    ORDER BY id
  `).all(`-${days} days`);

  if (rows.length === 0) {
    console.log(`Звонков за последние ${days} дн. для пересчёта не найдено.`);
    return;
  }

  console.log(`Найдено звонков за последние ${days} дн.: ${rows.length}`);
  if (!confirm) {
    console.log('\n[СУХОЙ ПРОГОН] Ничего не пересчитано. Запустите с флагом --confirm, чтобы пересчитать.');
    return;
  }

  let ok = 0, failed = 0;
  for (const [i, r] of rows.entries()) {
    try {
      await processCall(r.id, { reuseTranscript: true });
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
