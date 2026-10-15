#!/usr/bin/env bash
# Автодеплой: раз в INTERVAL секунд смотрит, появились ли на GitHub новые коммиты
# в ветках, из которых работает VPS, подтягивает их (только fast-forward)
# и, если менялся код бота, обновляет его и перезапускает через Supervisor.
# Статика сайтов (afisha-site, news-bot/site) отдаётся nginx прямо из клонов,
# поэтому для неё достаточно git pull.
set -u
INTERVAL="${INTERVAL:-60}"

log() { echo "$(date '+%F %T') $*" >&2; }  # stdout занят списком файлов из pull_repo

# pull_repo <папка клона> <ветка> → печатает список изменённых файлов (пусто, если нечего)
pull_repo() {
  local dir="$1" branch="$2" old new
  cd "$dir" || { log "нет папки $dir"; return 1; }
  git fetch -q origin "$branch" || { log "$dir: fetch не удался"; return 1; }
  old=$(git rev-parse HEAD); new=$(git rev-parse "origin/$branch")
  [ "$old" = "$new" ] && return 0
  if ! git merge --ff-only -q "origin/$branch"; then
    log "$dir: не fast-forward (локальные правки?), пропускаю"; return 1
  fi
  log "$dir: $old → $new"
  git diff --name-only "$old" "$new"
}

deploy_news_bot() {
  log "news-bot: обновляю код и перезапускаю"
  rsync -a --delete --exclude venv --exclude bot/.env --exclude __pycache__ --exclude site \
    /root/afisha-news-bot/news-bot/ /root/news-bot/ || return 1
  /root/news-bot/venv/bin/pip install -q -r /root/news-bot/requirements.txt || return 1
  supervisorctl restart news-bot news-media-proxy
}

while true; do
  # news-bot: сайт news.ekb-guide.ru, виджет и сам бот
  changed=$(pull_repo /root/afisha-news-bot claude/news-bot)
  if echo "$changed" | grep -q '^news-bot/' && echo "$changed" | grep '^news-bot/' | grep -qv '^news-bot/site/'; then
    deploy_news_bot
  fi

  # афиша: статика afisha.ekb-guide.ru из /root/claude-repo (ветка, на которой стоит клон)
  if [ -d /root/claude-repo/.git ]; then
    b=$(git -C /root/claude-repo rev-parse --abbrev-ref HEAD)
    pull_repo /root/claude-repo "$b" >/dev/null
  fi

  sleep "$INTERVAL"
done
