const express = require('express');
const cookieParser = require('cookie-parser');
const bcrypt = require('bcryptjs');
const path = require('path');
const XLSX = require('xlsx');
const db = require('./db');
const auth = require('./auth');
const { getEffectiveChecklist, adminForUser, canAccessSalon, findOrCreateClient, normalizePhone } = require('./lib');

const app = express();
const PORT = process.env.PORT || 3002;

app.use(express.json());
app.use(cookieParser());
app.use(express.static(path.join(__dirname, 'public')));

// ---------- auth ----------
app.post('/api/login', auth.login);
app.post('/api/logout', auth.logout);
app.get('/api/me', auth.requireAuth, (req, res) => {
  const admin = req.user.role === 'staff' ? adminForUser(req.user.id) : null;
  res.json({ ...req.user, salon_id: admin ? admin.salon_id : null, admin_id: admin ? admin.id : null });
});

app.use('/api', auth.requireAuth);

function formatCall(c) {
  return { ...c, checklist_results: c.checklist_results ? JSON.parse(c.checklist_results) : null };
}

// ================= САЛОНЫ / ОБЪЕКТЫ =================
app.get('/api/salons', (req, res) => {
  if (req.user.role === 'admin') {
    const includeArchived = req.query.all === '1';
    const rows = includeArchived
      ? db.prepare('SELECT * FROM salons ORDER BY active DESC, name').all()
      : db.prepare('SELECT * FROM salons WHERE active = 1 ORDER BY name').all();
    return res.json(rows);
  }
  const admin = adminForUser(req.user.id);
  if (!admin) return res.json([]);
  res.json(db.prepare('SELECT * FROM salons WHERE id = ?').all(admin.salon_id));
});

app.post('/api/salons', auth.requireAdmin, (req, res) => {
  const { name, address, phone, uis_line_id, type } = req.body || {};
  if (!name || !phone) return res.status(400).json({ error: 'Название и телефон обязательны' });
  const info = db.prepare('INSERT INTO salons (name, address, phone, uis_line_id, type) VALUES (?, ?, ?, ?, ?)')
    .run(name.trim(), address || null, phone.trim(), uis_line_id || null, type === 'sauna' ? 'sauna' : 'salon');
  res.json(db.prepare('SELECT * FROM salons WHERE id = ?').get(info.lastInsertRowid));
});

app.put('/api/salons/:id', auth.requireAdmin, (req, res) => {
  const salon = db.prepare('SELECT * FROM salons WHERE id = ?').get(req.params.id);
  if (!salon) return res.status(404).json({ error: 'Объект не найден' });
  const { name, address, phone, uis_line_id, type, active, uis_action_name } = req.body || {};
  db.prepare('UPDATE salons SET name=?, address=?, phone=?, uis_line_id=?, type=?, active=?, uis_action_name=? WHERE id=?')
    .run(
      name ?? salon.name, address ?? salon.address, phone ?? salon.phone,
      uis_line_id ?? salon.uis_line_id, type === 'sauna' || type === 'salon' ? type : salon.type,
      active === undefined ? salon.active : (active ? 1 : 0),
      uis_action_name === undefined ? salon.uis_action_name : (uis_action_name || null),
      salon.id
    );
  res.json(db.prepare('SELECT * FROM salons WHERE id = ?').get(salon.id));
});

// удаление объекта = архивация (номер освобождается, история сохраняется)
app.delete('/api/salons/:id', auth.requireAdmin, (req, res) => {
  const salon = db.prepare('SELECT * FROM salons WHERE id = ?').get(req.params.id);
  if (!salon) return res.status(404).json({ error: 'Объект не найден' });
  db.prepare('UPDATE salons SET active = 0 WHERE id = ?').run(salon.id);
  res.json({ ok: true, archived: true });
});

// переключить объект между общим шаблоном чек-листа и приватным списком
app.put('/api/salons/:id/checklist-mode', auth.requireAdmin, (req, res) => {
  const salon = db.prepare('SELECT * FROM salons WHERE id = ?').get(req.params.id);
  if (!salon) return res.status(404).json({ error: 'Объект не найден' });
  const mode = req.body?.mode === 'custom' ? 'custom' : 'template';

  if (mode === 'custom' && salon.checklist_mode !== 'custom') {
    // делаем приватный снимок текущего эффективного чек-листа объекта
    const effective = getEffectiveChecklist(salon);
    const insert = db.prepare('INSERT INTO checklist_items (template, salon_id, text, position) VALUES (NULL, ?, ?, ?)');
    effective.forEach((item, i) => insert.run(salon.id, item.text, i));
  }
  if (mode === 'template' && salon.checklist_mode === 'custom') {
    // прячем приватные пункты объекта, чтобы не задваивались с шаблоном при возврате
    db.prepare('UPDATE checklist_items SET active = 0 WHERE salon_id = ?').run(salon.id);
  }

  db.prepare('UPDATE salons SET checklist_mode = ? WHERE id = ?').run(mode, salon.id);
  res.json({ ok: true });
});

