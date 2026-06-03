"""P4-2 관리자 패널 — 메인 페이지 + 액션 라우트.

권한:
- users.is_admin=TRUE (ADMIN_EMAILS 기반 동기화형 부트스트랩으로만 변경)
- admin 세션 쿠키 (admin_token, OTP 검증 후 1시간 유효)
  ↳ OTP 발급/검증은 routers/admin_otp.py

audit:
- 모든 admin 작업은 admin_audit_log에 자동 INSERT (성공·실패 모두)
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import StrictUndefined

from config import JWT_ALGORITHM, JWT_SECRET
from database import adjust_gold, db_delete, db_insert, db_select, db_update
from engine.admin_audit import record as audit
from engine.batch import run_batch
from engine.market import reset_daily_market
from engine.materials import MATERIALS, ORE_CODES, SKILL_DEFINITIONS
from routers.auth import get_current_user, is_token_revoked

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")
templates.env.undefined = StrictUndefined


# ── 세션 상수 ──────────────────────────────────────────────
ADMIN_SESSION_HOURS = 1
ADMIN_COOKIE = "admin_token"


# ── 권한·세션 헬퍼 ──────────────────────────────────────────
def _load_user_row(user: dict) -> dict | None:
    rows = db_select("users", id=user["sub"])
    return rows[0] if rows else None


def _require_admin(request: Request) -> dict:
    """JWT 쿠키 + users.is_admin=TRUE 검증. 통과 시 user_row 반환."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    row = _load_user_row(user)
    if not row or not row.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access denied")
    return row


def _create_admin_session(user_id: str) -> str:
    expire = datetime.now(UTC) + timedelta(hours=ADMIN_SESSION_HOURS)
    return jwt.encode(
        {
            "sub": user_id,
            "scope": "admin",
            "exp": expire,
            "jti": secrets.token_urlsafe(16),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def _verify_admin_session(request: Request, user_id: str) -> bool:
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        return False
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return False
    if is_token_revoked(payload.get("jti")):
        return False
    return payload.get("scope") == "admin" and payload.get("sub") == user_id


# ── /admin 메인 페이지 ─────────────────────────────────────
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_page(request: Request):
    try:
        user_row = _require_admin(request)
    except HTTPException as e:
        if e.status_code == 302:
            return RedirectResponse(e.headers["Location"], status_code=302)
        raise

    if not _verify_admin_session(request, user_row["id"]):
        return RedirectResponse("/admin/otp", status_code=302)

    # 4섹션 폼 — 본인 캐릭터만 대상 (디버그 도구는 자기 캐릭터에만)
    chars = db_select("characters", user_id=user_row["id"])
    all_users = sorted(db_select("users"), key=lambda u: u.get("username") or "")
    ore_admin_options = sorted(
        [
            {"code": c, "name": MATERIALS[c]["name"], "rarity": MATERIALS[c]["rarity"]}
            for c in ORE_CODES
        ],
        key=lambda x: (x["rarity"], x["code"]),
    )
    material_admin_options = sorted(
        [
            {"code": c, "name": MATERIALS[c]["name"], "rarity": MATERIALS[c]["rarity"]}
            for c in MATERIALS
        ],
        key=lambda x: (x["rarity"], x["code"]),
    )
    skill_admin_options = [
        {"code": "smelting", "name": "제련"},
        {"code": "forging", "name": "단조"},
        {"code": "heat_treat", "name": "열처리"},
        {"code": "finishing", "name": "마감"},
        {"code": "appraisal", "name": "감정"},
        {"code": "talent_management", "name": "인재관리"},
    ]
    recent_audits = sorted(
        db_select("admin_audit_log"),
        key=lambda r: r.get("created_at") or "",
        reverse=True,
    )[:20]
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "request": request,
            "user_row": user_row,
            "characters": chars,
            "all_users": all_users,
            "ore_admin_options": ore_admin_options,
            "material_admin_options": material_admin_options,
            "skill_admin_options": skill_admin_options,
            "recent_audits": recent_audits,
        },
    )


# ── 권한·세션 + audit 공통 보호 ────────────────────────────
def _guard(request: Request) -> dict:
    """admin POST 라우트의 공통 진입 보호. user_row 반환."""
    try:
        user_row = _require_admin(request)
    except HTTPException as e:
        if e.status_code == 302:
            raise HTTPException(status_code=302, headers={"Location": "/login"}) from e
        raise
    if not _verify_admin_session(request, user_row["id"]):
        raise HTTPException(status_code=302, headers={"Location": "/admin/otp"})
    return user_row


def _own_character(user_id: str, character_id: str) -> bool:
    chars = db_select("characters", user_id=user_id)
    return any(c["id"] == character_id for c in chars)


