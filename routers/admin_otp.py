"""P4-2 관리자 OTP 세션 발급.

8자리 영숫자, 5분 만료, 1회용. 발송 60초 / 검증 IP별 분당 5회 제한.
검증 통과 시 admin_token 쿠키 발급 (1시간 유효). admin 액션 진입은 routers/admin.py."""

from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import StrictUndefined

from config import ADMIN_EMAIL, IS_PROD
from database import db_insert, db_select, db_update
from engine.admin_audit import record as audit
from engine.email import send_otp
from routers.admin import (
    ADMIN_COOKIE,
    ADMIN_SESSION_HOURS,
    _create_admin_session,
    _require_admin,
)
from routers.auth import revoke_token
from routers.ratelimit import client_ip

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")
templates.env.undefined = StrictUndefined


# ── OTP 상수 ───────────────────────────────────────────────
OTP_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
OTP_LENGTH = 8
OTP_EXPIRE_MIN = 5
OTP_SEND_COOLDOWN_SEC = 60
OTP_VERIFY_WINDOW_SEC = 60
OTP_VERIFY_MAX_PER_WINDOW = 5


# ── Rate limit (in-memory) ────────────────────────────────
_otp_send_last: dict[str, float] = {}
_otp_verify_log: dict[str, deque] = defaultdict(deque)


def _can_send_otp(user_id: str) -> bool:
    last = _otp_send_last.get(user_id, 0.0)
    return (time.time() - last) >= OTP_SEND_COOLDOWN_SEC


def _record_otp_send(user_id: str) -> None:
    _otp_send_last[user_id] = time.time()


def _can_verify(ip: str) -> bool:
    now = time.time()
    log = _otp_verify_log[ip]
    while log and (now - log[0]) > OTP_VERIFY_WINDOW_SEC:
        log.popleft()
    return len(log) < OTP_VERIFY_MAX_PER_WINDOW


def _record_verify_attempt(ip: str) -> None:
    _otp_verify_log[ip].append(time.time())


def _generate_otp() -> str:
    return "".join(secrets.choice(OTP_ALPHABET) for _ in range(OTP_LENGTH))


# ── OTP 라우트 ─────────────────────────────────────────────
@router.get("/otp", response_class=HTMLResponse)
async def otp_page(request: Request, sent: int = 0, error: str | None = None):
    try:
        user_row = _require_admin(request)
    except HTTPException as e:
        if e.status_code == 302:
            return RedirectResponse(e.headers["Location"], status_code=302)
        raise
    return templates.TemplateResponse(
        request,
        "admin_otp.html",
        {
            "request": request,
            "admin_email": user_row.get("email") or ADMIN_EMAIL or "(미설정)",
            "sent": bool(sent),
            "error": error,
        },
    )


@router.post("/otp/send")
async def otp_send(request: Request):
    try:
        user_row = _require_admin(request)
    except HTTPException as e:
        if e.status_code == 302:
            return RedirectResponse(e.headers["Location"], status_code=302)
        raise

    user_id = user_row["id"]
    if not _can_send_otp(user_id):
        return RedirectResponse(
            "/admin/otp?error=" + "60초 안에 이미 발송했습니다. 잠시 후 다시 시도하세요.",
            status_code=302,
        )

    to = (user_row.get("email") or ADMIN_EMAIL or "").strip()
    if not to:
        return RedirectResponse(
            "/admin/otp?error="
            + "관리자 이메일이 설정되지 않았습니다 (.env ADMIN_EMAIL 또는 users.email).",
            status_code=302,
        )

    code = _generate_otp()
    expires_at = (datetime.now(UTC) + timedelta(minutes=OTP_EXPIRE_MIN)).isoformat()
    db_insert(
        "admin_otp",
        {
            "user_id": user_id,
            "otp_code": code,
            "expires_at": expires_at,
        },
    )
    ok = send_otp(to, code)
    _record_otp_send(user_id)

    audit(user_id, "/admin/otp/send", {"to": to}, "success" if ok else "send_failed")
    if not ok:
        return RedirectResponse(
            "/admin/otp?error=" + "이메일 발송 실패. 잠시 후 다시 시도하세요.",
            status_code=302,
        )
    return RedirectResponse("/admin/otp?sent=1", status_code=302)


@router.post("/otp/verify")
async def otp_verify(request: Request, otp_code: str = Form(...)):
    try:
        user_row = _require_admin(request)
    except HTTPException as e:
        if e.status_code == 302:
            return RedirectResponse(e.headers["Location"], status_code=302)
        raise

    ip = client_ip(request)
    if not _can_verify(ip):
        return RedirectResponse(
            "/admin/otp?error=" + "검증 시도 한도 초과 (분당 5회). 1분 후 다시 시도하세요.",
            status_code=302,
        )
    _record_verify_attempt(ip)

    code = (otp_code or "").strip().upper()
    if not code:
        return RedirectResponse("/admin/otp?error=" + "코드를 입력하세요.", status_code=302)

    now = datetime.now(UTC).isoformat()
    rows = db_select("admin_otp", user_id=user_row["id"], otp_code=code)
    rows = [r for r in rows if not r.get("consumed_at") and (r.get("expires_at") or "") > now]

    if not rows:
        audit(user_row["id"], "/admin/otp/verify", None, "invalid_or_expired")
        return RedirectResponse(
            "/admin/otp?error=" + "코드가 올바르지 않거나 만료되었습니다.",
            status_code=302,
        )

    db_update("admin_otp", {"consumed_at": now}, id=rows[0]["id"])
    audit(user_row["id"], "/admin/otp/verify", None, "success")

    token = _create_admin_session(user_row["id"])
    resp = RedirectResponse("/admin", status_code=302)
    resp.set_cookie(
        ADMIN_COOKIE,
        token,
        max_age=ADMIN_SESSION_HOURS * 3600,
        httponly=True,
        secure=IS_PROD,
        samesite="strict",
    )
    return resp


@router.post("/logout")
async def admin_logout(request: Request):
    revoke_token(request.cookies.get(ADMIN_COOKIE))
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.delete_cookie(ADMIN_COOKIE, httponly=True, secure=IS_PROD, samesite="strict")
    return resp
