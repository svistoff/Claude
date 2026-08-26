const jwt = require('jsonwebtoken');
const bcrypt = require('bcryptjs');
const db = require('./db');

const JWT_SECRET = process.env.JWT_SECRET || 'change-me-in-production-env-var-JWT_SECRET';
const COOKIE_NAME = 'crm_token';

function signToken(user) {
  return jwt.sign({ id: user.id, username: user.username, role: user.role }, JWT_SECRET, { expiresIn: '30d' });
}

function login(req, res) {
  const { username, password } = req.body || {};
  if (!username || !password) return res.status(400).json({ error: 'Укажите логин и пароль' });

  const user = db.prepare('SELECT * FROM users WHERE username = ? AND active = 1').get(username);
  if (!user || !bcrypt.compareSync(password, user.password_hash)) {
    return res.status(401).json({ error: 'Неверный логин или пароль' });
  }

  const token = signToken(user);
  res.cookie(COOKIE_NAME, token, {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    maxAge: 30 * 24 * 60 * 60 * 1000
  });
  res.json({ id: user.id, username: user.username, full_name: user.full_name, role: user.role });
}

function logout(req, res) {
  res.clearCookie(COOKIE_NAME);
  res.json({ ok: true });
}

function requireAuth(req, res, next) {
  const token = req.cookies && req.cookies[COOKIE_NAME];
  if (!token) return res.status(401).json({ error: 'Не авторизован' });
  try {
    const payload = jwt.verify(token, JWT_SECRET);
    const user = db.prepare('SELECT id, username, full_name, role, active FROM users WHERE id = ?').get(payload.id);
    if (!user || !user.active) return res.status(401).json({ error: 'Не авторизован' });
    req.user = user;
    next();
  } catch (e) {
    return res.status(401).json({ error: 'Сессия истекла' });
  }
}

function requireAdmin(req, res, next) {
  if (!req.user || req.user.role !== 'admin') {
    return res.status(403).json({ error: 'Требуются права администратора' });
  }
  next();
}

module.exports = { login, logout, requireAuth, requireAdmin, COOKIE_NAME };
