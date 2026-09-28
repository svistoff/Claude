// Разовый импорт исторических звонков из CSV-выгрузки отчёта UIS через
// командную строку — тонкая обёртка над ../csv-import.js (та же логика,
// что и у формы загрузки в Настройках → Телефония UIS → "Дозагрузить из
// файла"). Нужен, когда нет доступа в браузер к СРМ, только SSH.
//
// Использование:
//   node scripts/import-uis-csv.js путь/к/отчёту.csv [--dry-run]

const fs = require('fs');
const path = require('path');
const { importUisCsv } = require('../csv-import');

function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes('--dry-run');
  const filePath = args.find(a => !a.startsWith('--'));
  if (!filePath) {
    console.error('Использование: node scripts/import-uis-csv.js путь/к/отчёту.csv [--dry-run]');
    process.exit(1);
  }

  const text = fs.readFileSync(path.resolve(filePath), 'utf8');
  const r = importUisCsv(text, { dryRun });

  console.log(`Строк с данными: ${r.totalRows}`);
  console.log(`\n${dryRun ? '[СУХОЙ ПРОГОН, ничего не сохранено]\n' : ''}Готово: обработано ${r.totalRows}, ${dryRun ? 'будет добавлено' : 'добавлено'} ${r.inserted}, уже были в базе (пропущены) ${r.duplicates}, исключённых номеров ${r.excluded}.`);
  if (r.badDates) console.log(`Пропущено строк с нераспознанной датой: ${r.badDates}`);

  if (r.matchedBySalon.length) {
    console.log('\nПо салонам:');
    for (const { name, count } of r.matchedBySalon) console.log(`  ${name}: ${count}`);
  }
  if (r.unmatchedByLabel.length) {
    console.log('\nНепривязанные метки UIS (добавьте нужному салону через "Метки UIS" и запустите импорт ещё раз):');
    for (const { label, count } of r.unmatchedByLabel) console.log(`  "${label}": ${count}`);
  }
  if (r.unmatchedByNumber.length) {
    console.log('\nНепривязанные номера (без метки, добавьте в "Салоны" → "Номера" или в "Общие номера меню"):');
    for (const { number, count } of r.unmatchedByNumber) console.log(`  ${number}: ${count}`);
  }
}

try { main(); } catch (err) { console.error('Ошибка импорта:', err); process.exit(1); }
