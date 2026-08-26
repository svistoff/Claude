const express = require('express');
const cookieParser = require('cookie-parser');
const bcrypt = require('bcryptjs');
const path = require('path');
const db = require('./db');
const auth = require('./auth');
const { getEffectiveChecklist, userSalonIds, canAccessSalon } = require('./lib');

const app = express();
const PORT = process.env.PORT || 3001;

app.use(express.json());
app.use(cookieParser());
app.use(express.static(path.join(__dirname, 'public')));

// ---------- auth ----------
app.post('/api/login', auth.login);
app.post('/api/logout', auth.logout);
app.get('/api/me', auth.requireAuth, (req, res) => {
  res.json({ ...req.user, salon_ids: req.user.role === 'admin' ? null : userSalonIds(req.user.id) });
});

app.use('/api', auth.requireAuth);

// ---------- salons ----------
app.get('/api/salons', (req, res) => {
  let rows;
  if (req.user.role === 'admin') {
    rows = db.prepare('SELECT * FROM salons ORDER BY name').all();
  } else {
    rows = db.prepare(`
      SELECT s.* FROM salons s
      JOIN user_salons us ON us.salon_id = s.id
      WHERE us.user_id = ?
      ORDER BY s.name
    `).all(req.user.id);
  }
  res.json(rows);
});

app.post('/api/salons', auth.requireAdmin, (req, res) => {
  const { name, address, phone, uis_line_id } = req.body || {};
  if (!name || !phone) return res.status(400).json({ error: 'Название и телефон обязательны' });
  const info = db.prepare('INSERT INTO salons (name, address, phone, uis_line_id) VALUES (?, ?, ?, ?)')
    .run(name.trim(), address || null, phone.trim(), uis_line_id || null);
  res.json(db.prepare('SELECT * FROM salons WHERE id = ?').get(info.lastInsertRowid));
});

app.put('/api/salons/:id', auth.requireAdmin, (req, res) => {
  const salon = db.prepare('SELECT * FROM salons WHERE id = ?').get(req.params.id);
  if (!salon) return res.status(404).json({ error: 'Салон не найден' });
  const { name, address, phone, uis_line_id, active } = req.body || {};
  db.prepare('UPDATE salons SET name=?, address=?, phone=?, uis_line_id=?, active=? WHERE id=?')
    .run(
      name ?? salon.name,
      address ?? salon.address,
      phone ?? salon.phone,
      uis_line_id ?? salon.uis_line_id,
      active === undefined ? salon.active : (active ? 1 : 0),
      salon.id
    );
  res.json(db.prepare('SELECT * FROM salons WHERE id = ?').get(salon.id));
});

app.delete('/api/salons/:id', auth.requireAdmin, (req, res) => {
  const salon = db.prepare('SELECT * FROM salons WHERE id = ?').get(req.params.id);
  if (!salon) return res.status(404).json({ error: 'Салон не найден' });
  db.prepare('DELETE FROM salons WHERE id = ?').run(salon.id); // каскад удалит звонки, привязки, чек-листы салона
  res.json({ ok: true });
});

// ---------- staff (users) ----------
app.get('/api/users', auth.requireAdmin, (req, res) => {
  const rows = db.prepare(`SELECT id, username, full_name, role, phone, active, created_at FROM users WHERE username != '__ai__' ORDER BY full_name`).all();
  const withSalons = rows.map(u => ({ ...u, salon_ids: userSalonIds(u.id) }));
  res.json(withSalons);
});

app.post('/api/users', auth.requireAdmin, (req, res) => {
  const { username, password, full_name, role, phone, salon_ids } = req.body || {};
  if (!username || !password || !full_name) return res.status(400).json({ error: 'Заполните логин, пароль и имя' });
  const exists = db.prepare('SELECT 1 FROM users WHERE username = ?').get(username);
  if (exists) return res.status(400).json({ error: 'Такой логин уже занят' });

  const hash = bcrypt.hashSync(password, 10);
  const info = db.prepare('INSERT INTO users (username, password_hash, full_name, role, phone) VALUES (?, ?, ?, ?, ?)')
    .run(username.trim(), hash, full_name.trim(), role === 'admin' ? 'admin' : 'staff', phone || null);

  const insertLink = db.prepare('INSERT OR IGNORE INTO user_salons (user_id, salon_id) VALUES (?, ?)');
  (salon_ids || []).forEach(sid => insertLink.run(info.lastInsertRowid, sid));

  res.json({ id: info.lastInsertRowid });
});

