// Разовый импорт исторических звонков из CSV-выгрузки отчёта UIS
// ("Название отчета: Звонки"), когда обычный опрос через Data API упирается
// в дневной лимит запросов (500/день) и штатный backfill временно недоступен.
//
// Резолюция салона использует ТУ ЖЕ логику, что и telephony.js ingestCalls:
// сначала прямое совпадение по номеру (getSalonPhoneMap), затем бесплатная
// метка "Сотрудники разговора" (аналог employees из get.calls_report) через
// salon_uis_labels. Звонки без ИИ-анализа сохраняются со статусом 'imported'
// (см. вопрос пользователя — полный ИИ-разбор ~1500 звонков разом стоит
// реальных денег и времени, поэтому импорт даёт только цифры для статистики).
//
// Использование:
//   node scripts/import-uis-csv.js путь/к/отчёту.csv [--dry-run]
//
// --dry-run — ничего не пишет в базу, только печатает сводку по тому, что
// было бы сделано (сколько куда распределится, что осталось непривязанным).
//
// Повторный запуск безопасен: звонки уникальны по uis_call_id (это
// "Идентификатор сессии звонка" из отчёта), уже сохранённые строки просто
// пропускаются.

const fs = require('fs');
const path = require('path');
const db = require('../db');
const {
  normalizePhone, findOrCreateClient, getSalonPhoneMap,
  getExcludedNumberSet, getActionNameSalonMap
} = require('../lib');

function parseCsv(text) {
  // Файл CRLF, поля в кавычках могут содержать запятые и переносы строк
  // (например, сериализованный python-dict в "Детализация звонка") —
  // разбираем посимвольно, а не по строкам.
  const rows = [];
  let row = [];
  let cur = '';
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') { cur += '"'; i++; }
        else inQuotes = false;
      } else {
        cur += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ',') {
      row.push(cur); cur = '';
    } else if (ch === '\r') {
      // пропускаем, конец строки определяем по \n
    } else if (ch === '\n') {
      row.push(cur); cur = '';
      rows.push(row); row = [];
    } else {
      cur += ch;
    }
  }
  if (cur !== '' || row.length > 0) { row.push(cur); rows.push(row); }
  return rows.filter(r => r.length > 1 || r[0] !== '');
}

// "DD.MM.YYYY HH:mm:ss" (уже в местном времени аккаунта UIS, как и start_time
// из API — доп. сдвиг по офсету не нужен, см. uisLocalStringFor в telephony.js)
function toDbDateString(s) {
  const m = /^(\d{2})\.(\d{2})\.(\d{4}) (\d{2}:\d{2}:\d{2})$/.exec(s || '');
  if (!m) return null;
  return `${m[3]}-${m[2]}-${m[1]} ${m[4]}`;
}

function durationToSeconds(s) {
  const m = /^(\d+):(\d{2}):(\d{2})$/.exec(s || '');
  if (!m) return 0;
  return Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]);
}

