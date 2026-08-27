// Транскрибация + ИИ-разбор звонка. Один ключ OpenAI на обе задачи, один запрос
// в LLM на анализ (чтобы стоимость не росла), аудио скачивается во временный
// буфер и не сохраняется — в базе только текст и выводы ИИ.
//
// За один проход ИИ определяет: кто из администраторов объекта ответил (с учётом
// падежей/уменьшительных имён, сопоставляя со справочником объекта; новое имя —
// автосоздание неподтверждённого администратора), выполнение пунктов чек-листа
// объекта (✅/⚠️/❌ с цитатой), резюме и разбор звонка, советы по удержанию,
// исход разговора и — если запись подтверждена — данные для авто-создания брони.

const fetch = require('node-fetch');
const FormData = require('form-data');
const db = require('./db');
const { getEffectiveChecklist } = require('./lib');

const OPENAI_BASE = 'https://api.openai.com/v1';

function getAiSettings() {
  return db.prepare('SELECT * FROM ai_settings WHERE id = 1').get();
}

function logUsage(callId, kind, costUsd) {
  db.prepare('INSERT INTO ai_usage (call_id, kind, cost_usd) VALUES (?, ?, ?)').run(callId, kind, costUsd);
}

async function downloadRecording(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Не удалось скачать запись звонка (HTTP ${resp.status})`);
  return Buffer.from(await resp.arrayBuffer());
}

async function transcribeAudio(buffer, model, apiKey, durationSec) {
  const form = new FormData();
  form.append('file', buffer, { filename: 'call.mp3', contentType: 'audio/mpeg' });
  form.append('model', model);
  form.append('language', 'ru');

  const resp = await fetch(`${OPENAI_BASE}/audio/transcriptions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, ...form.getHeaders() },
    body: form
  });
  const json = await resp.json();
  if (!resp.ok) throw new Error(`OpenAI transcribe error: ${json.error?.message || resp.status}`);

  const costUsd = (durationSec / 60) * 0.003; // ~$0.003/мин
  return { text: json.text || '', costUsd };
}