// доп. номера объекта (например, с разных рекламных площадок с переадресацией на салон) —
// звонки на любой из них будут распознаны как звонки этому объекту, см. telephony.js
app.get('/api/salons/:id/phones', auth.requireAdmin, (req, res) => {
  res.json(db.prepare('SELECT * FROM salon_phone_numbers WHERE salon_id = ? ORDER BY id').all(req.params.id));
});

app.post('/api/salons/:id/phones', auth.requireAdmin, (req, res) => {
  const { phone, note } = req.body || {};
  if (!phone) return res.status(400).json({ error: 'Укажите номер' });
  const info = db.prepare('INSERT INTO salon_phone_numbers (salon_id, phone, note) VALUES (?, ?, ?)')
    .run(req.params.id, phone.trim(), note || null);
  res.json(db.prepare('SELECT * FROM salon_phone_numbers WHERE id = ?').get(info.lastInsertRowid));
});

app.delete('/api/salons/:salonId/phones/:phoneId', auth.requireAdmin, (req, res) => {
  db.prepare('DELETE FROM salon_phone_numbers WHERE id = ? AND salon_id = ?').run(req.params.phoneId, req.params.salonId);
  res.json({ ok: true });
});

// номера с общим голосовым меню на несколько объектов (см. telephony.js resolveSalonByLegs)
app.get('/api/ivr-numbers', auth.requireAdmin, (req, res) => {
  res.json(db.prepare('SELECT * FROM shared_ivr_numbers ORDER BY id').all());
});

app.post('/api/ivr-numbers', auth.requireAdmin, (req, res) => {
  const { phone, note } = req.body || {};
  if (!phone) return res.status(400).json({ error: 'Укажите номер' });
  const info = db.prepare('INSERT INTO shared_ivr_numbers (phone, note) VALUES (?, ?)').run(phone.trim(), note || null);
  res.json(db.prepare('SELECT * FROM shared_ivr_numbers WHERE id = ?').get(info.lastInsertRowid));
});

app.delete('/api/ivr-numbers/:id', auth.requireAdmin, (req, res) => {
  db.prepare('DELETE FROM shared_ivr_numbers WHERE id = ?').run(req.params.id);
  res.json({ ok: true });
});

// ================= АДМИНИСТРАТОРЫ =================
app.get('/api/admins', (req, res) => {
  let salonId = req.query.salon_id ? Number(req.query.salon_id) : null;
  if (req.user.role !== 'admin') {
    const admin = adminForUser(req.user.id);
    if (!admin) return res.json([]);
    salonId = admin.salon_id;
  }
  const status = req.query.status;
  const conditions = [];
  const params = [];
  if (salonId) { conditions.push('a.salon_id = ?'); params.push(salonId); }
  if (status) { conditions.push('a.status = ?'); params.push(status); }
  const where = conditions.length ? 'WHERE ' + conditions.join(' AND ') : '';
  const rows = db.prepare(`
    SELECT a.*, s.name AS salon_name, u.username AS login_username
    FROM admins a JOIN salons s ON s.id = a.salon_id
    LEFT JOIN users u ON u.id = a.user_id
    ${where} ORDER BY a.status DESC, a.name
  `).all(...params);
  res.json(rows);
});

app.post('/api/admins', auth.requireAdmin, (req, res) => {
  const { salon_id, name } = req.body || {};
  if (!salon_id || !name) return res.status(400).json({ error: 'Укажите объект и имя администратора' });
  const info = db.prepare(`INSERT INTO admins (salon_id, name, status) VALUES (?, ?, 'confirmed')`).run(salon_id, name.trim());
  res.json(db.prepare('SELECT * FROM admins WHERE id = ?').get(info.lastInsertRowid));
});

app.put('/api/admins/:id', auth.requireAdmin, (req, res) => {
  const admin = db.prepare('SELECT * FROM admins WHERE id = ?').get(req.params.id);
  if (!admin) return res.status(404).json({ error: 'Администратор не найден' });
  const { name, callout_phone } = req.body || {};
  db.prepare('UPDATE admins SET name=?, callout_phone=? WHERE id=?')
    .run(name ?? admin.name, callout_phone ?? admin.callout_phone, admin.id);
  res.json(db.prepare('SELECT * FROM admins WHERE id = ?').get(admin.id));
});

