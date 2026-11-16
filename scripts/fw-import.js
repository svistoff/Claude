// Импорт звонков Fuckwell из JSON-файла прямо на сервере (без загрузки через браузер).
//   node scripts/fw-import.js /root/fw-legacy.json
// Файл делается из базы старой crm.fuckwell.ru скриптом scripts/fw-legacy-export.sql.
// Повторный запуск безопасен: уже загруженные звонки пропускаются.
const fs = require('fs');
const path = require('path');
process.chdir(path.join(__dirname, '..'));
const { importFuckwell } = require('../fuckwell/routes');

const file = process.argv[2];
if (!file) { console.error('Укажите файл: node scripts/fw-import.js /root/fw-legacy.json'); process.exit(1); }
const data = JSON.parse(fs.readFileSync(file, 'utf8'));
const res = importFuckwell(data);
console.log(`Загружено: звонков ${res.calls} из ${data.calls.length}, анализов ИИ ${res.analyses}, новых номеров ${res.numbers}`);
process.exit(0);
