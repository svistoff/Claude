"""API-эндпоинты (§20 ТЗ). Названия/набор соответствуют ТЗ; ТЗ прямо допускает
их изменение при реализации."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from randomgiveaway.adapters.import_adapter import ImportAdapter
from randomgiveaway.adapters.instagram_adapter import InstagramAdapter
from randomgiveaway.adapters.telegram_adapter import TelegramAdapter
from randomgiveaway.adapters.vk_adapter import VKAdapter
from randomgiveaway.api.schemas import (
    CreateGiveawayRequest,
    DrawResultOut,
    GiveawayOut,
    ParticipantsPreviewOut,
    PublicResultOut,
    WinnerOut,
)
from randomgiveaway.config import ENV_PATH, config
from randomgiveaway.database.models import Participant, Winner
from randomgiveaway.env_file import set_env_var
from randomgiveaway.services import giveaways as giveaway_service
from randomgiveaway.services import instagram_oauth

router = APIRouter(prefix="/api")

_LIVE_ADAPTERS = {
    "instagram": lambda: InstagramAdapter(config.instagram_access_token),
    "vk": lambda: VKAdapter(config.vk_community_token),
    "telegram": lambda: TelegramAdapter(config.telegram_session),
}


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Простая защита мутирующих ручек без полноценной регистрации
    пользователей (§17, §24 ТЗ). Если ADMIN_TOKEN не задан в .env — проверка
    отключена (удобно для локальной разработки), это осознанный компромисс
    для Этапа 1, а не финальная модель безопасности."""
    if config.admin_token and x_admin_token != config.admin_token:
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий административный токен")


def _to_winner_out(w: Winner, p: Participant) -> WinnerOut:
    return WinnerOut(
        position=w.position,
        source_user_id=p.source_user_id,
        username=p.username,
        display_name=p.display_name,
        comment_count=p.comment_count,
    )


@router.post("/giveaways", response_model=GiveawayOut, dependencies=[Depends(require_admin)])
async def create_giveaway_endpoint(payload: CreateGiveawayRequest) -> GiveawayOut:
    g = await giveaway_service.create_giveaway(
        source=payload.source,
        post_url=payload.post_url,
        title=payload.title,
        settings=payload.settings.to_domain(),
        post_author_user_id=payload.post_author_user_id,
    )
    return GiveawayOut.from_domain(g)


@router.get("/giveaways/{giveaway_id}", response_model=GiveawayOut)
async def get_giveaway_endpoint(giveaway_id: int) -> GiveawayOut:
    g = await giveaway_service.get_giveaway(giveaway_id)
    return GiveawayOut.from_domain(g)


@router.post(
    "/giveaways/{giveaway_id}/import",
    response_model=ParticipantsPreviewOut,
    dependencies=[Depends(require_admin)],
)
async def import_participants(
    giveaway_id: int,
    file: UploadFile = File(...),
    format: str = Form(...),
) -> ParticipantsPreviewOut:
    """Импорт участников (§19 ТЗ). format: csv | json | list."""
    raw = await file.read()
    parsers = {
        "csv": ImportAdapter.parse_csv,
        "json": ImportAdapter.parse_json,
        "list": ImportAdapter.parse_username_list,
    }
    parser = parsers.get(format)
    if parser is None:
        raise HTTPException(status_code=400, detail=f"Неизвестный формат импорта: {format}")

    comments = parser(raw)
    preview = await giveaway_service.load_comments(giveaway_id, comments)
    return ParticipantsPreviewOut(
        total_comments=preview.total_comments,
        unique_users=preview.unique_users,
        repeated_comments=preview.repeated_comments,
        participants_before_rules=preview.participants_before_rules,
        participants_after_rules=preview.participants_after_rules,
    )


