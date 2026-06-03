import logging
import time
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from config import ADMIN_EMAIL, ADMIN_EMAILS, IS_PROD
from database import RpcUnavailable, close_async_client, db_select, db_update
from engine.admin_audit import fetch_last_24h, mask_email
from engine.email import send_admin_log
from engine.market import ensure_market_seeded
from engine.npcs import ensure_all_pools_seeded
from routers import admin, admin_otp, auth, blacksmith, character, command, dashboard, internal, npc
from routers.auth import blacklist_table_ready, purge_expired_blacklist
from routers.csrf import CSRF_COOKIE, CSRF_MAX_AGE, csrf_protect, issue_csrf_token

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def sync_admin_emails() -> None:
    """ADMIN_EMAILS 환경변수를 단일 출처로 users.is_admin 동기화.

    - ADMIN_EMAILS의 이메일을 가진 users → is_admin=TRUE (UPGRADE)
    - ADMIN_EMAILS에 없는 이메일의 users.is_admin=TRUE 행 → FALSE (DOWNGRADE)

    .env가 비어있으면 안전망으로 스킵 (대량 downgrade 사고 방지).
    """
    if not ADMIN_EMAILS:
        logger.warning("ADMIN_EMAILS 비어있음 — 부트스트랩 스킵")
        return

    target = {e.lower() for e in ADMIN_EMAILS}
    all_users = db_select("users")
    upgraded, downgraded = 0, 0

    for u in all_users:
        email = (u.get("email") or "").strip().lower()
        is_admin = bool(u.get("is_admin"))
        should_be_admin = bool(email) and email in target
        if should_be_admin and not is_admin:
            db_update("users", {"is_admin": True}, id=u["id"])
            upgraded += 1
        elif not should_be_admin and is_admin:
            db_update("users", {"is_admin": False}, id=u["id"])
            downgraded += 1

    logger.info(
        "ADMIN_EMAILS 부트스트랩: 목록 %d명 / UPGRADE %d, DOWNGRADE %d",
        len(target),
        upgraded,
        downgraded,
    )
    if upgraded == 0 and len(target) > 0:
        logger.warning(
            "ADMIN_EMAILS의 이메일과 매치되는 users.email 행이 없음 — "
            "users.email 컬럼에 본인 이메일을 채웠는지 확인하세요."
        )


def _send_daily_admin_log() -> None:
    if not ADMIN_EMAIL:
        logger.info("ADMIN_EMAIL 비어있음 — 자정 이메일 스킵")
        return
    entries = fetch_last_24h()
    ok = send_admin_log(ADMIN_EMAIL, entries)
    logger.info(
        "자정 admin 로그 발송: %d건 → %s (%s)",
        len(entries),
        mask_email(ADMIN_EMAIL),
        "OK" if ok else "FAIL",
    )


_scheduler: AsyncIOScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    sync_admin_emails()

    try:
        result = ensure_market_seeded()
        logger.info("ensure_market_seeded: %s", result)
    except Exception as e:
        logger.error("ensure_market_seeded 실패 — DB 미적용일 수 있음: %s", e)

    try:
        npc_result = ensure_all_pools_seeded()
        logger.info("ensure_all_pools_seeded: %s", npc_result)
    except Exception as e:
        logger.error("ensure_all_pools_seeded 실패 — P5 마이그레이션 미적용일 수 있음: %s", e)

    if blacklist_table_ready():
        logger.info("jwt_blacklist 확인: JWT revocation 활성")
    else:
        logger.error(
            "jwt_blacklist 테이블 없음 — JWT revocation 비활성. migration_jwt_blacklist.sql 실행 필요"
        )

    global _scheduler
    if not IS_PROD:
        # 로컬 dev — 인프로세스 스케줄러로 자정 작업 수행.
        # prod(Cloud Run scale-to-zero)는 인스턴스가 잠들어 APScheduler가 못 도므로
        # Cloud Scheduler가 /internal/maintenance를 호출해 대체한다.
        _scheduler = AsyncIOScheduler(timezone=ZoneInfo("Asia/Seoul"))
        _scheduler.add_job(_send_daily_admin_log, "cron", hour=0, minute=0, id="daily_admin_log")
        _scheduler.add_job(
            purge_expired_blacklist, "cron", hour=0, minute=5, id="purge_jwt_blacklist"
        )
        _scheduler.start()
        logger.info("APScheduler 시작 (로컬 dev — 자정 작업 인프로세스, KST)")
    else:
        logger.info("IS_PROD — APScheduler 비활성 (Cloud Scheduler가 /internal/maintenance 호출)")

    yield

    if _scheduler:
        _scheduler.shutdown(wait=False)
    await close_async_client()


app = FastAPI(lifespan=lifespan, dependencies=[Depends(csrf_protect)])
app.mount("/static", StaticFiles(directory="static"), name="static")


# [보안 패스] RPC 미존재(404)·도달불가 → 사용자에게 500 대신 친절 안내(작업실 배너).
# database.db_rpc가 RpcUnavailable로 승격 + ERROR 로그를 남긴 상태. RPC 사용 라우트는 전부
# 인증된 POST 폼이라 /dashboard 리다이렉트가 UX 정합. 5개 RPC가 단일 마이그라 현실적 실패는
# '전부 누락' = 각 흐름 첫 RPC가 변형 전 404 → 깔끔한 중단(부분 변형 없음).
@app.exception_handler(RpcUnavailable)
async def _rpc_unavailable_handler(request: Request, exc: RpcUnavailable):
    return RedirectResponse("/dashboard?warn=service_unavailable#workshop", status_code=302)


# R-1: 응답 시간 측정 + [S8] 보안 응답 헤더 (CSP·HTTPS 리다이렉트는 P+/배포 단계)
@app.middleware("http")
async def add_response_headers(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.0f}"
    if elapsed_ms >= 500:
        logger.warning("SLOW %.0fms %s %s", elapsed_ms, request.method, request.url.path)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if IS_PROD:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# [S8] CSRF double-submit 쿠키 발급 + request.state 노출 (검증은 csrf_protect 전역 의존성)
@app.middleware("http")
async def csrf_cookie(request: Request, call_next):
    existing = request.cookies.get(CSRF_COOKIE)
    token = existing or issue_csrf_token()
    request.state.csrf_token = token
    response = await call_next(request)
    if not existing:
        response.set_cookie(
            CSRF_COOKIE,
            token,
            httponly=True,
            secure=IS_PROD,
            samesite="lax",
            max_age=CSRF_MAX_AGE,
        )
    return response


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(character.router)
app.include_router(blacksmith.router)
app.include_router(command.router)
app.include_router(npc.router)
app.include_router(admin.router)
app.include_router(admin_otp.router)
app.include_router(internal.router)
