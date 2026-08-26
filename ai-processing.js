// Транскрибация + ИИ-разбор звонка. Та же схема, что и в исходном проекте ЕКБ ГИД:
// один ключ OpenAI на обе задачи, аудио скачивается во временный буфер и никуда не
// сохраняется, в базе остаются только текст и выводы ИИ.
//
// Дополнительно к исходной версии:
//  - ИИ пытается определить по фразе представления, кто из сотрудников салона ответил
//    ("это менеджер Ольга") и сопоставляет это со справочником сотрудников салона;
//  - ИИ проверяет чек-лист конкретных пунктов, заданных админом для этого салона.

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

  // Оценка стоимости по документированному тарифу ~$0.003/мин (см. резюме проекта).
  const costUsd = (durationSec / 60) * 0.003;
  return { text: json.text || '', costUsd };
}

function buildAnalysisPrompt({ companyContext, transcript, staffNames, checklist }) {
  const staffList = staffNames.length
    ? staffNames.map(n => `- ${n}`).join('\n')
    : '(список сотрудников салона пуст)';

  const checklistList = checklist.map((item, i) => `${i + 1}. [id=${item.id}] ${item.text}`).join('\n');

  const system = `Ты — ассистент отдела контроля качества сети массажных салонов.
Контекст компании: ${companyContext || 'Сеть массажных салонов, администраторы принимают звонки на запись клиентов.'}

Твоя задача по расшифровке телефонного звонка (администратор салона отвечает клиенту):
1. Определить, кто из сотрудников ответил на звонок. В начале разговора администратор обычно
   представляется ("Здравствуйте, это салон такой-то, меня зовут Ольга"). Сопоставь услышанное
   имя со списком сотрудников салона ниже (если явного совпадения нет — верни null в matched_staff).
   Сотрудники этого салона:
${staffList}
2. Проверить чек-лист конкретных пунктов — по каждому пункту определить, было ли это
   произнесено/сделано администратором в разговоре, и привести короткую цитату-подтверждение:
${checklistList}
3. Сделать разбор звонка: краткое резюме, что было сделано хорошо, что плохо, конкретные
   рекомендации по улучшению для этого администратора.

Ответь СТРОГО в формате JSON без markdown, по схеме:
{
  "detected_staff_name": string | null,
  "matched_staff_full_name": string | null,
  "summary": string,
  "strengths": string,
  "weaknesses": string,
  "recommendations": string,
  "checklist": [ { "item_id": number, "passed": boolean, "evidence": string } ]
}`;

  return { system, user: `Расшифровка звонка:\n\n${transcript}` };
}

async function analyzeTranscript({ transcript, companyContext, staffNames, checklist, model, apiKey }) {
  const { system, user } = buildAnalysisPrompt({ companyContext, transcript, staffNames, checklist });

  const resp = await fetch(`${OPENAI_BASE}/chat/completions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      messages: [
        { role: 'system', content: system },
        { role: 'user', content: user }
      ],
      response_format: { type: 'json_object' },
      temperature: 0.2
    })
  });
  const json = await resp.json();
  if (!resp.ok) throw new Error(`OpenAI analysis error: ${json.error?.message || resp.status}`);

  const content = json.choices?.[0]?.message?.content || '{}';
  let parsed;
  try {
    parsed = JSON.parse(content);
  } catch (e) {
    throw new Error('ИИ вернул невалидный JSON: ' + content.slice(0, 200));
  }

  // Грубая оценка стоимости анализа — уточняется по факту использования (см. счётчики расходов).
  const usage = json.usage || {};
  const costUsd = ((usage.prompt_tokens || 0) * 0.15 + (usage.completion_tokens || 0) * 0.6) / 1_000_000;

  return { parsed, costUsd };
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

    const staff = db.prepare(`
      SELECT u.full_name FROM users u
      JOIN user_salons us ON us.user_id = u.id
      WHERE us.salon_id = ? AND u.active = 1
    `).all(salon.id).map(r => r.full_name);

    const checklist = getEffectiveChecklist(salon.id);

    const { parsed, costUsd: analysisCost } = await analyzeTranscript({
      transcript,
      companyContext: settings.company_context,
      staffNames: staff,
      checklist,
      model: settings.analysis_model,
      apiKey: settings.openai_api_key
    });
    logUsage(callId, 'analysis', analysisCost);

    let matchedUserId = null;
    if (parsed.matched_staff_full_name) {
      const match = db.prepare(`
        SELECT u.id FROM users u
        JOIN user_salons us ON us.user_id = u.id
        WHERE us.salon_id = ? AND u.full_name = ? AND u.active = 1
      `).get(salon.id, parsed.matched_staff_full_name);
      matchedUserId = match ? match.id : null;
    }

    db.prepare(`
      UPDATE calls SET
        status = 'done',
        transcript = ?,
        detected_staff_name = ?,
        matched_user_id = ?,
        summary = ?,
        strengths = ?,
        weaknesses = ?,
        recommendations = ?,
        checklist_results = ?,
        processed_at = datetime('now')
      WHERE id = ?
    `).run(
      transcript,
      parsed.detected_staff_name || null,
      matchedUserId,
      parsed.summary || null,
      parsed.strengths || null,
      parsed.weaknesses || null,
      parsed.recommendations || null,
      JSON.stringify(mergeChecklist(checklist, parsed.checklist)),
      callId
    );
  } catch (err) {
    db.prepare(`UPDATE calls SET status='error', error_message=? WHERE id=?`).run(err.message, callId);
    throw err;
  }
}

// склеиваем эталонный список пунктов с ответом ИИ, чтобы не потерять пункт,
// если ИИ вдруг пропустил его в ответе
function mergeChecklist(templateItems, aiResults) {
  const byId = new Map((aiResults || []).map(r => [Number(r.item_id), r]));
  return templateItems.map(item => {
    const r = byId.get(item.id);
    return {
      item_id: item.id,
      text: item.text,
      passed: r ? !!r.passed : false,
      evidence: r ? (r.evidence || '') : ''
    };
  });
}

module.exports = { processCall };