app.post('/api/admins/:id/confirm', auth.requireAdmin, (req, res) => {
  db.prepare(`UPDATE admins SET status = 'confirmed' WHERE id = ?`).run(req.params.id);
  res.json({ ok: true });
});

// отклонить неподтверждённого (ИИ ошибся/выдумал имя) — запись удаляется,
// у звонков, где он был указан, метка сотрётся автоматически
app.delete('/api/admins/:id', auth.requireAdmin, (req, res) => {
  db.prepare('DELETE FROM admins WHERE id = ?').run(req.params.id);
  res.json({ ok: true });
});

// выдать/отозвать доступ к странице «Гости»
app.put('/api/admins/:id/login', auth.requireAdmin, (req, res) => {
  const admin = db.prepare('SELECT * FROM admins WHERE id = ?').get(req.params.id);
  if (!admin) return res.status(404).json({ error: 'Администратор не найден' });
  const { username, password } = req.body || {};
  if (!username || !password) return res.status(400).json({ error: 'Укажите логин и пароль' });

  if (admin.user_id) {
    db.prepare('UPDATE users SET username=?, password_hash=? WHERE id=?')
      .run(username.trim(), bcrypt.hashSync(password, 10), admin.user_id);
  } else {
    const exists = db.prepare('SELECT 1 FROM users WHERE username = ?').get(username);
    if (exists) return res.status(400).json({ error: 'Такой логин уже занят' });
    const info = db.prepare(`INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, 'staff')`)
      .run(username.trim(), bcrypt.hashSync(password, 10), admin.name);
    db.prepare('UPDATE admins SET user_id = ? WHERE id = ?').run(info.lastInsertRowid, admin.id);
  }
  res.json({ ok: true });
});

app.delete('/api/admins/:id/login', auth.requireAdmin, (req, res) => {
  const admin = db.prepare('SELECT * FROM admins WHERE id = ?').get(req.params.id);
  if (!admin || !admin.user_id) return res.status(404).json({ error: 'Доступа нет' });
  db.prepare('UPDATE users SET active = 0 WHERE id = ?').run(admin.user_id);
  db.prepare('UPDATE admins SET user_id = NULL WHERE id = ?').run(admin.id);
  res.json({ ok: true });
});

// ================= ЧЕК-ЛИСТЫ =================
app.get('/api/checklist', (req, res) => {
  const salonId = req.query.salon_id ? Number(req.query.salon_id) : null;
  if (salonId) {
    if (!canAccessSalon(req.user, salonId)) return res.status(403).json({ error: 'Нет доступа к объекту' });
    const salon = db.prepare('SELECT * FROM salons WHERE id = ?').get(salonId);
    return res.json(getEffectiveChecklist(salon));
  }
  if (req.user.role !== 'admin') return res.status(403).json({ error: 'Укажите salon_id' });
  const template = req.query.template === 'sauna' ? 'sauna' : 'salon';
  const items = db.prepare('SELECT * FROM checklist_items WHERE template = ? AND salon_id IS NULL ORDER BY position, id').all(template);
  res.json(items);
});

app.post('/api/checklist', auth.requireAdmin, (req, res) => {
  const { text, template, salon_id, position } = req.body || {};
  if (!text) return res.status(400).json({ error: 'Текст пункта обязателен' });
  if (!salon_id && template !== 'salon' && template !== 'sauna') {
    return res.status(400).json({ error: 'Укажите template (salon/sauna) для общего пункта или salon_id для пункта объекта' });
  }
  const info = db.prepare('INSERT INTO checklist_items (template, salon_id, text, position) VALUES (?, ?, ?, ?)')
    .run(salon_id ? null : template, salon_id || null, text.trim(), position || 0);
  res.json(db.prepare('SELECT * FROM checklist_items WHERE id = ?').get(info.lastInsertRowid));
});

app.put('/api/checklist/:id', auth.requireAdmin, (req, res) => {
  const item = db.prepare('SELECT * FROM checklist_items WHERE id = ?').get(req.params.id);
  if (!item) return res.status(404).json({ error: 'Пункт не найден' });
  const { text, position, active } = req.body || {};
  db.prepare('UPDATE checklist_items SET text=?, position=?, active=? WHERE id=?')
    .run(text ?? item.text, position ?? item.position, active === undefined ? item.active : (active ? 1 : 0), item.id);
  res.json(db.prepare('SELECT * FROM checklist_items WHERE id = ?').get(item.id));
});