@router.post(
    "/giveaways/{giveaway_id}/load-comments",
    response_model=ParticipantsPreviewOut,
    dependencies=[Depends(require_admin)],
)
async def load_comments_live(giveaway_id: int) -> ParticipantsPreviewOut:
    """Живые источники (Instagram/VK/Telegram) — заготовка под Этап 4, см.
    randomgiveaway/adapters/*. На Этапе 1 отвечает понятным 501, пока не
    реализовано — используйте /import."""
    g = await giveaway_service.get_giveaway(giveaway_id)
    factory = _LIVE_ADAPTERS.get(g.source)
    if factory is None:
        raise HTTPException(status_code=400, detail=f"Источник «{g.source}» не поддерживает загрузку по ссылке")

    adapter = factory()
    comments = await adapter.fetch_comments(g.post_url)
    preview = await giveaway_service.load_comments(giveaway_id, comments)
    return ParticipantsPreviewOut(
        total_comments=preview.total_comments,
        unique_users=preview.unique_users,
        repeated_comments=preview.repeated_comments,
        participants_before_rules=preview.participants_before_rules,
        participants_after_rules=preview.participants_after_rules,
    )


@router.post("/giveaways/{giveaway_id}/participants/process", response_model=ParticipantsPreviewOut)
async def get_participants_preview(giveaway_id: int) -> ParticipantsPreviewOut:
    """Предпросмотр участников перед стартом (§8 ТЗ) — по уже загруженным
    данным, без повторного обращения к источнику."""
    g = await giveaway_service.get_giveaway(giveaway_id)
    active_participants = await giveaway_service.get_active_participants(giveaway_id)
    all_participants_count = await giveaway_service.count_all_participants(giveaway_id)
    return ParticipantsPreviewOut(
        total_comments=g.comments_count,
        participants_before_rules=all_participants_count,
        participants_after_rules=len(active_participants),
    )


@router.post("/giveaways/{giveaway_id}/draw", response_model=DrawResultOut, dependencies=[Depends(require_admin)])
async def draw_giveaway(giveaway_id: int) -> DrawResultOut:
    g, _winners, _backups = await giveaway_service.perform_draw(giveaway_id)
    pairs = await giveaway_service.get_winners_with_participants(giveaway_id)
    winners = [_to_winner_out(w, p) for w, p in pairs if not w.is_backup]
    backups = [_to_winner_out(w, p) for w, p in pairs if w.is_backup]
    return DrawResultOut(giveaway=GiveawayOut.from_domain(g), winners=winners, backups=backups)


@router.get("/giveaways/{giveaway_id}/result", response_model=DrawResultOut)
async def get_result(giveaway_id: int) -> DrawResultOut:
    g = await giveaway_service.get_giveaway(giveaway_id)
    if g.status != "DRAWN":
        raise HTTPException(status_code=404, detail="Розыгрыш ещё не проведён")
    pairs = await giveaway_service.get_winners_with_participants(giveaway_id)
    winners = [_to_winner_out(w, p) for w, p in pairs if not w.is_backup]
    backups = [_to_winner_out(w, p) for w, p in pairs if w.is_backup]
    return DrawResultOut(giveaway=GiveawayOut.from_domain(g), winners=winners, backups=backups)


@router.get("/results/{public_id}", response_model=PublicResultOut)
async def get_public_result(public_id: str) -> PublicResultOut:
    """Публичная страница результата (§12 ТЗ) — без авторизации, без
    внутреннего numeric id, только public_id."""
    g = await giveaway_service.get_giveaway_by_public_id(public_id)
    if g.status != "DRAWN":
        raise HTTPException(status_code=404, detail="Результат ещё не готов")
    pairs = await giveaway_service.get_winners_with_participants(g.id)
    winners = [_to_winner_out(w, p) for w, p in pairs if not w.is_backup]
    backups = [_to_winner_out(w, p) for w, p in pairs if w.is_backup]
    return PublicResultOut(
        public_id=g.public_id,
        title=g.title,
        source=g.source,
        post_url=g.post_url,
        created_at=g.created_at,
        drawn_at=g.drawn_at,
        comments_count=g.comments_count,
        participants_count=g.participants_count,
        winners_count=g.winners_count,
        backup_winners_count=g.backup_winners_count,
        algorithm_version=g.algorithm_version,
        participants_hash=g.participants_hash,
        result_hash=g.result_hash,
        winners=winners,
        backups=backups,
    )


