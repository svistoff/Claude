-- «Новости одной строкой»: таблицы news + news_media.
-- Можно запускать повторно (idempotent).

create table if not exists news (
  id               uuid primary key default gen_random_uuid(),
  slug             text unique not null,
  title            text not null,
  summary          text,
  body             text,
  status           text not null default 'published' check (status in ('published','hidden')),
  published_at     timestamptz not null default now(),
  origin_key       text unique,          -- '<chat_id>:<message_id>' источника, защита от дублей
  telegram_user_id bigint,
  created_at       timestamptz default now()
);
create index if not exists news_status_published_idx on news (status, published_at desc);

create table if not exists news_media (
  id                 uuid primary key default gen_random_uuid(),
  news_id            uuid not null references news(id) on delete cascade,
  position           int  not null default 0,
  kind               text not null check (kind in ('photo','video')),
  token              text unique not null,
  file_id            text not null,      -- file_id копии в канале-хранилище
  channel_message_id bigint not null,    -- для deleteMessage
  width int, height int, duration int,
  created_at         timestamptz default now()
);
create index if not exists news_media_news_idx on news_media (news_id, position);

alter table news       enable row level security;
alter table news_media enable row level security;

-- Публичное чтение только опубликованного
drop policy if exists news_public_read on news;
create policy news_public_read on news
  for select to anon using (status = 'published');

drop policy if exists news_media_public_read on news_media;
create policy news_media_public_read on news_media
  for select to anon
  using (exists (select 1 from news n where n.id = news_id and n.status = 'published'));

-- anon только читает и только нужные колонки
-- (origin_key, telegram_user_id, file_id, channel_message_id наружу не отдаём)
revoke all on news, news_media from anon, authenticated;
-- status нужен политике news_media_public_read (подзапрос выполняется от anon)
grant select (id, slug, title, summary, body, status, published_at) on news to anon;
grant select (news_id, position, kind, token, width, height, duration) on news_media to anon;

-- обновить кэш схемы PostgREST
notify pgrst, 'reload schema';
