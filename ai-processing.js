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

// node-fetch сам по себе никогда не отваливается по тайм-ауту — если сеть
// "подвисла" (соединение установлено, но ответ не приходит — ровно то, что
// уже один раз ловили с UIS из-за DPI-блокировки), запрос висит бесконечно.
// Для массового пересчёта звонков (scripts/reanalyze-calls.js) это фатально:
// одно зависшее соединение блокирует всю последовательную очередь навсегда.
// Поэтому у каждого внешнего запроса — явный тайм-аут через AbortController.
async function fetchWithTimeout(url, opts, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...opts, signal: controller.signal });
  } catch (err) {
    if (err.name === 'AbortError') throw new Error(`Таймаут запроса (${timeoutMs / 1000}с): ${url}`);
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

function getAiSettings() {
  return db.prepare('SELECT * FROM ai_settings WHERE id = 1').get();
}

function logUsage(callId, kind, costUsd) {
  db.prepare('INSERT INTO ai_usage (call_id, kind, cost_usd) VALUES (?, ?, ?)').run(callId, kind, costUsd);
}

async function downloadRecording(url) {
  const resp = await fetchWithTimeout(url, {}, 60_000);
  if (!resp.ok) throw new Error(`Не удалось скачать запись звонка (HTTP ${resp.status})`);
  return Buffer.from(await resp.arrayBuffer());
}

async function transcribeAudio(buffer, model, apiKey, durationSec) {
  const form = new FormData();
  form.append('file', buffer, { filename: 'call.mp3', contentType: 'audio/mpeg' });
  form.append('model', model);
  form.append('language', 'ru');

  const resp = await fetchWithTimeout(`${OPENAI_BASE}/audio/transcriptions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, ...form.getHeaders() },
    body: form
  }, 90_000);
  const json = await resp.json();
  if (!resp.ok) throw new Error(`OpenAI transcribe error: ${json.error?.message || resp.status}`);

  const costUsd = (durationSec / 60) * 0.003; // ~$0.003/мин
  return { text: json.text || '', costUsd };
}

function buildAnalysisPrompt({ companyContext, transcript, salon, admins, checklist, direction, callbackStatus }) {
  const adminsList = admins.length
    ? admins.map(a => `- "${a.name}" (id=${a.id}, статус: ${a.status === 'confirmed' ? 'подтверждён' : 'не подтверждён'})`).join('\n')
    : '(справочник администраторов пока пуст)';

  const checklistList = checklist.map((item, i) => {
    const flags = [`вес=${item.weight}`];
    if (item.critical) flags.push('КРИТИЧНЫЙ');
    const hint = item.not_applicable_hint ? ` | когда НЕ применим: ${item.not_applicable_hint}` : '';
    return `${i + 1}. [id=${item.id}] ${item.text} (${flags.join(', ')})${hint}`;
  }).join('\n');
  const objectKind = salon.type === 'sauna' ? 'сауна' : 'салон массажа';
  const callContext = direction === 'out'
    ? `Это ИСХОДЯЩИЙ звонок — вероятно, перезвон администратора клиенту после пропущенного звонка${callbackStatus ? ` (перезвонили ${callbackStatus === 'on_time' ? 'вовремя' : 'позже обычного окна'})` : ''}. Разбери его по тому же чек-листу, как обычный разговор.`
    : 'Это входящий звонок клиента.';

  const system = `Ты — AI-аудитор качества телефонных звонков администраторов сети массажных салонов и сауны.
Контекст компании: ${companyContext || 'Сеть массажных салонов и сауна, администраторы принимают звонки и записывают клиентов.'}
Этот объект: ${objectKind} «${salon.name}». ${callContext}

ГЛАВНЫЙ ПРИНЦИП: ты НЕ проверяешь, произнёс ли администратор все пункты стандартного
скрипта. Сначала определи контекст — зачем клиент позвонил, что он уже знает, насколько
он готов к записи/визиту, какой результат достигнут — и только потом оценивай, какие
пункты чек-листа вообще были нужны В ЭТОМ конкретном разговоре. Нельзя штрафовать за
пункт, выполнение которого не требовалось (например, гостю, который уже всё знает и
просто уточняет цену перед тем как приехать, не нужна полная презентация салона).
Оценивай смысл сказанного, а не дословное совпадение со скриптом — если то же самое
сказано другими словами, пункт считается выполненным. Отказ клиента или любой другой
результат сам по себе не является ошибкой администратора, если тот действовал верно.

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
   Справочник администраторов (общий по всей сети — один и тот же человек может
   отвечать в разных объектах сети):
${adminsList}

2. Определить контекст звонка:
   - primary_scenario — свободная короткая фраза по-русски, что это был за звонок
     (например: "повторный клиент, уточнение цены", "новый клиент, запись", "жалоба").
   - client_type — "NEW" (новый клиент), "RETURNING" (уже был/звонил раньше),
     "UNKNOWN" (невозможно определить по разговору).
   - client_intent — насколько клиент готов к действию: "INFORMATION" (просто узнаёт),
     "CONSIDERING" ("я подумаю"), "READY_TO_BOOK" (просит записать), "READY_TO_VISIT"
     (уже решил приехать/записался в разговоре), "COMPLAINT" (жалоба), "OTHER".

3. Проверить пункты чек-листа — но СНАЧАЛА для каждого пункта реши, был ли он вообще
   применим (applicable) в данной ситуации, с учётом подсказки "когда НЕ применим",
   если она указана у пункта, и общего смысла разговора. Если пункт не нужен был в
   этой ситуации — applicable=false, status="NA" (это НЕ штраф, НЕ ошибка). Если пункт
   применим, определи status:
   - "PASS" — чётко выполнен (по смыслу, не обязательно теми же словами);
   - "PARTIAL" — затронут частично/вскользь;
   - "FAIL" — применим, но не выполнен;
   - "UNCERTAIN" — невозможно достоверно определить по расшифровке (плохое качество
     записи, обрыв и т.п.) — это НЕ штраф, не выдумывай результат, если не уверен(а).
   К каждому пункту — короткая цитата-подтверждение (evidence) и краткое объяснение
   (reason), плюс confidence от 0 до 1 (насколько ты уверен(а) в этом статусе).
   Чек-лист этого объекта (вес и критичность — для справки, расчёт баллов делает CRM):
${checklistList}

4. Отдельно выявить КРИТИЧЕСКИЕ ОШИБКИ (critical_errors) — это не то же самое, что
   невыполненный пункт чек-листа. Критическая ошибка — существенный и однозначный
   промах: неверная цена/условия/время, игнорирование прямого вопроса клиента,
   грубость, вводящая в заблуждение информация, ошибка при оформлении записи. НЕ
   считай критической ошибкой просто отсутствие необязательного пункта скрипта.
   Для каждой — type (одно из: WRONG_PRICE, WRONG_CONDITIONS, WRONG_TIME,
   WRONG_AVAILABILITY, DIRECT_QUESTION_IGNORED, RUDE_BEHAVIOR, MISLEADING_INFORMATION,
   BOOKING_ERROR, OTHER_CRITICAL), description, evidence (цитата), confidence (0-1).

5. Сделать разбор звонка: резюме, что было сделано хорошо (strengths), что плохо
   (weaknesses), конкретные рекомендации по улучшению (recommendations) — это
   предложения "как можно было сделать ещё лучше", а не перечень ошибок (ошибки уже
   в critical_errors); если гость и так получил всё нужное — не придумывай рекомендации
   искусственно, короткое "—" вполне нормальный ответ.

6. Советы по удержанию (retention_advice) — отдельно: что администратор могла(-л)
   сделать, чтобы клиент не "слился" (предложить другое время, обозначить выгоду,
   взять контакт для напоминания и т.п.). Если клиент и так записался — короткое "—".

7. Определить исход (outcome): "booking" (запись подтверждена), "interest" (интерес,
   но без записи), "callback" (просили перезвонить/клиент подумает), "refusal" (отказ),
   "spam" (нецелевой/рекламный/ошибочный звонок — не в счёт статистики).

8. Если в разговоре прозвучало имя клиента — верни его в client_name (иначе null).

9. Если запись подтверждена (пункт "booking") — заполни объект booking: confirmed=true,
   when_text — как это прозвучало ("завтра в 15:00"), when_iso — попытка перевести в
   ISO 8601 (используй сегодняшнюю дату как точку отсчёта, если это возможно понять из
   контекста; если не уверен — null, but when_text заполни всегда).

Ответь СТРОГО в формате JSON без markdown, по схеме:
{
  "detected_admin_name": string | null,
  "matched_admin_name": string | null,
  "is_new_admin": boolean,
  "primary_scenario": string,
  "client_type": "NEW"|"RETURNING"|"UNKNOWN",
  "client_intent": "INFORMATION"|"CONSIDERING"|"READY_TO_BOOK"|"READY_TO_VISIT"|"COMPLAINT"|"OTHER",
  "checklist": [ { "item_id": number, "applicable": boolean, "status": "PASS"|"FAIL"|"PARTIAL"|"NA"|"UNCERTAIN", "evidence": string, "reason": string, "confidence": number } ],
  "critical_errors": [ { "type": string, "description": string, "evidence": string, "confidence": number } ],
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

// temperature намеренно не передаётся: некоторые модели (в т.ч. используемая
// в проекте) поддерживают только значение по умолчанию и отклоняют запрос
// с любым другим числом.
async function analyzeTranscript(args) {
  const { system, user } = buildAnalysisPrompt(args);
  const resp = await fetchWithTimeout(`${OPENAI_BASE}/chat/completions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${args.apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: args.model,
      messages: [{ role: 'system', content: system }, { role: 'user', content: user }],
      response_format: { type: 'json_object' }
    })
  }, 120_000);
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

const VALID_STATUSES = ['PASS', 'FAIL', 'PARTIAL', 'NA', 'UNCERTAIN'];

// Пункт, который ИИ не нужно штрафовать, если он не применим в данной
// ситуации (NA) или его состояние нельзя достоверно определить (UNCERTAIN) —
// см. тех. задание "контекстная оценка качества", разделы 11-14.
function mergeChecklist(templateItems, aiResults) {
  const byId = new Map((aiResults || []).map(r => [Number(r.item_id), r]));
  return templateItems.map(item => {
    const r = byId.get(item.id);
    const status = r && VALID_STATUSES.includes(r.status) ? r.status : 'UNCERTAIN';
    const coefficient = item.partial_coefficient ?? 0.5;
    const earned = status === 'PASS' ? item.weight : status === 'PARTIAL' ? item.weight * coefficient : 0;
    return {
      item_id: item.id, text: item.text, weight: item.weight, critical: !!item.critical,
      applicable: status !== 'NA', status, earned,
      evidence: r ? (r.evidence || '') : '', reason: r ? (r.reason || '') : '',
      confidence: r && typeof r.confidence === 'number' ? r.confidence : null
    };
  });
}

// quality_score = earned_points / maximum_applicable_points — NA и UNCERTAIN
// исключаются из знаменателя (не являются ни штрафом, ни выполнением).
function scoreChecklist(mergedChecklist) {
  let earned = 0, maxApplicable = 0;
  for (const item of mergedChecklist) {
    if (item.status === 'NA' || item.status === 'UNCERTAIN') continue;
    earned += item.earned;
    maxApplicable += item.weight;
  }
  return { earned, maxApplicable };
}

function resolveAdmin(admins, parsed) {
  if (parsed.matched_admin_name) {
    const found = admins.find(a => a.name.toLowerCase() === String(parsed.matched_admin_name).toLowerCase());
    if (found) return found.id;
  }
  if (parsed.is_new_admin && parsed.detected_admin_name) {
    const info = db.prepare(`INSERT INTO admins (name, status) VALUES (?, 'unconfirmed')`)
      .run(parsed.detected_admin_name.trim());
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

// reuseTranscript=true пропускает скачивание записи и повторную транскрибацию,
// если расшифровка уже сохранена с прошлого раза — используется массовым
// пересчётом старых звонков по новой логике оценки (см. scripts/reanalyze-calls.js):
// не тратит деньги и время на то, что уже есть, и работает даже если запись
// в UIS к этому моменту уже истекла/удалена.
async function processCall(callId, { reuseTranscript = false } = {}) {
  const call = db.prepare('SELECT * FROM calls WHERE id = ?').get(callId);
  if (!call) return;

  const salon = db.prepare('SELECT * FROM salons WHERE id = ?').get(call.salon_id);
  const settings = getAiSettings();

  if (!settings.openai_api_key) {
    db.prepare(`UPDATE calls SET status='error', error_message='Не задан ключ OpenAI в настройках' WHERE id=?`).run(callId);
    return;
  }
  if (!(reuseTranscript && call.transcript) && !call.recording_url) {
    db.prepare(`UPDATE calls SET status='error', error_message='Нет ссылки на запись звонка' WHERE id=?`).run(callId);
    return;
  }

  db.prepare(`UPDATE calls SET status='processing' WHERE id=?`).run(callId);

  try {
    let transcript;
    if (reuseTranscript && call.transcript) {
      transcript = call.transcript;
    } else {
      const buffer = await downloadRecording(call.recording_url);
      const transcribed = await transcribeAudio(
        buffer, settings.transcribe_model, settings.openai_api_key, call.duration_sec
      );
      transcript = transcribed.text;
      logUsage(callId, 'transcribe', transcribed.costUsd);
    }

    // администраторы — общий список по всей сети: один и тот же человек может
    // в разные смены выходить в разных салонах, ИИ узнаёт по имени, не по объекту
    const admins = db.prepare('SELECT * FROM admins').all();
    const checklist = getEffectiveChecklist(salon);

    const { parsed, costUsd: analysisCost } = await analyzeTranscript({
      transcript, companyContext: settings.company_context, salon, admins, checklist,
      direction: call.direction, callbackStatus: call.callback_status,
      model: settings.analysis_model, apiKey: settings.openai_api_key
    });
    logUsage(callId, 'analysis', analysisCost);

    const matchedAdminId = resolveAdmin(admins, parsed);
    const merged = mergeChecklist(checklist, parsed.checklist);
    const { earned, maxApplicable } = scoreChecklist(merged);
    const criticalErrors = Array.isArray(parsed.critical_errors) ? parsed.critical_errors : [];

    if (call.client_id && parsed.client_name) {
      db.prepare(`UPDATE clients SET name = COALESCE(name, ?), updated_at = datetime('now') WHERE id = ?`)
        .run(parsed.client_name, call.client_id);
    }

    db.prepare(`
      UPDATE calls SET
        status = 'done', transcript = ?, detected_admin_name = ?, matched_admin_id = ?,
        checklist_results = ?, checklist_score = ?, checklist_total = ?,
        primary_scenario = ?, client_type = ?, client_intent = ?, critical_errors = ?,
        summary = ?, strengths = ?, weaknesses = ?, recommendations = ?, retention_advice = ?,
        outcome = ?, processed_at = datetime('now')
      WHERE id = ?
    `).run(
      transcript, parsed.detected_admin_name || null, matchedAdminId,
      JSON.stringify(merged), earned, maxApplicable,
      parsed.primary_scenario || null,
      ['NEW', 'RETURNING', 'UNKNOWN'].includes(parsed.client_type) ? parsed.client_type : null,
      ['INFORMATION', 'CONSIDERING', 'READY_TO_BOOK', 'READY_TO_VISIT', 'COMPLAINT', 'OTHER'].includes(parsed.client_intent) ? parsed.client_intent : null,
      criticalErrors.length ? JSON.stringify(criticalErrors) : null,
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
