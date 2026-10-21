// ИИ-оценка разговоров Fuckwell: запись -> транскрипция -> вероятность визита.
// Ключ OpenAI и модели — общие с xmassage (Настройки -> Основное).
// Транскрипция не сохраняется: в базе только оценка, комментарий и признаки.

const db = require('../db');
const { fetchWithTimeout, transcribeAudio } = require('../ai-processing');
const { getSettings, excludedKeys, phoneKey, toDbString } = require('./util');

const SYSTEM_PROMPT = `Ты — ассистент, который оценивает телефонные разговоры салона с клиентами. По расшифровке входящего звонка оцени, насколько вероятно, что клиент после этого разговора РЕАЛЬНО придёт в салон.

Это оценка на основе содержания разговора, а не гарантия. Не завышай оценку.

Повышают оценку: клиент уточнил адрес; спросил, как добраться; спросил режим работы; спросил, можно ли приехать сейчас; назвал конкретное время; подтвердил запись; сказал «сейчас приеду» / «буду через 20 минут»; спросил про свободное место; явно подтвердил намерение приехать.

Снижают оценку: клиент только спросил цену; только интересовался услугой; сказал «я подумаю» / «перезвоню позже»; разговор закончился без намерения приехать; отказ; просто выяснял общую информацию.

Верни СТРОГО JSON-объект без пояснений вида:
{"visit_probability": <целое 0..100>, "comment": "<1-2 предложения по-русски>", "signals": ["<короткий признак>", "..."]}`;

const DOWNLOAD_ATTEMPTS = 6;
const DOWNLOAD_BACKOFF_MS = 4000;
const RETRYABLE_MARKERS = ['таймаут', 'timeout', 'connect', 'network', 'обрыв связи', 'temporarily', 'fetch failed', 'econn'];

const sleep = ms => new Promise(r => setTimeout(r, ms));

// сервер ВАТС режет зарубежные IP — записи качаем через российский мост
// (record.php на Timeweb), он же подставляет X-API-KEY для закрытых записей
async function downloadRecording(url, settings) {
  const viaProxy = settings.recording_proxy_url && settings.bridge_secret;
  const target = viaProxy
    ? `${settings.recording_proxy_url}?${new URLSearchParams({ t: settings.bridge_secret, u: url })}`
    : url;
  let lastErr;
  for (let attempt = 1; attempt <= DOWNLOAD_ATTEMPTS; attempt++) {
    try {
      let resp = await fetchWithTimeout(target, {}, 90_000);
      if (!viaProxy && (resp.status === 401 || resp.status === 403) && settings.megafon_api_key) {
        resp = await fetchWithTimeout(target, { headers: { 'X-API-KEY': settings.megafon_api_key } }, 90_000);
      }
      if (!resp.ok) throw Object.assign(new Error(`Запись не скачалась: HTTP ${resp.status}`), { fatal: true });
      return Buffer.from(await resp.arrayBuffer());
    } catch (err) {
      if (err.fatal) throw err;
      lastErr = err;
      console.warn(`[fuckwell] запись не скачалась (попытка ${attempt}/${DOWNLOAD_ATTEMPTS}): ${err.message}`);
      if (attempt < DOWNLOAD_ATTEMPTS) await sleep(DOWNLOAD_BACKOFF_MS);
    }
  }
  throw new Error(`Не удалось скачать запись за ${DOWNLOAD_ATTEMPTS} попыток (обрыв связи с сервером ВАТС): ${lastErr && lastErr.message}`);
}

async function analyzeTranscript(transcript, aiSettings) {
  const resp = await fetchWithTimeout('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: { Authorization: `Bearer ${aiSettings.openai_api_key}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: aiSettings.analysis_model,
      messages: [{ role: 'system', content: SYSTEM_PROMPT }, { role: 'user', content: `Расшифровка разговора:\n\n${transcript}` }],
      response_format: { type: 'json_object' }
    })
  }, 120_000);
  const json = await resp.json();
  if (!resp.ok) throw new Error(`OpenAI: ${json.error?.message || resp.status}`);
  const parsed = JSON.parse(json.choices?.[0]?.message?.content || '{}');
  const prob = Number.parseInt(parsed.visit_probability, 10);
  const costUsd = ((json.usage?.prompt_tokens || 0) * 0.15 + (json.usage?.completion_tokens || 0) * 0.6) / 1_000_000;
  db.prepare('INSERT INTO ai_usage (call_id, kind, cost_usd) VALUES (NULL, ?, ?)').run('fw_analysis', costUsd);
  return {
    visit_probability: Number.isFinite(prob) ? Math.max(0, Math.min(100, prob)) : null,
    comment: String(parsed.comment || '').trim() || null,
    signals: Array.isArray(parsed.signals) ? parsed.signals.map(String) : null
  };
}