# --- Instagram OAuth: разовая привязка собственного аккаунта ekb_guide ---
# (см. services/instagram_oauth.py и README.md). Это не публичная кнопка
# "Войти через Instagram" для организаторов — вызывается один раз
# администратором, залогиненным как ekb_guide.
#
# /start защищён require_admin (нужен X-Admin-Token) — без этого кто угодно,
# наткнувшись на ссылку, мог бы авторизовать приложение своим Instagram-
# аккаунтом и подменить INSTAGRAM_ACCESS_TOKEN в .env своим токеном.
# state дополнительно защищает сам /callback от CSRF/replay — принимается
# только code, полученный в ответ на state, который мы сами сгенерировали
# в /start (см. README.md, как пройти /start из браузера при включённом
# ADMIN_TOKEN).

INSTAGRAM_SCOPES = "instagram_business_basic,instagram_business_manage_comments"

_pending_oauth_states: set[str] = set()


@router.get("/instagram/oauth/start", dependencies=[Depends(require_admin)])
async def instagram_oauth_start() -> RedirectResponse:
    if not (config.instagram_app_id and config.instagram_oauth_redirect_uri):
        raise HTTPException(
            status_code=400,
            detail="INSTAGRAM_APP_ID / INSTAGRAM_OAUTH_REDIRECT_URI не заданы в .env",
        )
    state = secrets.token_urlsafe(24)
    _pending_oauth_states.add(state)
    url = (
        "https://www.instagram.com/oauth/authorize"
        f"?client_id={config.instagram_app_id}"
        f"&redirect_uri={config.instagram_oauth_redirect_uri}"
        f"&response_type=code&scope={INSTAGRAM_SCOPES}"
        f"&state={state}"
    )
    return RedirectResponse(url)


@router.get("/instagram/oauth/callback")
async def instagram_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> HTMLResponse:
    if error:
        return HTMLResponse(
            f"<h1>Instagram отказал в авторизации</h1><p>{error}: {error_description}</p>",
            status_code=400,
        )
    if not state or state not in _pending_oauth_states:
        raise HTTPException(
            status_code=400,
            detail="Неизвестный или уже использованный state — начните заново с /api/instagram/oauth/start",
        )
    _pending_oauth_states.discard(state)
    if not code:
        raise HTTPException(status_code=400, detail="Instagram не вернул code")
    if not (config.instagram_app_id and config.instagram_app_secret and config.instagram_oauth_redirect_uri):
        raise HTTPException(
            status_code=500,
            detail="INSTAGRAM_APP_ID / INSTAGRAM_APP_SECRET / INSTAGRAM_OAUTH_REDIRECT_URI не заданы в .env",
        )

    try:
        token, expires_in = await instagram_oauth.exchange_code_for_long_lived_token(
            code,
            config.instagram_app_id,
            config.instagram_app_secret,
            config.instagram_oauth_redirect_uri,
        )
    except instagram_oauth.InstagramOAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    set_env_var(ENV_PATH, "INSTAGRAM_ACCESS_TOKEN", token)
    days = expires_in // 86400
    return HTMLResponse(
        "<h1>Instagram подключён</h1>"
        f"<p>Токен сохранён в .env, действителен ещё ~{days} дней.</p>"
        "<p>Перезапустите сервис, чтобы он подхватил новый токен:<br>"
        "<code>sudo supervisorctl restart random-giveaway-api</code></p>"
        "<p>И настройте автопродление по cron — см. randomgiveaway/README.md "
        "(scripts/refresh_instagram_token.py), иначе токен молча истечёт через ~60 дней.</p>"
    )