app.delete('/api/checklist/:id', auth.requireAdmin, (req, res) => {
  db.prepare('DELETE FROM checklist_items WHERE id = ?').run(req.params.id);
  res.json({ ok: true });
});

app.post('/api/checklist/:id/override', auth.requireAdmin, (req, res) => {
  const itemId = Number(req.params.id);
  const { salon_id, disabled } = req.body || {};
  if (!salon_id) return res.status(400).json({ error: 'salon_id обязателен' });
  if (disabled) {
    db.prepare('INSERT OR REPLACE INTO checklist_overrides (salon_id, item_id, disabled) VALUES (?, ?, 1)').run(salon_id, itemId);
  } else {
    db.prepare('DELETE FROM checklist_overrides WHERE salon_id = ? AND item_id = ?').run(salon_id, itemId);
  }
  res.json({ ok: true });
});

// ================= ЗВОНКИ =================
app.get('/api/calls', (req, res) => {
  const conditions = [];
  const params = [];

  if (req.user.role !== 'admin') {
    const admin = adminForUser(req.user.id);
    if (!admin) return res.json([]);
    conditions.push('c.salon_id = ?'); params.push(admin.salon_id);
  } else if (req.query.salon_id) {
    conditions.push('c.salon_id = ?'); params.push(Number(req.query.salon_id));
  }

  if (req.query.admin_id) { conditions.push('c.matched_admin_id = ?'); params.push(Number(req.query.admin_id)); }
  if (req.query.outcome) { conditions.push('c.outcome = ?'); params.push(req.query.outcome); }
  if (req.query.direction) { conditions.push('c.direction = ?'); params.push(req.query.direction); }
  if (req.query.status) { conditions.push('c.status = ?'); params.push(req.query.status); }
  if (req.query.missed === '1') { conditions.push(`c.direction = 'in' AND c.is_answered = 0`); }
  if (req.query.callback_status) { conditions.push('c.callback_status = ?'); params.push(req.query.callback_status); }
  if (req.query.date_from) { conditions.push('c.started_at >= ?'); params.push(req.query.date_from); }
  if (req.query.date_to) { conditions.push('c.started_at <= ?'); params.push(req.query.date_to); }

  const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
  const rows = db.prepare(`
    SELECT c.*, s.name AS salon_name, a.name AS matched_admin_name, cl.name AS client_name
    FROM calls c
    JOIN salons s ON s.id = c.salon_id
    LEFT JOIN admins a ON a.id = c.matched_admin_id
    LEFT JOIN clients cl ON cl.id = c.client_id
    ${where}
    ORDER BY c.started_at DESC
    LIMIT 500
  `).all(...params);

  res.json(rows.map(formatCall));
});

app.get('/api/calls/:id', (req, res) => {
  const call = db.prepare(`
    SELECT c.*, s.name AS salon_name, a.name AS matched_admin_name, cl.name AS client_name, cl.phone AS client_phone_norm
    FROM calls c JOIN salons s ON s.id = c.salon_id
    LEFT JOIN admins a ON a.id = c.matched_admin_id
    LEFT JOIN clients cl ON cl.id = c.client_id
    WHERE c.id = ?
  `).get(req.params.id);
  if (!call) return res.status(404).json({ error: 'Звонок не найден' });
  if (!canAccessSalon(req.user, call.salon_id)) return res.status(403).json({ error: 'Нет доступа' });
  res.json(formatCall(call));
});

app.post('/api/calls/:id/reprocess', (req, res) => {
  const call = db.prepare('SELECT * FROM calls WHERE id = ?').get(req.params.id);
  if (!call) return res.status(404).json({ error: 'Звонок не найден' });
  if (!canAccessSalon(req.user, call.salon_id)) return res.status(403).json({ error: 'Нет доступа' });
  db.prepare(`UPDATE calls SET status='new', error_message=NULL WHERE id=?`).run(call.id);
  const { processCall } = require('./ai-processing');
  processCall(call.id).catch(err => console.error('[reprocess]', err));
  res.json({ ok: true });
});

// ручная коррекция администратора в карточке звонка (ИИ мог ошибиться)
app.put('/api/calls/:id/admin', (req, res) => {
  const call = db.prepare('SELECT * FROM calls WHERE id = ?').get(req.params.id);
  if (!call) return res.status(404).json({ error: 'Звонок не найден' });
  if (!canAccessSalon(req.user, call.salon_id)) return res.status(403).json({ error: 'Нет доступа' });
  const { admin_id } = req.body || {};
  db.prepare('UPDATE calls SET matched_admin_id = ? WHERE id = ?').run(admin_id || null, call.id);
  res.json({ ok: true });
});

