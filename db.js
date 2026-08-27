const path = require('path');
const fs = require('fs');
const Database = require('better-sqlite3');
const bcrypt = require('bcryptjs');

const DATA_DIR = path.join(__dirname, 'data');
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

const db = new Database(path.join(DATA_DIR, 'salons.db'));
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

db.exec(`
-- ===== Пользователи (учётные записи) =====
-- role 'admin' = владелец сети (полный доступ), 'staff' = логин администратора
-- объекта (только страница «Гости» своего объекта, см. admins.user_id)
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  full_name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'staff',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ===== Объекты сети: салоны и сауна =====
CREATE TABLE IF NOT EXISTS salons (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  address TEXT,
  phone TEXT NOT NULL,              -- основной виртуальный номер UIS объекта
  uis_line_id TEXT,
  type TEXT NOT NULL DEFAULT 'salon', -- salon | sauna
  checklist_mode TEXT NOT NULL DEFAULT 'template', -- template | custom (отвязан от шаблона)
  active INTEGER NOT NULL DEFAULT 1,  -- 0 = архив (удаление объекта = архивация)
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Доп. номера, привязанные к тому же объекту (например, номера с разных
-- рекламных площадок с переадресацией на салон) — основной номер из salons.phone
-- участвует в сопоставлении наравне с этими.
CREATE TABLE IF NOT EXISTS salon_phone_numbers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  salon_id INTEGER NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
  phone TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_salon_phone_numbers_salon ON salon_phone_numbers(salon_id);

-- ===== Администраторы =====
-- Отдельно от users: администратор существует как метка для ИИ даже без логина.
-- Привязан ровно к одному объекту. user_id заполняется, только если владелец
-- выдал доступ к странице «Гости».
CREATE TABLE IF NOT EXISTS admins (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  salon_id INTEGER NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'confirmed', -- confirmed | unconfirmed
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  callout_phone TEXT, -- номер в приложении UIS, для клик-звонка
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_admins_salon ON admins(salon_id);

-- ===== Чек-лист-шаблоны =====
-- salon_id IS NULL  -> пункт общего шаблона (template = 'salon' | 'sauna')
-- salon_id указан   -> пункт конкретного объекта (добавка поверх шаблона,
--                      либо — если у объекта checklist_mode='custom' — часть
--                      его приватного списка после отвязки от шаблона)
CREATE TABLE IF NOT EXISTS checklist_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  template TEXT,                    -- 'salon' | 'sauna' | NULL (для salon_id-пунктов не важен)
  salon_id INTEGER REFERENCES salons(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- отключить конкретный пункт шаблона для конкретного объекта (объект остаётся на шаблоне)
CREATE TABLE IF NOT EXISTS checklist_overrides (
  salon_id INTEGER NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL REFERENCES checklist_items(id) ON DELETE CASCADE,
  disabled INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (salon_id, item_id)
);

-- ===== Клиенты =====
-- Склейка по нормализованному номеру телефона по всей сети.
CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phone TEXT UNIQUE NOT NULL,
  name TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ===== Звонки =====
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  salon_id INTEGER NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
  client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
  uis_call_id TEXT UNIQUE,
  direction TEXT NOT NULL DEFAULT 'in', -- in | out
  caller_phone TEXT,
  started_at TEXT NOT NULL,
  duration_sec INTEGER NOT NULL DEFAULT 0,
  is_answered INTEGER NOT NULL DEFAULT 0,
  recording_url TEXT,
  status TEXT NOT NULL DEFAULT 'new', -- new | processing | done | error | missed | skipped

  -- пропущенные / перезвоны (актуально для is_answered=0, direction='in')
  callback_call_id INTEGER REFERENCES calls(id) ON DELETE SET NULL,
  callback_status TEXT,   -- on_time | late | none
  callback_minutes INTEGER,

  transcript TEXT,
  detected_admin_name TEXT,
  matched_admin_id INTEGER REFERENCES admins(id) ON DELETE SET NULL,

  checklist_results TEXT, -- JSON [{item_id, text, state: yes|partial|no, evidence}]
  checklist_score REAL,
  checklist_total INTEGER,

  summary TEXT,
  strengths TEXT,
  weaknesses TEXT,
  recommendations TEXT,
  retention_advice TEXT,
  outcome TEXT, -- booking | interest | callback | refusal | spam

  error_message TEXT,
  processed_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_calls_salon ON calls(salon_id);
CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status);
CREATE INDEX IF NOT EXISTS idx_calls_client ON calls(client_id);
CREATE INDEX IF NOT EXISTS idx_calls_started ON calls(started_at);

-- ===== Записи (bookings) =====
-- Создаются автоматически, когда ИИ находит в разговоре подтверждённую запись.
CREATE TABLE IF NOT EXISTS bookings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  salon_id INTEGER NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
  call_id INTEGER REFERENCES calls(id) ON DELETE SET NULL,
  scheduled_at TEXT NOT NULL, -- дата/время записи (текст из разговора + попытка ISO-парсинга)
  scheduled_date TEXT,        -- YYYY-MM-DD, для выборок на день
  note TEXT,
  status TEXT NOT NULL DEFAULT 'upcoming', -- upcoming | arrived | no_show | cancelled
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bookings_salon_date ON bookings(salon_id, scheduled_date);

-- ===== Визиты =====
-- Факт «дошёл/не дошёл»: либо привязан к записи, либо самостоятельный (гость с улицы).
CREATE TABLE IF NOT EXISTS visits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  salon_id INTEGER NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
  booking_id INTEGER REFERENCES bookings(id) ON DELETE SET NULL,
  visited_date TEXT NOT NULL, -- YYYY-MM-DD
  arrived INTEGER NOT NULL DEFAULT 1,
  source TEXT NOT NULL DEFAULT 'walkin', -- booking | walkin
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_visits_client ON visits(client_id);
CREATE INDEX IF NOT EXISTS idx_visits_salon_date ON visits(salon_id, visited_date);

-- ===== Закрытие дня на странице «Гости» =====
CREATE TABLE IF NOT EXISTS day_closures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  salon_id INTEGER NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
  closed_date TEXT NOT NULL,
  closed_at TEXT NOT NULL DEFAULT (datetime('now')),
  closed_by INTEGER REFERENCES users(id),
  UNIQUE(salon_id, closed_date)
);

-- ===== Настройки ИИ =====
CREATE TABLE IF NOT EXISTS ai_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  openai_api_key TEXT,
  company_context TEXT,
  transcribe_model TEXT NOT NULL DEFAULT 'gpt-4o-mini-transcribe',
  analysis_model TEXT NOT NULL DEFAULT 'gpt-5.6-luna',
  rub_per_usd REAL NOT NULL DEFAULT 90
);
INSERT OR IGNORE INTO ai_settings (id, rub_per_usd) VALUES (1, 90);

CREATE TABLE IF NOT EXISTS ai_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  call_id INTEGER REFERENCES calls(id) ON DELETE SET NULL,
  kind TEXT NOT NULL, -- transcribe | analysis | report
  cost_usd REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ===== Телефония UIS =====
CREATE TABLE IF NOT EXISTS telephony_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  uis_login TEXT,
  uis_api_key TEXT,
  poll_interval_sec INTEGER NOT NULL DEFAULT 300,
  callback_window_min INTEGER NOT NULL DEFAULT 5,
  enabled INTEGER NOT NULL DEFAULT 0,
  last_poll_at TEXT
);
INSERT OR IGNORE INTO telephony_settings (id) VALUES (1);

CREATE TABLE IF NOT EXISTS call_out_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  outbound_virtual_number TEXT,
  enabled INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO call_out_settings (id) VALUES (1);
`);