app.put('/api/users/:id', auth.requireAdmin, (req, res) => {
  const user = db.prepare('SELECT * FROM users WHERE id = ?').get(req.params.id);
  if (!user || user.username === '__ai__') return res.status(404).json({ error: 'Сотрудник не найден' });

  const { full_name, role, active, password, phone, salon_ids } = req.body || {};
  db.prepare('UPDATE users SET full_name=?, role=?, active=?, phone=? WHERE id=?')
    .run(
      full_name ?? user.full_name,
      role === 'admin' ? 'admin' : (role === 'staff' ? 'staff' : user.role),
      active === undefined ? user.active : (active ? 1 : 0),
      phone ?? user.phone,
      user.id
    );

  if (password) {
    db.prepare('UPDATE users SET password_hash=? WHERE id=?').run(bcrypt.hashSync(password, 10), user.id);
  }

  if (Array.isArray(salon_ids)) {
    db.prepare('DELETE FROM user_salons WHERE user_id=?').run(user.id);
    const insertLink = db.prepare('INSERT OR IGNORE INTO user_salons (user_id, salon_id) VALUES (?, ?)');
    salon_ids.forEach(sid => insertLink.run(user.id, sid));
  }

  res.json({ ok: true });
});

app.delete('/api/users/:id', auth.requireAdmin, (req, res) => {
  if (Number(req.params.id) === req.user.id) return res.status(400).json({ error: 'Нельзя удалить самого себя' });
  db.prepare(`DELETE FROM users WHERE id = ? AND username != '__ai__'`).run(req.params.id);
  res.json({ ok: true });
});

// ---------- checklist templates ----------
app.get('/api/checklist', (req, res) => {
  const salonId = req.query.salon_id ? Number(req.query.salon_id) : null;
  if (salonId) {
    if (!canAccessSalon(req.user, salonId)) return res.status(403).json({ error: 'Нет доступа к салону' });
    return res.json(getEffectiveChecklist(salonId));
  }
  // без salon_id — весь справочник (только админ, для управления шаблоном)
  if (req.user.role !== 'admin') return res.status(403).json({ error: 'Укажите salon_id' });
  const items = db.prepare('SELECT * FROM checklist_items ORDER BY salon_id IS NOT NULL, position, id').all();
  const overrides = db.prepare('SELECT * FROM checklist_overrides').all();
  res.json({ items, overrides });
});

app.post('/api/checklist', auth.requireAdmin, (req, res) => {
  const { text, salon_id, position } = req.body || {};
  if (!text) return res.status(400).json({ error: 'Текст пункта обязателен' });
  const info = db.prepare('INSERT INTO checklist_items (salon_id, text, position) VALUES (?, ?, ?)')
    .run(salon_id || null, text.trim(), position || 0);
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

// включить/выключить конкретный глобальный пункт для конкретного салона
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

// ---------- calls ----------
app.get('/api/calls', (req, res) => {
  const salonId = req.query.salon_id ? Number(req.query.salon_id) : null;
  const status = req.query.status || null;
  const conditions = [];
  const params = [];

  if (salonId) {
    if (!canAccessSalon(req.user, salonId)) return res.status(403).json({ error: 'Нет доступа к салону' });
    conditions.push('c.salon_id = ?');
    params.push(salonId);
  } else if (req.user.role !== 'admin') {
    const ids = userSalonIds(req.user.id);
    if (ids.length === 0) return res.json([]);
    conditions.push(`c.salon_id IN (${ids.map(() => '?').join(',')})`);
    params.push(...ids);
  }

  if (status) {
    conditions.push('c.status = ?');
    params.push(status);
  }

  const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
  const rows = db.prepare(`
    SELECT c.*, s.name AS salon_name, u.full_name AS matched_user_name
    FROM calls c
    JOIN salons s ON s.id = c.salon_id
    LEFT JOIN users u ON u.id = c.matched_user_id
    ${where}
    ORDER BY c.started_at DESC
    LIMIT 500
  `).all(...params);

  res.json(rows.map(formatCall));
});

app.get('/api/calls/:id', (req, res) => {
  const call = db.prepare(`
    SELECT c.*, s.name AS salon_name, u.full_name AS matched_user_name
    FROM calls c JOIN salons s ON s.id = c.salon_id
    LEFT JOIN users u ON u.id = c.matched_user_id
    WHERE c.id = ?
  `).get(req.params.id);
  if (!call) return res.status(404).json({ error: 'Звонок не найден' });
  if (!canAccessSalon(req.user, call.salon_id)) return res.status(403).json({ error: 'Нет доступа' });
  res.json(formatCall(call));
});

function formatCall(c) {
  return { ...c, checklist_results: c.checklist_results ? JSON.parse(c.checklist_results) : null };
}

// повторно обработать звонок (заново скачать/распознать/проанализировать)
app.post('/api/calls/:id/reprocess', (req, res) => {
  const call = db.prepare('SELECT * FROM calls WHERE id = ?').get(req.params.id);
  if (!call) return res.status(404).json({ error: 'Звонок не найден' });
  if (!canAccessSalon(req.user, call.salon_id)) return res.status(403).json({ error: 'Нет доступа' });
  db.prepare(`UPDATE calls SET status='new', error_message=NULL WHERE id=?`).run(call.id);
  const { processCall } = require('./ai-processing');
  processCall(call.id).catch(err => console.error('[reprocess]', err));
  res.json({ ok: true });
});

// ---------- ai settings ----------
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
      company_context ?? s.company_context,
      transcribe_model || s.transcribe_model,
      analysis_model || s.analysis_model,
      rub_per_usd || s.rub_per_usd
    );
  res.json({ ok: true });
});