// ================= ДАШБОРД =================
app.get('/api/dashboard', auth.requireAdmin, (req, res) => {
  const missedNoCallback = db.prepare(`
    SELECT c.*, s.name AS salon_name FROM calls c JOIN salons s ON s.id = c.salon_id
    WHERE c.direction = 'in' AND c.is_answered = 0 AND c.callback_status = 'none'
    ORDER BY c.started_at DESC LIMIT 50
  `).all();

  const unconfirmedAdmins = db.prepare(`
    SELECT a.*, s.name AS salon_name FROM admins a JOIN salons s ON s.id = a.salon_id
    WHERE a.status = 'unconfirmed' ORDER BY a.created_at DESC
  `).all();

  const today = new Date().toISOString().slice(0, 10);
  const salons = db.prepare('SELECT * FROM salons WHERE active = 1').all();
  const unclosedDays = [];
  for (const s of salons) {
    const closed = db.prepare('SELECT 1 FROM day_closures WHERE salon_id = ? AND closed_date = ?').get(s.id, today);
    if (closed) continue;
    const unmarked = db.prepare(`
      SELECT COUNT(*) AS c FROM bookings
      WHERE salon_id = ? AND scheduled_date = ? AND status = 'upcoming'
    `).get(s.id, today).c;
    if (unmarked > 0) unclosedDays.push({ salon_id: s.id, salon_name: s.name, date: today, unmarked_count: unmarked });
  }

  const todaySummary = salons.map(s => {
    const calls = db.prepare(`SELECT COUNT(*) AS c FROM calls WHERE salon_id = ? AND date(started_at) = ?`).get(s.id, today).c;
    const missed = db.prepare(`SELECT COUNT(*) AS c FROM calls WHERE salon_id = ? AND date(started_at) = ? AND direction='in' AND is_answered=0`).get(s.id, today).c;
    return { salon_id: s.id, salon_name: s.name, calls, missed };
  });

  res.json({ missed_no_callback: missedNoCallback.map(formatCall), unconfirmed_admins: unconfirmedAdmins, unclosed_days: unclosedDays, today_summary: todaySummary });
});

// ================= КЛИЕНТЫ =================
app.get('/api/clients', auth.requireAdmin, (req, res) => {
  const q = req.query.q ? `%${req.query.q}%` : null;
  const rows = db.prepare(`
    SELECT cl.*,
      (SELECT COUNT(*) FROM bookings b WHERE b.client_id = cl.id) AS bookings_count,
      (SELECT COUNT(*) FROM visits v WHERE v.client_id = cl.id AND v.arrived = 1) AS visits_count,
      (SELECT MAX(started_at) FROM calls c WHERE c.client_id = cl.id) AS last_call_at
    FROM clients cl
    ${q ? 'WHERE cl.phone LIKE ? OR cl.name LIKE ?' : ''}
    ORDER BY last_call_at DESC
    LIMIT 500
  `).all(...(q ? [q, q] : []));
  res.json(rows.map(r => ({ ...r, status: clientStatus(r) })));
});

function clientStatus(row) {
  const visits = row.visits_count || 0;
  const lastCallDays = row.last_call_at ? (Date.now() - new Date(row.last_call_at).getTime()) / 86400000 : null;
  if (visits === 0 && !row.bookings_count) return 'Новый';
  if (lastCallDays !== null && lastCallDays > 60) return 'Спящий';
  if (visits >= 3) return 'Постоянный';
  return 'Повторный';
}

app.get('/api/clients/rating', auth.requireAdmin, (req, res) => {
  const type = req.query.type === 'sleeping' ? 'sleeping' : 'top';
  if (type === 'top') {
    const rows = db.prepare(`
      SELECT cl.*, COUNT(v.id) AS visits_count
      FROM clients cl JOIN visits v ON v.client_id = cl.id AND v.arrived = 1
      GROUP BY cl.id ORDER BY visits_count DESC LIMIT 30
    `).all();
    return res.json(rows);
  }
  const rows = db.prepare(`
    SELECT cl.*, MAX(v.visited_date) AS last_visit
    FROM clients cl JOIN visits v ON v.client_id = cl.id AND v.arrived = 1
    GROUP BY cl.id
    HAVING julianday('now') - julianday(last_visit) > 60
    ORDER BY last_visit ASC LIMIT 30
  `).all();
  res.json(rows);
});

