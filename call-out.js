// Клик-звонок через UIS Call API (start.simple_call) — аналог call-out.js из
// исходного проекта. Сотрудник жмёт кнопку в карточке звонка/салона → UIS сначала
// звонит сотруднику на его номер в приложении UIS, затем набирает клиента и соединяет.

const fetch = require('node-fetch');
const db = require('./db');

const CALL_API_URL = 'https://callapi.uiscom.ru/v4.0/';

async function startClickToCall({ userId, salonId, targetPhone }) {
  const settings = db.prepare('SELECT * FROM call_out_settings WHERE id = 1').get();
  const telephony = db.prepare('SELECT uis_api_key FROM telephony_settings WHERE id = 1').get();

  if (!settings.enabled) throw new Error('Клик-звонок отключён в настройках');
  if (!telephony.uis_api_key) throw new Error('Не задан ключ UIS API');

  const user = db.prepare('SELECT * FROM users WHERE id = ?').get(userId);
  if (!user || !user.phone) throw new Error('У сотрудника не указан номер телефона в приложении UIS');

  const salon = db.prepare('SELECT * FROM salons WHERE id = ?').get(salonId);
  if (!salon) throw new Error('Салон не найден');

  const body = {
    jsonrpc: '2.0',
    id: Date.now(),
    method: 'start.simple_call',
    params: {
      access_token: telephony.uis_api_key,
      employee_phone: user.phone,
      client_phone: targetPhone,
      virtual_phone_number: settings.outbound_virtual_number || salon.uis_line_id || salon.phone
    }
  };

  const resp = await fetch(CALL_API_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const json = await resp.json();
  if (json.error) throw new Error(`UIS Call API error: ${json.error.message || JSON.stringify(json.error)}`);

  return { ok: true, uis_result: json.result };
}

module.exports = { startClickToCall };