function buildAnalysisPrompt({ companyContext, transcript, salon, admins, checklist, direction, callbackStatus }) {
  const adminsList = admins.length
    ? admins.map(a => `- "${a.name}" (id=${a.id}, статус: ${a.status === 'confirmed' ? 'подтверждён' : 'не подтверждён'})`).join('\n')
    : '(справочник администраторов этого объекта пока пуст)';

  const checklistList = checklist.map((item, i) => `${i + 1}. [id=${item.id}] ${item.text}`).join('\n');
  const objectKind = salon.type === 'sauna' ? 'сауна' : 'салон массажа';
  const callContext = direction === 'out'
    ? `Это ИСХОДЯЩИЙ звонок — вероятно, перезвон администратора клиенту после пропущенного звонка${callbackStatus ? ` (перезвонили ${callbackStatus === 'on_time' ? 'вовремя' : 'позже обычного окна'})` : ''}. Разбери его по тому же чек-листу, как обычный разговор.`
    : 'Это входящий звонок клиента.';

  const system = `Ты — ассистент отдела контроля качества сети массажных салонов и сауны.
Контекст компании: ${companyContext || 'Сеть массажных салонов и сауна, администраторы принимают звонки и записывают клиентов.'}
Этот объект: ${objectKind} «${salon.name}». ${callContext}

Задачи по расшифровке звонка:

1. Определить, кто из администраторов ответил. Администратор обычно представляется
   в начале разговора ("Здравствуйте, это Ольга" / "вас слушает Оля" и т.п.).
   Сопоставь услышанное имя со справочником администраторов ниже, ОБЯЗАТЕЛЬНО учитывая
   падежи и уменьшительные формы (пример: "Ольгой", "Олей", "Оля" — это одно и то же
   имя "Ольга"; "Дианой" = "Диана"). Если имя явно совпадает с одним из справочника —
   верни его каноническое написание из справочника в matched_admin_name. Если имя
   прозвучало, но ни на кого из справочника не похоже — это может быть новый
   администратор: верни is_new_admin=true и восстанови имя в именительном падеже в
   detected_admin_name. Если имя не прозвучало вообще — оставь оба поля null.
   Справочник администраторов этого объекта:
${adminsList}

2. Проверить чек-лист конкретных пунктов — по каждому определить состояние:
   "yes" (чётко проговорено/сделано), "partial" (затронуто вскользь/не полностью),
   "no" (не было). К каждому пункту — короткая цитата-подтверждение (evidence).
   Чек-лист этого объекта:
${checklistList}

3. Сделать разбор звонка: резюме, что было сделано хорошо (strengths), что плохо
   (weaknesses), конкретные рекомендации (recommendations).

4. Советы по удержанию (retention_advice) — отдельно: что администратор могла(-л)
   сделать, чтобы клиент не "слился" (предложить другое время, обозначить выгоду,
   взять контакт для напоминания и т.п.). Если клиент и так записался — короткое "—".

5. Определить исход (outcome): "booking" (запись подтверждена), "interest" (интерес,
   но без записи), "callback" (просили перезвонить/клиент подумает), "refusal" (отказ),
   "spam" (нецелевой/рекламный/ошибочный звонок — не в счёт статистики).

6. Если в разговоре прозвучало имя клиента — верни его в client_name (иначе null).

7. Если запись подтверждена (пункт "booking") — заполни объект booking: confirmed=true,
   when_text — как это прозвучало ("завтра в 15:00"), when_iso — попытка перевести в
   ISO 8601 (используй сегодняшнюю дату как точку отсчёта, если это возможно понять из
   контекста; если не уверен — null, but when_text заполни всегда).

Ответь СТРОГО в формате JSON без markdown, по схеме:
{
  "detected_admin_name": string | null,
  "matched_admin_name": string | null,
  "is_new_admin": boolean,
  "checklist": [ { "item_id": number, "state": "yes"|"partial"|"no", "evidence": string } ],
  "summary": string,
  "strengths": string,
  "weaknesses": string,
  "recommendations": string,
  "retention_advice": string,
  "outcome": "booking"|"interest"|"callback"|"refusal"|"spam",
  "client_name": string | null,
  "booking": { "confirmed": boolean, "when_text": string | null, "when_iso": string | null }
}`;

  return { system, user: `Расшифровка звонка:\n\n${transcript}` };
}