app.get('/api/clients/:id', auth.requireAdmin, (req, res) => {
  const client = db.prepare('SELECT * FROM clients WHERE id = ?').get(req.params.id);
  if (!client) return res.status(404).json({ error: 'Клиент не найден' });
  const calls = db.prepare(`
    SELECT c.*, s.name AS salon_name FROM calls c JOIN salons s ON s.id = c.salon_id
    WHERE c.client_id = ? ORDER BY c.started_at DESC
  `).all(client.id).map(formatCall);
  const bookings = db.prepare(`
    SELECT b.*, s.name AS salon_name FROM bookings b JOIN salons s ON s.id = b.salon_id
    WHERE b.client_id = ? ORDER BY b.scheduled_at DESC
  `).all(client.id);
  const visits = db.prepare(`
    SELECT v.*, s.name AS salon_name FROM visits v JOIN salons s ON s.id = v.salon_id
    WHERE v.client_id = ? ORDER BY v.visited_date DESC
  `).all(client.id);
  res.json({ ...client, calls, bookings, visits });
});

// ================= ГОСТИ (страница администратора объекта) =================
function resolveGuestSalonId(req) {
  if (req.user.role === 'admin') return req.query.salon_id ? Number(req.query.salon_id) : null;
  const admin = adminForUser(req.user.id);
  return admin ? admin.salon_id : null;
}

app.get('/api/guest/bookings', (req, res) => {
  const salonId = resolveGuestSalonId(req);
  if (!salonId) return res.status(400).json({ error: 'Не определён объект' });
  if (!canAccessSalon(req.user, salonId)) return res.status(403).json({ error: 'Нет доступа' });

  const range = req.query.range || 'today';
  const today = new Date().toISOString().slice(0, 10);
  const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
  let condition = 'b.scheduled_date = ?';
  let params = [salonId, today];
  if (range === 'tomorrow') params = [salonId, tomorrow];
  if (range === 'upcoming') { condition = 'b.scheduled_date > ?'; params = [salonId, today]; }

  const rows = db.prepare(`
    SELECT b.*, cl.name AS client_name, cl.phone AS client_phone
    FROM bookings b JOIN clients cl ON cl.id = b.client_id
    WHERE b.salon_id = ? AND ${condition}
    ORDER BY b.scheduled_at ASC
  `).all(...params);
  res.json(rows);
});

app.post('/api/guest/bookings/:id/mark', (req, res) => {
  const booking = db.prepare('SELECT * FROM bookings WHERE id = ?').get(req.params.id);
  if (!booking) return res.status(404).json({ error: 'Запись не найдена' });
  if (!canAccessSalon(req.user, booking.salon_id)) return res.status(403).json({ error: 'Нет доступа' });

  const arrived = !!req.body?.arrived;
  db.prepare('UPDATE bookings SET status = ? WHERE id = ?').run(arrived ? 'arrived' : 'no_show', booking.id);

  const today = new Date().toISOString().slice(0, 10);
  const existing = db.prepare('SELECT id FROM visits WHERE booking_id = ?').get(booking.id);
  if (existing) {
    db.prepare('UPDATE visits SET arrived = ? WHERE id = ?').run(arrived ? 1 : 0, existing.id);
  } else {
    db.prepare(`
      INSERT INTO visits (client_id, salon_id, booking_id, visited_date, arrived, source, created_by)
      VALUES (?, ?, ?, ?, ?, 'booking', ?)
    `).run(booking.client_id, booking.salon_id, booking.id, today, arrived ? 1 : 0, req.user.id);
  }
  res.json({ ok: true });
});

// визит без звонка/записи — гость с улицы или постоянный клиент, который не звонит
app.post('/api/guest/visits', (req, res) => {
  const salonId = resolveGuestSalonId(req);
  if (!salonId) return res.status(400).json({ error: 'Не определён объект' });
  if (!canAccessSalon(req.user, salonId)) return res.status(403).json({ error: 'Нет доступа' });

  const { phone, name } = req.body || {};
  if (!phone) return res.status(400).json({ error: 'Укажите телефон гостя' });
  const clientId = findOrCreateClient(phone, name);
  const today = new Date().toISOString().slice(0, 10);
  db.prepare(`
    INSERT INTO visits (client_id, salon_id, visited_date, arrived, source, created_by)
    VALUES (?, ?, ?, 1, 'walkin', ?)
  `).run(clientId, salonId, today, req.user.id);
  res.json({ ok: true });
});

app.post('/api/guest/close-day', (req, res) => {
  const salonId = resolveGuestSalonId(req);
  if (!salonId) return res.status(400).json({ error: 'Не определён объект' });
  if (!canAccessSalon(req.user, salonId)) return res.status(403).json({ error: 'Нет доступа' });
  const today = new Date().toISOString().slice(0, 10);
  db.prepare('INSERT OR REPLACE INTO day_closures (salon_id, closed_date, closed_by) VALUES (?, ?, ?)').run(salonId, today, req.user.id);
  res.json({ ok: true });
});

