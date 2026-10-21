// Телефоны, время и известная схема рекламных номеров МегаФон ВАТС.

const db = require('../db');

function normalizePhone(raw) {
  let digits = String(raw || '').replace(/\D/g, '');
  if (!digits) return '';
  if (digits.length === 11 && digits.startsWith('8')) digits = '7' + digits.slice(1);
  if (digits.length === 10) digits = '7' + digits;
  return digits;
}

// последние 10 цифр — так совпадают '+7 926…', '8926…' и номер клиента с
// префиксом доп.-линии МегаФона (1079/2079/3079 + 9 цифр)
function phoneKey(raw) {
  const digits = String(raw || '').replace(/\D/g, '');
  return digits.length >= 10 ? digits.slice(-10) : digits;
}

// МегаФон всегда присылает в diversion ОСНОВНОЙ номер рекламной группы, а на
// какую из 4 линий позвонили на самом деле, видно только по номеру клиента:
// для доп.1/2/3 перед последними 9 цифрами стоит префикс 1079/2079/3079.
const ROLE_LABELS = { 0: 'основной', 1: 'доп.1', 2: 'доп.2', 3: 'доп.3' };
const GROUPS = [
  ['8 марта', [
    ['79396091003', '79326380338', '79221902791', '79326377250'],
    ['79226029643', '79222997068', '79326385207', '79326382058'],
    ['79327008406', '79222997098', '79326377235', '79326386453'],
    ['79327008385', '79222998066', '79326379535', '79326378277']
  ]],
  ['Юмашева', [
    ['79327008405', '79326386164', '79222991540', '79326385053'],
    ['79327008409', '79326379790', '79222909290', '79326387646'],
    ['79327008393', '79326379791', '79222905035', '79221909671'],
    ['79327008397', '79222991235', '79326376098', '79326382184'],
    ['79327008399', '79326378614', '79326379015', '79326379775']
  ]],
  ['Чайковского', [
    ['79327008384', '79326380421', '79326381687', '79326379765'],
    ['79327008407', '79326384029', '79326382077', '79326374727'],
    ['79327008408', '79326377856', '79222998482', '79326381050'],
    ['79327008410', '79326379793', '79326379798', '79326386068']
  ]]
];
const GROUPS_BY_MAIN = new Map();
const SALON_BY_NUMBER = new Map();
for (const [salon, groups] of GROUPS) {
  groups.forEach((numbers, i) => {
    GROUPS_BY_MAIN.set(numbers[0], { salon, group: i + 1, numbers });
    for (const n of numbers) SALON_BY_NUMBER.set(n, salon);
  });
}
const SALONS = GROUPS.map(([salon]) => salon);

// прямые номера салонов — на них переадресуются все анкеты салона (определено
// по полю user вебхуков МегаФона: chayka / 8_marta / yumasheva)
const SALON_LINES = { '79994994776': 'Чайковского', '79221397135': '8 марта', '79994993114': 'Юмашева' };
for (const [phone, salon] of Object.entries(SALON_LINES)) SALON_BY_NUMBER.set(phone, salon);

// заводит прямые номера салонов и подписывает салон у известных номеров
function syncKnownNumbers() {
  db.transaction(() => {
    for (const [phone, salon] of Object.entries(SALON_LINES)) {
      db.prepare(`INSERT OR IGNORE INTO fw_numbers (name, phone, comment, salon, kind) VALUES (?, ?, ?, ?, 'salon')`)
        .run(`Салон ${salon}`, phone, 'Прямой номер салона — на него переадресуются анкеты', salon);
      db.prepare(`UPDATE fw_numbers SET kind = 'salon', salon = COALESCE(salon, ?) WHERE phone = ?`).run(salon, phone);
    }
    const update = db.prepare('UPDATE fw_numbers SET salon = ? WHERE id = ?');
    for (const n of db.prepare('SELECT id, phone FROM fw_numbers WHERE salon IS NULL').all()) {
      if (SALON_BY_NUMBER.has(n.phone)) update.run(SALON_BY_NUMBER.get(n.phone), n.id);
    }
  })();
}

