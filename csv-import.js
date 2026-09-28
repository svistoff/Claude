// Разбор и импорт CSV-выгрузки отчёта UIS ("Название отчета: Звонки") —
// общая логика для CLI-скрипта (scripts/import-uis-csv.js) и веб-формы
// в Настройках (POST /api/settings/telephony/import-csv). Нужно, когда
// обычный опрос через Data API недоступен (например, упёрлись в дневной
// лимит запросов), а звонки при этом нужно учесть в статистике.
//
// Резолюция салона — та же, что и в telephony.js ingestCalls: сначала прямое
// совпадение по номеру (getSalonPhoneMap), затем бесплатная метка "Сотрудники
// разговора" (аналог employees из get.calls_report) через salon_uis_labels.
// Звонки сохраняются без ИИ-анализа (статус 'imported') — массовый прогон
// через OpenAI для сотен исторических звонков разом не нужен, только цифры
// для статистики (см. дашборд/отчёты — считают по calls независимо от того,
// анализирован звонок ИИ или нет).
//
// Идемпотентно: звонки уникальны по uis_call_id ("Идентификатор сессии
// звонка" из отчёта), уже сохранённые строки просто пропускаются — файл за
// пересекающийся период можно грузить повторно без дублей.

const db = require('./db');
const {
  normalizePhone, findOrCreateClient, getSalonPhoneMap,
  getExcludedNumberSet, getExcludedCallerNumberSet, getActionNameSalonMap
} = require('./lib');

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

// dryRun=true ничего не пишет в базу, только считает, что было бы сделано.
function importUisCsv(text, { dryRun = false } = {}) {
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

  const salonsById = new Map(db.prepare('SELECT * FROM salons WHERE active = 1').all().map(s => [s.id, s]));
  const phoneMap = getSalonPhoneMap();
  const excludedNumbers = getExcludedNumberSet();
  const excludedCallerNumbers = getExcludedCallerNumberSet();
  const actionNameMap = getActionNameSalonMap();

  const insertStmt = db.prepare(`
    INSERT INTO calls (salon_id, client_id, uis_call_id, direction, caller_phone, dialed_number, started_at, duration_sec, is_answered, recording_url, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);
  const existsStmt = db.prepare('SELECT id FROM calls WHERE uis_call_id = ?');

  let inserted = 0, duplicates = 0, excluded = 0, badDates = 0;
  const matchedBySalon = new Map();
  const unmatchedByLabel = new Map();
  const unmatchedByNumber = new Map();

  const runOne = (row) => {
    const uisCallId = row[idx.sessionId];
    if (existsStmt.get(uisCallId)) { duplicates++; return; }

    const callerNorm = normalizePhone(row[idx.callerPhone]);
    if (callerNorm && excludedCallerNumbers.has(callerNorm)) { excluded++; return; }

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
    if (!startedAt) { badDates++; return; }

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

  if (dryRun) dataRows.forEach(runOne);
  else db.transaction(() => dataRows.forEach(runOne))();

  return {
    totalRows: dataRows.length,
    inserted,
    duplicates,
    excluded,
    badDates,
    matchedBySalon: Array.from(matchedBySalon, ([name, count]) => ({ name, count })),
    unmatchedByLabel: Array.from(unmatchedByLabel, ([label, count]) => ({ label, count })),
    unmatchedByNumber: Array.from(unmatchedByNumber, ([number, count]) => ({ number, count }))
  };
}

module.exports = { importUisCsv };