app.get('/api/guest/day-status', (req, res) => {
  const salonId = resolveGuestSalonId(req);
  if (!salonId) return res.status(400).json({ error: 'Не определён объект' });
  if (!canAccessSalon(req.user, salonId)) return res.status(403).json({ error: 'Нет доступа' });
  const today = new Date().toISOString().slice(0, 10);
  const closed = !!db.prepare('SELECT 1 FROM day_closures WHERE salon_id = ? AND closed_date = ?').get(salonId, today);
  res.json({ closed, date: today });
});

// ================= НАСТРОЙКИ ИИ =================
app.get('/api/settings/ai', auth.requireAdmin, (req, res) => {
  const s = db.prepare('SELECT * FROM ai_settings WHERE id = 1').get();
  res.json({ ...s, openai_api_key: s.openai_api_key ? '••••••••' + s.openai_api_key.slice(-4) : null });
});

app.put('/api/settings/ai', auth.requireAdmin, (req, res) => {
  const s = db.prepare('SELECT * FROM ai_settings WHERE id = 1').get();
  const { openai_api_key, company_context, transcribe_model, analysis_model, rub_per_usd } = req.body || {};
  db.prepare(`UPDATE ai_settings SET openai_api_key=?, company_context=?, transcribe_model=?, analysis_model=?, rub_per_usd=? WHERE id=1`)
    .run(
      openai_api_key && !openai_api_key.startsWith('••••') ? openai_api_key : s.openai_api_key,
      company_context ?? s.company_context, transcribe_model || s.transcribe_model,
      analysis_model || s.analysis_model, rub_per_usd || s.rub_per_usd
    );
  res.json({ ok: true });
});

app.get('/api/settings/ai/usage', auth.requireAdmin, (req, res) => {
  const today = db.prepare(`SELECT COALESCE(SUM(cost_usd),0) AS usd FROM ai_usage WHERE date(created_at) = date('now')`).get();
  const total = db.prepare(`SELECT COALESCE(SUM(cost_usd),0) AS usd FROM ai_usage`).get();
  const rate = db.prepare('SELECT rub_per_usd FROM ai_settings WHERE id=1').get().rub_per_usd;
  res.json({ today_usd: today.usd, today_rub: today.usd * rate, total_usd: total.usd, total_rub: total.usd * rate });
});

// ================= НАСТРОЙКИ ТЕЛЕФОНИИ =================
app.get('/api/settings/telephony', auth.requireAdmin, (req, res) => {
  const s = db.prepare('SELECT * FROM telephony_settings WHERE id = 1').get();
  res.json({ ...s, uis_api_key: s.uis_api_key ? '••••••••' + s.uis_api_key.slice(-4) : null });
});

app.put('/api/settings/telephony', auth.requireAdmin, (req, res) => {
  const s = db.prepare('SELECT * FROM telephony_settings WHERE id = 1').get();
  const { uis_login, uis_api_key, poll_interval_sec, callback_window_min, uis_timezone_offset_hours, enabled } = req.body || {};
  db.prepare(`UPDATE telephony_settings SET uis_login=?, uis_api_key=?, poll_interval_sec=?, callback_window_min=?, uis_timezone_offset_hours=?, enabled=? WHERE id=1`)
    .run(
      uis_login ?? s.uis_login,
      uis_api_key && !uis_api_key.startsWith('••••') ? uis_api_key : s.uis_api_key,
      poll_interval_sec || s.poll_interval_sec,
      callback_window_min || s.callback_window_min,
      uis_timezone_offset_hours === undefined ? s.uis_timezone_offset_hours : uis_timezone_offset_hours,
      enabled === undefined ? s.enabled : (enabled ? 1 : 0)
    );
  res.json({ ok: true });
});

// ручная дозагрузка звонков за произвольный период (например, если обычный опрос
// не работал какое-то время и часть звонков не попала в скользящее окно)
app.post('/api/settings/telephony/backfill', auth.requireAdmin, (req, res) => {
  const { date_from, date_till } = req.body || {};
  if (!date_from || !date_till) return res.status(400).json({ error: 'Укажите date_from и date_till' });
  require('./telephony').backfill(date_from, date_till)
    .then(result => res.json(result))
    .catch(err => res.status(500).json({ error: err.message }));
});

// ================= КЛИК-ЗВОНОК (отложено, но код доступен) =================
app.get('/api/settings/call-out', auth.requireAdmin, (req, res) => {
  res.json(db.prepare('SELECT * FROM call_out_settings WHERE id = 1').get());
});