// первичный владелец, если пользователей ещё нет
const usersCount = db.prepare('SELECT COUNT(*) AS c FROM users').get().c;
if (usersCount === 0) {
  const defaultPassword = process.env.ADMIN_DEFAULT_PASSWORD || 'admin123';
  const hash = bcrypt.hashSync(defaultPassword, 10);
  db.prepare(`INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, 'admin')`)
    .run('admin', hash, 'Владелец');
  console.log(`[db] Создан первичный владелец: логин "admin", пароль "${defaultPassword}" (смените после первого входа)`);
}

// стартовые шаблоны чек-листов, если пусто
const checklistCount = db.prepare('SELECT COUNT(*) AS c FROM checklist_items').get().c;
if (checklistCount === 0) {
  const salonDefaults = [
    'Представилась по имени',
    'Выяснила запрос (вид массажа, проблемные зоны, опыт/противопоказания)',
    'Назвала цену и длительность',
    'Предложила ближайшее время записи',
    'Предложила альтернативу, если время не подходит',
    'Уточнила имя клиента',
    'Подтвердила запись (дата, время, адрес)',
    'Вежливо завершила разговор'
  ];
  const saunaDefaults = [
    'Представилась',
    'Уточнила дату/время/количество человек',
    'Назвала тариф и что входит',
    'Рассказала про доп. услуги',
    'Предложила забронировать',
    'Подтвердила детали',
    'Вежливо завершила разговор'
  ];
  const stmt = db.prepare('INSERT INTO checklist_items (template, salon_id, text, position) VALUES (?, NULL, ?, ?)');
  salonDefaults.forEach((text, i) => stmt.run('salon', text, i));
  saunaDefaults.forEach((text, i) => stmt.run('sauna', text, i));
}

module.exports = db;