app.get('/api/settings/ai/usage', auth.requireAdmin, (req, res) => {
  const today = db.prepare(`SELECT COALESCE(SUM(cost_usd),0) AS usd FROM ai_usage WHERE date(created_at) = date('now')`).get();
  const total = db.prepare(`SELECT COALESCE(SUM(cost_usd),0) AS usd FROM ai_usage`).get();
  const rate = db.prepare('SELECT rub_per_usd FROM ai_settings WHERE id=1').get().rub_per_usd;
  res.json({
    today_usd: today.usd, today_rub: today.usd * rate,
    total_usd: total.usd, total_rub: total.usd * rate
  });
});

// ---------- telephony settings ----------
app.get('/api/settings/telephony', auth.requireAdmin, (req, res) => {
  const s = db.prepare('SELECT * FROM telephony_settings WHERE id = 1').get();
  res.json({ ...s, uis_api_key: s.uis_api_key ? '••••••••' + s.uis_api_key.slice(-4) : null });
});

app.put('/api/settings/telephony', auth.requireAdmin, (req, res) => {
  const s = db.prepare('SELECT * FROM telephony_settings WHERE id = 1').get();
  const { uis_login, uis_api_key, poll_interval_sec, enabled } = req.body || {};
  db.prepare(`UPDATE telephony_settings SET uis_login=?, uis_api_key=?, poll_interval_sec=?, enabled=? WHERE id=1`)
    .run(
      uis_login ?? s.uis_login,
      uis_api_key && !uis_api_key.startsWith('••••') ? uis_api_key : s.uis_api_key,
      poll_interval_sec || s.poll_interval_sec,
      enabled === undefined ? s.enabled : (enabled ? 1 : 0)
    );
  res.json({ ok: true });
});

// ---------- call-out (click-to-call) settings ----------
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
  if (!canAccessSalon(req.user, salon_id)) return res.status(403).json({ error: 'Нет доступа к салону' });
  const { startClickToCall } = require('./call-out');
  startClickToCall({ userId: req.user.id, salonId: salon_id, targetPhone: target_phone })
    .then(result => res.json(result))
    .catch(err => res.status(500).json({ error: err.message }));
});

// ---------- reports ----------
const reports = require('./reports');
app.get('/api/reports/salon/:id', (req, res) => {
  const salonId = Number(req.params.id);
  if (!canAccessSalon(req.user, salonId)) return res.status(403).json({ error: 'Нет доступа к салону' });
  reports.renderSalonReport(salonId, req.query.period || 'week')
    .then(html => res.send(html))
    .catch(err => res.status(500).send('Ошибка отчёта: ' + err.message));
});

app.get('/api/reports/staff/:id', auth.requireAdmin, (req, res) => {
  reports.renderStaffReport(Number(req.params.id), req.query.period || 'week')
    .then(html => res.send(html))
    .catch(err => res.status(500).send('Ошибка отчёта: ' + err.message));
});

app.listen(PORT, () => {
  console.log(`[server] CRM массажных салонов запущена на порту ${PORT}`);
  require('./telephony').startPolling();
});
