create table if not exists event_videos (
  id                  uuid primary key default gen_random_uuid(),
  token               text unique not null,
  file_id             text not null,          -- file_id копии из канала-хранилища
  channel_message_id  bigint not null,        -- для deleteMessage
  telegram_user_id    bigint,
  event_id            uuid references events(id) on delete set null,  -- nullable
  event_date          date,                   -- дата события (для авто-удаления)
  created_at          timestamptz default now(),
  deleted             boolean default false
);

alter table event_videos enable row level security;
-- Доступ только через service_role (бот/прокси/крон). Политик для anon НЕ создаём:
-- при включённом RLS без политик anon не читает — это и нужно.