function setAnalysis(callId, fields) {
  const cols = Object.keys(fields);
  db.prepare(`UPDATE fw_analyses SET ${cols.map(c => `${c} = ?`).join(', ')}, updated_at = datetime('now') WHERE call_id = ?`)
    .run(...cols.map(c => fields[c]), callId);
}

// безопасно вызывать повторно: готовый анализ не трогается
async function processAnalysis(callId) {
  const aiSettings = db.prepare('SELECT * FROM ai_settings WHERE id = 1').get();
  if (!aiSettings.openai_api_key) return;
  const call = db.prepare('SELECT * FROM fw_calls WHERE call_id = ?').get(callId);
  if (!call) return;
  db.prepare('INSERT OR IGNORE INTO fw_analyses (call_id) VALUES (?)').run(callId);
  const analysis = db.prepare('SELECT * FROM fw_analyses WHERE call_id = ?').get(callId);
  if (analysis.status === 'done') return;

  if (!shouldAnalyze(call)) {
    setAnalysis(callId, { status: 'skipped', error: 'Прямой звонок на номер салона или исключённый номер — не анализируется' });
    return;
  }
  const settings = getSettings();
  const success = (call.status || '').toLowerCase() === 'success';
  if (!success || !call.recording_url || (call.duration || 0) < settings.ai_min_duration_sec) {
    setAnalysis(callId, { status: 'skipped', error: 'Пропущенный звонок или нет записи/короткий разговор' });
    return;
  }

  setAnalysis(callId, { status: 'processing', model: aiSettings.analysis_model });
  try {
    const audio = await downloadRecording(call.recording_url, settings);
    const { text, costUsd } = await transcribeAudio(audio, aiSettings.transcribe_model, aiSettings.openai_api_key, call.duration || 0);
    db.prepare('INSERT INTO ai_usage (call_id, kind, cost_usd) VALUES (NULL, ?, ?)').run('fw_transcribe', costUsd);
    if (!text.trim()) throw new Error('Пустая транскрипция');
    const result = await analyzeTranscript(text, aiSettings);
    setAnalysis(callId, {
      status: 'done', visit_probability: result.visit_probability, ai_comment: result.comment,
      signals: result.signals ? JSON.stringify(result.signals) : null, error: null, analyzed_at: toDbString(new Date())
    });
  } catch (err) {
    console.error(`[fuckwell] ошибка анализа ${callId}:`, err.message);
    setAnalysis(callId, { status: 'failed', error: String(err.message || err).slice(0, 500) });
  }
}

// очередь, чтобы вебхуки не запускали десятки параллельных скачиваний/транскрибаций
let queue = Promise.resolve();
function enqueueAnalysis(callId) {
  queue = queue.then(() => processAnalysis(callId)).catch(err => console.error('[fuckwell] очередь ИИ:', err.message));
  return queue;
}

// звонки на прямые номера салонов и с исключённых номеров не разбираем — не тратим ИИ
function shouldAnalyze(call) {
  if (call.number_id && db.prepare(`SELECT 1 FROM fw_numbers WHERE id = ? AND kind = 'salon'`).get(call.number_id)) return false;
  return !excludedKeys().has(phoneKey(call.client_phone));
}

// при старте: дообработать зависшие и повторить упавшие из-за обрыва связи
function rescanPending(limit = 50) {
  const stuck = db.prepare(`SELECT call_id FROM fw_analyses WHERE status IN ('pending', 'processing') LIMIT ?`).all(limit);
  const failedNet = db.prepare(`SELECT call_id, error FROM fw_analyses WHERE status = 'failed' LIMIT 500`).all()
    .filter(r => RETRYABLE_MARKERS.some(m => (r.error || '').toLowerCase().includes(m))).slice(0, limit);
  for (const r of failedNet) setAnalysis(r.call_id, { status: 'pending' });
  for (const r of [...stuck, ...failedNet]) enqueueAnalysis(r.call_id);
  return stuck.length + failedNet.length;
}

module.exports = { enqueueAnalysis, shouldAnalyze, rescanPending };
