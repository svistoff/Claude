-- Выгрузка из базы старой crm.fuckwell.ru (PostgreSQL) звонков начиная с 2026-11-02
-- в формате импорта Fuckwell. Запуск (от postgres, пароль не нужен):
--   sudo -u postgres psql -d <база> -At -f ~/crm-salons/scripts/fw-legacy-export.sql > /root/fw-legacy.json
-- Секреты (.env старой CRM) не выгружаются. Время — UTC "ГГГГ-ММ-ДД ЧЧ:ММ:СС".
WITH c AS (SELECT * FROM calls WHERE COALESCE(started_at, created_at) >= TIMESTAMPTZ '2026-11-02 00:00:00+00')
SELECT json_build_object(
  'source', 'crm.fuckwell.ru',
  'phone_numbers', (SELECT COALESCE(json_agg(json_build_object(
      'id', id, 'name', name, 'phone', phone, 'comment', comment, 'active', active,
      'created_at', to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))), '[]'::json) FROM phone_numbers),
  'calls', (SELECT COALESCE(json_agg(json_build_object(
      'call_id', call_id, 'phone_number_id', phone_number_id, 'client_phone', client_phone, 'diversion', diversion,
      'telnum_name', telnum_name, 'direction', direction, 'event_type', event_type, 'status', status,
      'started_at', to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
      'duration', duration, 'wait', wait, 'recording_url', recording_url,
      'created_at', to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
      'updated_at', to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))), '[]'::json) FROM c),
  'ai_analyses', (SELECT COALESCE(json_agg(json_build_object(
      'call_id', a.call_id, 'status', a.status, 'visit_probability', a.visit_probability, 'ai_comment', a.ai_comment,
      'signals', a.signals, 'model', a.model, 'error', a.error,
      'analyzed_at', to_char(a.analyzed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
      'created_at', to_char(a.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
      'updated_at', to_char(a.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))), '[]'::json)
    FROM ai_analyses a JOIN c ON c.call_id = a.call_id),
  'excluded_phones', (SELECT COALESCE(json_agg(json_build_object('phone', phone, 'key', key, 'comment', comment)), '[]'::json) FROM excluded_phones)
);