async function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes('--dry-run');
  const filePath = args.find(a => !a.startsWith('--'));
  if (!filePath) {
    console.error('Использование: node scripts/import-uis-csv.js путь/к/отчёту.csv [--dry-run]');
    process.exit(1);
  }

  const text = fs.readFileSync(path.resolve(filePath), 'utf8');
  const allRows = parseCsv(text);
  const headerIdx = allRows.findIndex(r => r[0] === 'Детализация звонка');
  if (headerIdx === -1) throw new Error('Не нашёл строку заголовка "Детализация звонка" — формат файла не тот?');

  const header = allRows[headerIdx];
  const col = name => {
    const idx = header.indexOf(name);
    if (idx === -1) throw new Error(`В отчёте нет колонки "${name}"`);
    return idx;
  };
  const idx = {
    sessionId: col('Идентификатор сессии звонка'),
    startTime: col('Дата и время звонка'),
    callerPhone: col('Номер абонента'),
    direction: col('Направление звонка'),
    status: col('Статус звонка'),
    virtualNumber: col('Виртуальный номер'),
    employees: col('Сотрудники разговора'),
    talkDuration: col('Длительность разговора'),
    recordingUrl: col('Запись разговора')
  };

  const dataRows = allRows.slice(headerIdx + 1).filter(r => r[idx.sessionId]);
  console.log(`Строк с данными: ${dataRows.length}`);

  const salonsById = new Map(db.prepare('SELECT * FROM salons WHERE active = 1').all().map(s => [s.id, s]));
  const phoneMap = getSalonPhoneMap();
  const excludedNumbers = getExcludedNumberSet();
  const actionNameMap = getActionNameSalonMap();

  const insertStmt = db.prepare(`
    INSERT INTO calls (salon_id, client_id, uis_call_id, direction, caller_phone, dialed_number, started_at, duration_sec, is_answered, recording_url, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);
  const existsStmt = db.prepare('SELECT id FROM calls WHERE uis_call_id = ?');

  let inserted = 0, duplicates = 0, excluded = 0;
  const matchedBySalon = new Map();
  const unmatchedByLabel = new Map();
  const unmatchedByNumber = new Map();

  const runOne = (row) => {
    const uisCallId = row[idx.sessionId];
    if (existsStmt.get(uisCallId)) { duplicates++; return; }

    const virtualNumber = row[idx.virtualNumber] || '';
    const candidate = normalizePhone(virtualNumber);
    if (candidate && excludedNumbers.has(candidate)) { excluded++; return; }

    let salon = candidate ? salonsById.get(phoneMap.get(candidate)) : null;

    // Бесплатная метка "Сотрудники разговора" — берём ПЕРВУЮ из списка, если
    // их несколько (звонок пытались раскидать по нескольким салонам сразу и
    // никто не ответил — по подтверждённому правилу такие относятся на
    // основной салон, который в отчёте всегда указан первым).
    const rawLabel = (row[idx.employees] || '').trim();
    const firstLabel = rawLabel ? rawLabel.split(',')[0].trim() : null;
    if (!salon && firstLabel) {
      const salonId = actionNameMap.get(firstLabel.toLowerCase());
      salon = salonId ? salonsById.get(salonId) : null;
    }

    if (!salon) {
      if (firstLabel) unmatchedByLabel.set(firstLabel, (unmatchedByLabel.get(firstLabel) || 0) + 1);
      else unmatchedByNumber.set(virtualNumber || '—', (unmatchedByNumber.get(virtualNumber || '—') || 0) + 1);
      return;
    }

    const direction = /исход/i.test(row[idx.direction] || '') ? 'out' : 'in';
    const isAnswered = row[idx.status] === 'Принятый';
    const callerPhone = row[idx.callerPhone] || null;
    const startedAt = toDbDateString(row[idx.startTime]);
    if (!startedAt) { console.warn(`Пропущена строка с нераспознанной датой: "${row[idx.startTime]}" (id=${uisCallId})`); return; }

    let status;
    if (direction === 'in') status = isAnswered ? 'imported' : 'missed';
    else status = isAnswered ? 'imported' : 'skipped';

    matchedBySalon.set(salon.name, (matchedBySalon.get(salon.name) || 0) + 1);

    if (dryRun) { inserted++; return; }

    const clientId = callerPhone ? findOrCreateClient(callerPhone) : null;
    insertStmt.run(
      salon.id, clientId, uisCallId, direction, callerPhone, virtualNumber || null,
      startedAt, durationToSeconds(row[idx.talkDuration]), isAnswered ? 1 : 0,
      row[idx.recordingUrl] || null, status
    );
    inserted++;
  };

  if (dryRun) {
    dataRows.forEach(runOne);
  } else {
    db.transaction(() => dataRows.forEach(runOne))();
  }

  console.log(`\n${dryRun ? '[СУХОЙ ПРОГОН, ничего не сохранено]\n' : ''}Готово: обработано ${dataRows.length}, ${dryRun ? 'будет добавлено' : 'добавлено'} ${inserted}, уже были в базе (пропущены) ${duplicates}, исключённых номеров ${excluded}.`);

  if (matchedBySalon.size) {
    console.log('\nПо салонам:');
    for (const [name, count] of matchedBySalon) console.log(`  ${name}: ${count}`);
  }
  if (unmatchedByLabel.size) {
    console.log('\nНепривязанные метки UIS (добавьте нужному салону через "Метки UIS" и запустите импорт ещё раз):');
    for (const [label, count] of unmatchedByLabel) console.log(`  "${label}": ${count}`);
  }
  if (unmatchedByNumber.size) {
    console.log('\nНепривязанные номера (без метки, добавьте в "Салоны" → "Номера" или в "Общие номера меню"):');
    for (const [num, count] of unmatchedByNumber) console.log(`  ${num}: ${count}`);
  }
}

main().catch(err => { console.error('Ошибка импорта:', err); process.exit(1); });
