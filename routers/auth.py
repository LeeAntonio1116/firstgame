import contextlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import StrictUndefined

from config import INVITE_CODE, IS_PROD, JWT_ALGORITHM, JWT_EXPIRE_DAYS, JWT_SECRET
from database import db_delete, db_insert, db_select
from routers.ratelimit import allow, client_ip

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.undefined = StrictUndefined


def create_token(user_id: str, username: str) -> str:
    expire = datetime.now(UTC) + timedelta(days=JWT_EXPIRE_DAYS)
    return jwt.encode(
        {
            "sub": user_id,
            "username": username,
            "exp": expire,
            "jti": secrets.token_urlsafe(16),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def get_current_user(request: Request) -> dict | None:
    token = request.cookies.get("token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    if is_token_revoked(payload.get("jti")):
        return None
    return payload


def is_token_revoked(jti: str | None) -> bool:
    """jti가 블랙리스트(jwt_blacklist)에 있으면 True. jti 없는 옛 토큰은 미차단(exp까지 유효)."""
    if not jti:
        return False
    try:
        return bool(db_select("jwt_blacklist", jti=jti))
    except Exception as exc:
        # 조회 실패 시 인증을 막지 않음(가용성 우선). 단 누락/장애를 가시화하기 위해 로깅.
        logger.warning("jwt_blacklist 조회 실패 — revocation 미적용 가능: %s", exc)
        return False


def revoke_token(token: str | None) -> None:
    """로그아웃·탈퇴 시 토큰 jti를 블랙리스트에 등록 (best-effort)."""
    if not token:
        return
    try:
        payload = jwt.decode(
            token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"verify_exp": False}
        )
    except jwt.PyJWTError:
        return
    jti = payload.get("jti")
    if not jti:
        return
    exp = payload.get("exp")
    expires_at = datetime.fromtimestamp(exp, UTC).isoformat() if exp else None
    # 중복 jti(이미 로그아웃) 등은 무시 (best-effort)
    with contextlib.suppress(Exception):
        db_insert("jwt_blacklist", {"jti": jti, "expires_at": expires_at})


def purge_expired_blacklist() -> int:
    """만료된 블랙리스트 행 정리(housekeeping). 삭제 건수 반환."""
    try:
        now = datetime.now(UTC).isoformat()
        rows = db_select("jwt_blacklist")
        expired = [r["jti"] for r in rows if (r.get("expires_at") or "") and r["expires_at"] < now]
        for jti in expired:
            db_delete("jwt_blacklist", jti=jti)
        return len(expired)
    except Exception:
        return 0


def blacklist_table_ready() -> bool:
    """jwt_blacklist 접근 가능 여부 (부팅 점검 — 미적용 시 revocation 무력화 경고용)."""
    try:
        db_select("jwt_blacklist", jti="__healthcheck__")
        return True
    except Exception:
        return False


# ── 로그인 ──────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if not allow(f"login:{client_ip(request)}", 10, 60):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "error": "로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요."},
        )
    rows = db_select("users", username=username)
    if not rows:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "error": "아이디 또는 비밀번호가 틀렸습니다."},
        )

    user = rows[0]
    if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "error": "아이디 또는 비밀번호가 틀렸습니다."},
        )

    token = create_token(user["id"], user["username"])
    response = RedirectResponse("/dashboard", status_code=302)
    response.set_cookie(
        "token",
        token,
        httponly=True,
        secure=IS_PROD,
        samesite="lax",
        max_age=JWT_EXPIRE_DAYS * 86400,
    )
    return response


# ── 회원가입 ─────────────────────────────────────────────
@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "register.html", {"request": request, "error": None})


@router.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    invite_code: str = Form(...),
):
    if not allow(f"register:{client_ip(request)}", 5, 600):
        return templates.TemplateResponse(
            request,
            "register.html",
            {"request": request, "error": "가입 시도가 너무 많습니다. 잠시 후 다시 시도하세요."},
        )
    if not INVITE_CODE or invite_code != INVITE_CODE:
        return templates.TemplateResponse(
            request, "register.html", {"request": request, "error": "초대코드가 올바르지 않습니다."}
        )
    if password != password_confirm:
        return templates.TemplateResponse(
            request, "register.html", {"request": request, "error": "비밀번호가 일치하지 않습니다."}
        )
    if len(username) < 2 or len(username) > 20:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"request": request, "error": "아이디는 2~20자 사이여야 합니다."},
        )
    if len(password) < 6:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"request": request, "error": "비밀번호는 6자 이상이어야 합니다."},
        )

    if db_select("users", username=username):
        return templates.TemplateResponse(
            request, "register.html", {"request": request, "error": "이미 사용 중인 아이디입니다."}
        )

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    # P4-1: 신규 가입 시 자금 500량 지급 ([[시장_시스템]] § 초기 지급)
    db_insert("users", {"username": username, "password_hash": hashed, "gold": 500})
    return RedirectResponse("/login?registered=1", status_code=302)


# ── 로그아웃 ─────────────────────────────────────────────
@router.post("/logout")
async def logout(request: Request):
    revoke_token(request.cookies.get("token"))
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("token", httponly=True, secure=IS_PROD, samesite="lax")
    return response


# ── 회원탈퇴 ─────────────────────────────────────────────
@router.post("/delete-account")
async def delete_account(request: Request, password: str = Form(...)):
    # 순환 import 회피 — dashboard 모듈이 auth.get_current_user를 import하므로 지연 로드
    from routers.dashboard import _build_dashboard_context
    from routers.dashboard import templates as dashboard_templates

    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    rows = db_select("users", id=user["sub"])
    if not rows:
        return RedirectResponse("/login", status_code=302)

    if not bcrypt.checkpw(password.encode(), rows[0]["password_hash"].encode()):
        ctx = await _build_dashboard_context(request, user, delete_error="비밀번호가 틀렸습니다.")
        return dashboard_templates.TemplateResponse(request, "dashboard.html", ctx)

    # E-3: P5에서 commands·mailbox·items의 FK가 제거되고 npc_stat_exp는 FK가 없어 user 삭제 시
    #      cascade되지 않는다. 삭제 전 수동 정리 — characters·npcs·candidates·skills·proficiency·
    #      character_stat_exp·admin_otp·admin_audit_log는 FK CASCADE/SET NULL로 자동 처리됨.
    user_id = user["sub"]
    char_ids = [c["id"] for c in db_select("characters", user_id=user_id)]
    npc_ids = [n["id"] for n in db_select("npcs", owner_id=user_id)]
    for actor_id in char_ids + npc_ids:
        # mailbox.command_id FK가 commands를 참조 → mailbox 먼저 삭제 후 commands
        db_delete("mailbox", character_id=actor_id)
        db_delete("commands", character_id=actor_id)
        db_delete("items", owner_id=actor_id)  # 인벤 (actor 소유)
    for npc_id in npc_ids:
        db_delete("npc_stat_exp", npc_id=npc_id)  # FK 없음 — 수동 삭제
    db_delete("items", owner_id=user_id)  # 창고 (user 공유)
    db_delete("users", id=user_id)
    revoke_token(request.cookies.get("token"))
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("token", httponly=True, secure=IS_PROD, samesite="lax")
    return response