# ── 1섹션: 배치 트리거 ────────────────────────────────────
@router.post("/run-batch")
async def trigger_batch(request: Request):
    try:
        admin = _guard(request)
    except HTTPException as e:
        if e.status_code == 302:
            return RedirectResponse(e.headers["Location"], status_code=302)
        raise
    try:
        run_batch()
        audit(admin["id"], "/admin/run-batch", None, "success")
    except Exception as e:
        logger.exception("run-batch 실패")
        audit(admin["id"], "/admin/run-batch", None, f"failed: {type(e).__name__}")
        raise
    return RedirectResponse("/admin", status_code=302)


@router.post("/reset-market")
async def reset_market(request: Request):
    """P4-1 시장 일일 리셋 — 시세 ±15% 갱신 + 상인 재고 보충 + 유랑상단 라인업 교체."""
    try:
        admin = _guard(request)
    except HTTPException as e:
        if e.status_code == 302:
            return RedirectResponse(e.headers["Location"], status_code=302)
        raise
    try:
        result = reset_daily_market()
        audit(admin["id"], "/admin/reset-market", None, f"success: {result}")
    except Exception as e:
        logger.exception("reset-market 실패")
        audit(admin["id"], "/admin/reset-market", None, f"failed: {type(e).__name__}")
        raise
    return RedirectResponse("/admin", status_code=302)


# ── 2섹션: 콘텐츠 부여 ────────────────────────────────────
# F-1: 단일 지급 상한 — int 오버플로·실수 입력 방지 (gold는 BIGINT라 한참 아래 여유값).
_MAX_GRANT_AMOUNT = 1_000_000_000_000  # 1조 량 = 100만 정


@router.post("/grant-gold")
async def grant_gold(
    request: Request,
    target_user_id: str = Form(...),
    amount: int = Form(...),
):
    """지정한 유저 계정의 users.gold에 자금 지급 (량 단위)."""
    try:
        admin = _guard(request)
    except HTTPException as e:
        if e.status_code == 302:
            return RedirectResponse(e.headers["Location"], status_code=302)
        raise
    payload = {"target_user_id": target_user_id, "amount": amount}
    if not (1 <= amount <= _MAX_GRANT_AMOUNT):
        audit(admin["id"], "/admin/grant-gold", payload, "failed: invalid amount")
        return RedirectResponse("/admin", status_code=302)
    rows = db_select("users", id=target_user_id)
    if not rows:
        audit(admin["id"], "/admin/grant-gold", payload, "failed: user not found")
        return RedirectResponse("/admin", status_code=302)
    target = rows[0]
    new_total = adjust_gold(target["id"], amount)  # A-1: 원자 입금
    audit(
        admin["id"],
        "/admin/grant-gold",
        {**payload, "target_username": target.get("username"), "new_total": new_total},
        "success",
    )
    return RedirectResponse("/admin", status_code=302)


@router.post("/grant-gold-all")
async def grant_gold_all(request: Request, amount: int = Form(...)):
    """모든 유저 계정의 users.gold에 동일액 일괄 지급 (이벤트·보상용)."""
    try:
        admin = _guard(request)
    except HTTPException as e:
        if e.status_code == 302:
            return RedirectResponse(e.headers["Location"], status_code=302)
        raise
    payload = {"amount": amount}
    if not (1 <= amount <= _MAX_GRANT_AMOUNT):
        audit(admin["id"], "/admin/grant-gold-all", payload, "failed: invalid amount")
        return RedirectResponse("/admin", status_code=302)
    users = db_select("users")
    granted, failed = 0, 0
    for u in users:
        try:
            adjust_gold(u["id"], amount)  # A-1: 원자 입금
            granted += 1
        except Exception:
            failed += 1  # F-1: 한 유저 실패가 전체 루프를 막지 않게 개별 격리
    audit(
        admin["id"],
        "/admin/grant-gold-all",
        {**payload, "user_count": granted, "failed": failed},
        "success" if not failed else "partial",
    )
    return RedirectResponse("/admin", status_code=302)


@router.post("/set-proficiency")
async def set_proficiency(
    request: Request,
    character_id: str = Form(...),
    material: str = Form(...),
    value: int = Form(...),
):
    try:
        admin = _guard(request)
    except HTTPException as e:
        if e.status_code == 302:
            return RedirectResponse(e.headers["Location"], status_code=302)
        raise
    payload = {"character_id": character_id, "material": material, "value": value}
    if not _own_character(admin["id"], character_id) or material not in MATERIALS:
        audit(admin["id"], "/admin/set-proficiency", payload, "failed: invalid target")
        return RedirectResponse("/admin", status_code=302)
    value = max(0, min(95, value))
    existing = db_select("material_proficiency", character_id=character_id, material_type=material)
    if existing:
        db_update(
            "material_proficiency",
            {"value": value},
            character_id=character_id,
            material_type=material,
        )
    else:
        db_insert(
            "material_proficiency",
            {
                "character_id": character_id,
                "material_type": material,
                "value": value,
            },
        )
    audit(admin["id"], "/admin/set-proficiency", {**payload, "value": value}, "success")
    return RedirectResponse("/admin", status_code=302)


