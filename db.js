const path = require('path');
const fs = require('fs');
const Database = require('better-sqlite3');
const bcrypt = require('bcryptjs');

const DATA_DIR = path.join(__dirname, 'data');
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

const db = new Database(path.join(DATA_DIR, 'crm.db'));
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

db.exec(`
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  full_name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'staff', -- admin | staff
  phone TEXT, -- номер сотрудника в приложении UIS, нужен для клик-звонка
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Сотрудник может работать в нескольких салонах (many-to-many)
CREATE TABLE IF NOT EXISTS user_salons (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  salon_id INTEGER NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, salon_id)
);

CREATE TABLE IF NOT EXISTS salons (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  address TEXT,
  phone TEXT NOT NULL, -- номер, который слушаем (UIS virtual number)
  uis_line_id TEXT,    -- id виртуальной линии/номера в UIS, если нужен для фильтра отчёта
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Общий шаблон чек-листа (salon_id IS NULL) + переопределения на конкретный салон (salon_id указан)
CREATE TABLE IF NOT EXISTS checklist_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  salon_id INTEGER REFERENCES salons(id) ON DELETE CASCADE, -- NULL = глобальный пункт
  text TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Позволяет отключить конкретный глобальный пункт чек-листа для конкретного салона
-- (переопределение "общий шаблон, но не для этого салона")
CREATE TABLE IF NOT EXISTS checklist_overrides (
  salon_id INTEGER NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL REFERENCES checklist_items(id) ON DELETE CASCADE,
  disabled INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (salon_id, item_id)
);

CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  salon_id INTEGER NOT NULL REFERENCES salons(id) ON DELETE CASCADE,
  uis_call_id TEXT UNIQUE,
  direction TEXT NOT NULL DEFAULT 'in', -- in | out
  caller_phone TEXT,
  started_at TEXT NOT NULL,
  duration_sec INTEGER NOT NULL DEFAULT 0,
  is_answered INTEGER NOT NULL DEFAULT 0,
  recording_url TEXT, -- временная ссылка в UIS, не хранится физически
  status TEXT NOT NULL DEFAULT 'new', -- new | processing | done | error | skipped
  transcript TEXT,
  detected_staff_name TEXT,   -- как ИИ услышал имя ("Ольга")
  matched_user_id INTEGER REFERENCES users(id), -- сопоставление со справочником сотрудников
  summary TEXT,
  strengths TEXT,
  weaknesses TEXT,
  recommendations TEXT,
  checklist_results TEXT, -- JSON [{item_id, text, passed, evidence}]
  error_message TEXT,
  processed_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_calls_salon ON calls(salon_id);
CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status);

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
  kind TEXT NOT NULL, -- transcribe | analysis
  cost_usd REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS telephony_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  uis_login TEXT,
  uis_api_key TEXT,
  poll_interval_sec INTEGER NOT NULL DEFAULT 300,
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

// первичный админ, если базы ещё нет пользователей
const usersCount = db.prepare('SELECT COUNT(*) AS c FROM users').get().c;
if (usersCount === 0) {
  const defaultPassword = process.env.ADMIN_DEFAULT_PASSWORD || 'admin123';
  const hash = bcrypt.hashSync(defaultPassword, 10);
  db.prepare(`INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, 'admin')`)
    .run('admin', hash, 'Администратор');
  console.log(`[db] Создан первичный админ: логин "admin", пароль "${defaultPassword}" (смените после первого входа)`);
}

// дефолтный глобальный чек-лист, если пуст
const checklistCount = db.prepare('SELECT COUNT(*) AS c FROM checklist_items').get().c;
if (checklistCount === 0) {
  const defaults = [
    'Поздоровался и представился по имени',
    'Уточнил, был ли клиент раньше',
    'Предложил конкретное время записи',
    'Рассказал про акции/абонементы',
    'Уточнил пожелания по мастеру/виду массажа',
    'Повторил дату и время записи в конце разговора'
  ];
  const stmt = db.prepare('INSERT INTO checklist_items (salon_id, text, position) VALUES (NULL, ?, ?)');
  defaults.forEach((text, i) => stmt.run(text, i));
}

module.exports = db;