app.put('/api/settings/call-out', auth.requireAdmin, (req, res) => {
  const s = db.prepare('SELECT * FROM call_out_settings WHERE id = 1').get();
  const { outbound_virtual_number, enabled } = req.body || {};
  db.prepare('UPDATE call_out_settings SET outbound_virtual_number=?, enabled=? WHERE id=1')
    .run(outbound_virtual_number ?? s.outbound_virtual_number, enabled === undefined ? s.enabled : (enabled ? 1 : 0));
  res.json({ ok: true });
});

app.post('/api/call-out/start', (req, res) => {
  const { salon_id, target_phone } = req.body || {};
  if (!salon_id || !target_phone) return res.status(400).json({ error: 'salon_id и target_phone обязательны' });
  if (!canAccessSalon(req.user, salon_id)) return res.status(403).json({ error: 'Нет доступа к объекту' });
  const { startClickToCall } = require('./call-out');
  startClickToCall({ userId: req.user.id, salonId: salon_id, targetPhone: target_phone })
    .then(result => res.json(result))
    .catch(err => res.status(500).json({ error: err.message }));
});

// ================= ОТЧЁТЫ =================
const reports = require('./reports');
app.get('/api/reports/admin/:id', auth.requireAdmin, (req, res) => {
  reports.renderAdminReport(Number(req.params.id), req.query.period || 'week')
    .then(html => res.send(html)).catch(err => res.status(500).send('Ошибка отчёта: ' + err.message));
});
app.get('/api/reports/salon/:id', (req, res) => {
  const salonId = Number(req.params.id);
  if (!canAccessSalon(req.user, salonId)) return res.status(403).json({ error: 'Нет доступа к объекту' });
  reports.renderSalonReport(salonId, req.query.period || 'week')
    .then(html => res.send(html)).catch(err => res.status(500).send('Ошибка отчёта: ' + err.message));
});
app.get('/api/reports/network', auth.requireAdmin, (req, res) => {
  reports.renderNetworkReport(req.query.period || 'week')
    .then(html => res.send(html)).catch(err => res.status(500).send('Ошибка отчёта: ' + err.message));
});
app.get('/api/reports/clients', auth.requireAdmin, (req, res) => {
  reports.renderClientsReport(req.query.period || 'week')
    .then(html => res.send(html)).catch(err => res.status(500).send('Ошибка отчёта: ' + err.message));
});

// ================= ЭКСПОРТ В EXCEL =================
app.get('/api/export/calls.xlsx', auth.requireAdmin, (req, res) => {
  const rows = db.prepare(`
    SELECT c.started_at AS "Дата", s.name AS "Объект", c.direction AS "Направление",
      c.caller_phone AS "Телефон", cl.name AS "Клиент", a.name AS "Администратор",
      c.duration_sec AS "Длительность,с", c.status AS "Статус", c.outcome AS "Исход",
      c.checklist_score AS "Чек-лист (баллы)", c.checklist_total AS "Чек-лист (всего)",
      c.callback_status AS "Перезвон"
    FROM calls c JOIN salons s ON s.id = c.salon_id
    LEFT JOIN admins a ON a.id = c.matched_admin_id
    LEFT JOIN clients cl ON cl.id = c.client_id
    ORDER BY c.started_at DESC
  `).all();
  sendXlsx(res, rows, 'Звонки', 'calls.xlsx');
});

app.get('/api/export/clients.xlsx', auth.requireAdmin, (req, res) => {
  const rows = db.prepare(`
    SELECT cl.phone AS "Телефон", cl.name AS "Имя",
      (SELECT COUNT(*) FROM bookings b WHERE b.client_id = cl.id) AS "Записей",
      (SELECT COUNT(*) FROM visits v WHERE v.client_id = cl.id AND v.arrived = 1) AS "Визитов",
      (SELECT MAX(started_at) FROM calls c WHERE c.client_id = cl.id) AS "Последний звонок"
    FROM clients cl ORDER BY cl.updated_at DESC
  `).all();
  sendXlsx(res, rows, 'Клиенты', 'clients.xlsx');
});

function sendXlsx(res, rows, sheetName, filename) {
  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.json_to_sheet(rows);
  XLSX.utils.book_append_sheet(wb, ws, sheetName);
  const buf = XLSX.write(wb, { type: 'buffer', bookType: 'xlsx' });
  res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
  res.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
  res.send(buf);
}

app.listen(PORT, () => {
  console.log(`[server] CRM сети массажных салонов запущена на порту ${PORT}`);
  require('./telephony').startPolling();
});