function lineRole(clientRaw) {
  const digits = String(clientRaw || '').replace(/\D/g, '');
  if (digits.length === 13 && digits.slice(1, 4) === '079' && '123'.includes(digits[0])) return Number(digits[0]);
  return 0;
}

// настоящий номер клиента без префикса доп.-линии
function realClientPhone(clientRaw) {
  const digits = String(clientRaw || '').replace(/\D/g, '');
  return lineRole(digits) ? '79' + digits.slice(-9) : normalizePhone(digits);
}

function resolveCall(diversionRaw, clientRaw) {
  const diversion = normalizePhone(diversionRaw);
  if (SALON_LINES[diversion]) {
    const salon = SALON_LINES[diversion];
    return { salon, group: 0, role: -1, role_label: 'прямой номер', number: diversion, label: `${salon} — прямой номер салона` };
  }
  const info = GROUPS_BY_MAIN.get(diversion);
  if (!info) return null;
  const role = lineRole(clientRaw);
  return {
    salon: info.salon, group: info.group, role, role_label: ROLE_LABELS[role],
    number: info.numbers[role],
    label: `${info.salon} — группа ${info.group} — ${ROLE_LABELS[role]}`
  };
}

function getSettings() {
  return db.prepare('SELECT * FROM fw_settings WHERE id = 1').get();
}

function excludedKeys() {
  return new Set(db.prepare('SELECT key FROM fw_excluded').all().map(r => r.key));
}

const toDbString = d => d.toISOString().slice(0, 19).replace('T', ' ');
const fromDbString = s => new Date(s.replace(' ', 'T') + 'Z');

// смещение часового пояса (мс) в данный момент — через Intl, без библиотек
function tzOffsetMs(tz, date) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit'
  }).formatToParts(date).map(p => [p.type, p.value]));
  const asUtc = Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute, +parts.second);
  return asUtc - Math.floor(date.getTime() / 1000) * 1000;
}

function safeTz(tz) {
  try { new Intl.DateTimeFormat('en-US', { timeZone: tz }); return tz; } catch { return 'UTC'; }
}

// "YYYY-MM-DD HH:MM:SS" в UTC -> локальная дата/время в поясе tz
function toLocal(dbString, tz) {
  if (!dbString) return null;
  const d = fromDbString(dbString);
  return toDbString(new Date(d.getTime() + tzOffsetMs(tz, d)));
}

// локальные даты периода (ГГГГ-ММ-ДД) -> границы в UTC для сравнения строк в SQL;
// по умолчанию последние defaultDays дней включая сегодня
function resolvePeriod(dateFrom, dateTo, tz, defaultDays = 30) {
  const dateRe = /^\d{4}-\d{2}-\d{2}$/;
  const todayLocal = toLocal(toDbString(new Date()), tz).slice(0, 10);
  const shift = (day, n) => new Date(Date.parse(day + 'T00:00:00Z') + n * 86400000).toISOString().slice(0, 10);
  let from = dateRe.test(dateFrom || '') ? dateFrom : shift(todayLocal, -(defaultDays - 1));
  let to = dateRe.test(dateTo || '') ? dateTo : todayLocal;
  if (from > to) [from, to] = [to, from];
  const localToUtc = (day, time) => {
    const naive = new Date(`${day}T${time}Z`);
    return toDbString(new Date(naive.getTime() - tzOffsetMs(tz, naive)));
  };
  return { from, to, utcFrom: localToUtc(from, '00:00:00'), utcTo: localToUtc(to, '23:59:59') };
}

function daysBetween(from, to) {
  const days = [];
  for (let t = Date.parse(from + 'T00:00:00Z'); t <= Date.parse(to + 'T00:00:00Z'); t += 86400000) {
    days.push(new Date(t).toISOString().slice(0, 10));
  }
  return days;
}

module.exports = {
  normalizePhone, phoneKey, lineRole, realClientPhone, resolveCall, ROLE_LABELS, SALONS, syncKnownNumbers,
  getSettings, excludedKeys, toDbString, toLocal, resolvePeriod, daysBetween, safeTz
};