@router.post("/set-skill")
async def set_skill(
    request: Request,
    character_id: str = Form(...),
    skill_name: str = Form(...),
    value: int = Form(...),
):
    try:
        admin = _guard(request)
    except HTTPException as e:
        if e.status_code == 302:
            return RedirectResponse(e.headers["Location"], status_code=302)
        raise
    payload = {"character_id": character_id, "skill_name": skill_name, "value": value}
    if not _own_character(admin["id"], character_id) or skill_name not in SKILL_DEFINITIONS:
        audit(admin["id"], "/admin/set-skill", payload, "failed: invalid target")
        return RedirectResponse("/admin", status_code=302)
    value = max(0, min(95, value))
    existing = db_select("character_skills", character_id=character_id, skill_name=skill_name)
    if existing:
        db_update(
            "character_skills", {"value": value}, character_id=character_id, skill_name=skill_name
        )
    else:
        db_insert(
            "character_skills",
            {
                "character_id": character_id,
                "skill_name": skill_name,
                "value": value,
            },
        )
    audit(admin["id"], "/admin/set-skill", {**payload, "value": value}, "success")
    return RedirectResponse("/admin", status_code=302)


# ── 3섹션: 초기화 ─────────────────────────────────────────
@router.post("/reset-items")
async def reset_items(request: Request, character_id: str = Form(...)):
    try:
        admin = _guard(request)
    except HTTPException as e:
        if e.status_code == 302:
            return RedirectResponse(e.headers["Location"], status_code=302)
        raise
    payload = {"character_id": character_id}
    if not _own_character(admin["id"], character_id):
        audit(admin["id"], "/admin/reset-items", payload, "failed: not owner")
        return RedirectResponse("/admin", status_code=302)
    # P5 창고 공유: 창고 아이템은 owner_id=user_id(=admin["id"]) · location='warehouse'.
    # character_id로 지우면 캐릭터 인벤토리만 지워져 창고(주괴·완성품)가 안 비워짐 → user 창고를 비운다.
    db_delete("items", owner_id=admin["id"], location="warehouse")
    audit(admin["id"], "/admin/reset-items", payload, "success")
    return RedirectResponse("/admin", status_code=302)


@router.post("/reset-skills")
async def reset_skills(request: Request, character_id: str = Form(...)):
    try:
        admin = _guard(request)
    except HTTPException as e:
        if e.status_code == 302:
            return RedirectResponse(e.headers["Location"], status_code=302)
        raise
    payload = {"character_id": character_id}
    if not _own_character(admin["id"], character_id):
        audit(admin["id"], "/admin/reset-skills", payload, "failed: not owner")
        return RedirectResponse("/admin", status_code=302)
    db_delete("character_skills", character_id=character_id)
    for skill_name, initial_value in SKILL_DEFINITIONS.items():
        db_insert(
            "character_skills",
            {
                "character_id": character_id,
                "skill_name": skill_name,
                "value": initial_value,
            },
        )
    audit(admin["id"], "/admin/reset-skills", payload, "success")
    return RedirectResponse("/admin", status_code=302)


@router.post("/reset-proficiency")
async def reset_proficiency(request: Request, character_id: str = Form(...)):
    try:
        admin = _guard(request)
    except HTTPException as e:
        if e.status_code == 302:
            return RedirectResponse(e.headers["Location"], status_code=302)
        raise
    payload = {"character_id": character_id}
    if not _own_character(admin["id"], character_id):
        audit(admin["id"], "/admin/reset-proficiency", payload, "failed: not owner")
        return RedirectResponse("/admin", status_code=302)
    db_delete("material_proficiency", character_id=character_id)
    for mat_code, mat_info in MATERIALS.items():
        if mat_info["initial"] > 0:
            db_insert(
                "material_proficiency",
                {
                    "character_id": character_id,
                    "material_type": mat_code,
                    "value": mat_info["initial"],
                },
            )
    audit(admin["id"], "/admin/reset-proficiency", payload, "success")
    return RedirectResponse("/admin", status_code=302)


@router.post("/reset-mailbox")
async def reset_mailbox(request: Request, character_id: str = Form(...)):
    try:
        admin = _guard(request)
    except HTTPException as e:
        if e.status_code == 302:
            return RedirectResponse(e.headers["Location"], status_code=302)
        raise
    payload = {"character_id": character_id}
    if not _own_character(admin["id"], character_id):
        audit(admin["id"], "/admin/reset-mailbox", payload, "failed: not owner")
        return RedirectResponse("/admin", status_code=302)
    db_delete("mailbox", character_id=character_id)
    audit(admin["id"], "/admin/reset-mailbox", payload, "success")
    return RedirectResponse("/admin", status_code=302)