async function analyzeTranscript(args) {
  const { system, user } = buildAnalysisPrompt(args);
  const resp = await fetch(`${OPENAI_BASE}/chat/completions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${args.apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: args.model,
      messages: [{ role: 'system', content: system }, { role: 'user', content: user }],
      response_format: { type: 'json_object' },
      temperature: 0.2
    })
  });
  const json = await resp.json();
  if (!resp.ok) throw new Error(`OpenAI analysis error: ${json.error?.message || resp.status}`);

  const content = json.choices?.[0]?.message?.content || '{}';
  let parsed;
  try { parsed = JSON.parse(content); }
  catch (e) { throw new Error('ИИ вернул невалидный JSON: ' + content.slice(0, 200)); }

  const usage = json.usage || {};
  const costUsd = ((usage.prompt_tokens || 0) * 0.15 + (usage.completion_tokens || 0) * 0.6) / 1_000_000;
  return { parsed, costUsd };
}

function mergeChecklist(templateItems, aiResults) {
  const byId = new Map((aiResults || []).map(r => [Number(r.item_id), r]));
  return templateItems.map(item => {
    const r = byId.get(item.id);
    const state = r && ['yes', 'partial', 'no'].includes(r.state) ? r.state : 'no';
    return { item_id: item.id, text: item.text, state, evidence: r ? (r.evidence || '') : '' };
  });
}

function checklistScore(mergedChecklist) {
  const weight = { yes: 1, partial: 0.5, no: 0 };
  return mergedChecklist.reduce((sum, i) => sum + weight[i.state], 0);
}

function resolveAdmin(salon, admins, parsed) {
  if (parsed.matched_admin_name) {
    const found = admins.find(a => a.name.toLowerCase() === String(parsed.matched_admin_name).toLowerCase());
    if (found) return found.id;
  }
  if (parsed.is_new_admin && parsed.detected_admin_name) {
    const info = db.prepare(`INSERT INTO admins (salon_id, name, status) VALUES (?, ?, 'unconfirmed')`)
      .run(salon.id, parsed.detected_admin_name.trim());
    return info.lastInsertRowid;
  }
  return null;
}

function tryCreateBooking(call, salon, parsed) {
  if (!parsed.booking?.confirmed || !call.client_id) return;
  let scheduledDate = null;
  if (parsed.booking.when_iso) {
    const d = new Date(parsed.booking.when_iso);
    if (!isNaN(d.getTime())) scheduledDate = d.toISOString().slice(0, 10);
  }
  db.prepare(`
    INSERT INTO bookings (client_id, salon_id, call_id, scheduled_at, scheduled_date, status)
    VALUES (?, ?, ?, ?, ?, 'upcoming')
  `).run(call.client_id, salon.id, call.id, parsed.booking.when_text || parsed.booking.when_iso || 'без уточнённого времени', scheduledDate);
}

async function processCall(callId) {
  const call = db.prepare('SELECT * FROM calls WHERE id = ?').get(callId);
  if (!call) return;

  const salon = db.prepare('SELECT * FROM salons WHERE id = ?').get(call.salon_id);
  const settings = getAiSettings();

  if (!settings.openai_api_key) {
    db.prepare(`UPDATE calls SET status='error', error_message='Не задан ключ OpenAI в настройках' WHERE id=?`).run(callId);
    return;
  }
  if (!call.recording_url) {
    db.prepare(`UPDATE calls SET status='error', error_message='Нет ссылки на запись звонка' WHERE id=?`).run(callId);
    return;
  }

  db.prepare(`UPDATE calls SET status='processing' WHERE id=?`).run(callId);

  try {
    const buffer = await downloadRecording(call.recording_url);
    const { text: transcript, costUsd: transcribeCost } = await transcribeAudio(
      buffer, settings.transcribe_model, settings.openai_api_key, call.duration_sec
    );
    logUsage(callId, 'transcribe', transcribeCost);

    const admins = db.prepare('SELECT * FROM admins WHERE salon_id = ?').all(salon.id);
    const checklist = getEffectiveChecklist(salon);

    const { parsed, costUsd: analysisCost } = await analyzeTranscript({
      transcript, companyContext: settings.company_context, salon, admins, checklist,
      direction: call.direction, callbackStatus: call.callback_status,
      model: settings.analysis_model, apiKey: settings.openai_api_key
    });
    logUsage(callId, 'analysis', analysisCost);

    const matchedAdminId = resolveAdmin(salon, admins, parsed);
    const merged = mergeChecklist(checklist, parsed.checklist);
    const score = checklistScore(merged);

    if (call.client_id && parsed.client_name) {
      db.prepare(`UPDATE clients SET name = COALESCE(name, ?), updated_at = datetime('now') WHERE id = ?`)
        .run(parsed.client_name, call.client_id);
    }

    db.prepare(`
      UPDATE calls SET
        status = 'done', transcript = ?, detected_admin_name = ?, matched_admin_id = ?,
        checklist_results = ?, checklist_score = ?, checklist_total = ?,
        summary = ?, strengths = ?, weaknesses = ?, recommendations = ?, retention_advice = ?,
        outcome = ?, processed_at = datetime('now')
      WHERE id = ?
    `).run(
      transcript, parsed.detected_admin_name || null, matchedAdminId,
      JSON.stringify(merged), score, merged.length,
      parsed.summary || null, parsed.strengths || null, parsed.weaknesses || null,
      parsed.recommendations || null, parsed.retention_advice || null,
      ['booking', 'interest', 'callback', 'refusal', 'spam'].includes(parsed.outcome) ? parsed.outcome : null,
      callId
    );

    tryCreateBooking({ ...call, id: callId }, salon, parsed);
  } catch (err) {
    db.prepare(`UPDATE calls SET status='error', error_message=? WHERE id=?`).run(err.message, callId);
    throw err;
  }
}

module.exports = { processCall };
