import random

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import db_insert, db_select
from engine.materials import MATERIALS, SKILL_DEFINITIONS
from routers.auth import get_current_user

router = APIRouter(prefix="/character")
templates = Jinja2Templates(directory="templates")

# 6대 스탯 (2026-05-31: 통솔 제거 → 인재관리 스킬로 이관, [[인재관리_스킬_전환]])
STAT_FIELDS = [
    ("strength", "무력"),
    ("intelligence", "지략"),
    ("charisma", "매력"),
    ("health", "건강"),
    ("luck", "운"),
    ("dexterity", "민첩"),
]
# 6스탯 합계 상한. _sim_6stat.py: CAP=355 → 기각률 9.88% ≈ 7스탯(410)의 10.22%.
STAT_TOTAL_CAP = 355


def _roll_stat() -> int:
    return min(sum(random.randint(1, 6) for _ in range(3)) * 5, 75)


def _roll_all() -> dict:
    while True:
        stats = {key: _roll_stat() for key, _ in STAT_FIELDS}
        if sum(stats.values()) <= STAT_TOTAL_CAP:
            return stats


@router.get("/create", response_class=HTMLResponse)
async def create_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if db_select("characters", user_id=user["sub"]):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(
        request,
        "character_create.html",
        {
            "request": request,
            "stats": _roll_all(),
            "stat_fields": STAT_FIELDS,
            "error": None,
        },
    )


@router.post("/confirm")
async def confirm(
    request: Request,
    name: str = Form(...),
    strength: int = Form(...),
    intelligence: int = Form(...),
    charisma: int = Form(...),
    health: int = Form(...),
    luck: int = Form(...),
    dexterity: int = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if db_select("characters", user_id=user["sub"]):
        return RedirectResponse("/dashboard", status_code=302)

    name = name.strip()
    stats = {
        "strength": strength,
        "intelligence": intelligence,
        "charisma": charisma,
        "health": health,
        "luck": luck,
        "dexterity": dexterity,
    }

    if not (1 <= len(name) <= 20):
        return templates.TemplateResponse(
            request,
            "character_create.html",
            {
                "request": request,
                "stats": stats,
                "stat_fields": STAT_FIELDS,
                "error": "이름은 1~20자 사이여야 합니다.",
            },
        )

    if not all(15 <= v <= 75 for v in stats.values()):
        return RedirectResponse("/character/create", status_code=302)
    # F-3: 폼 변조로 개별 범위는 통과하나 합계가 캡(STAT_TOTAL_CAP)을 넘는 경우 거부
    if sum(stats.values()) > STAT_TOTAL_CAP:
        return RedirectResponse("/character/create", status_code=302)

    # A-5: characters.user_id UNIQUE — 위 read-check를 통과한 동시 요청 2개가 모두 INSERT하는
    # 레이스를 DB 제약으로 차단. 위반(409)이면 이미 생성된 것 → 대시보드로.
    try:
        char = db_insert(
            "characters",
            {
                "user_id": user["sub"],
                "name": name,
                **stats,
                "stamina_current": stats["health"] // 5,
            },
        )
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 409:
            return RedirectResponse("/dashboard", status_code=302)
        raise
    for mat_code, mat_info in MATERIALS.items():
        if mat_info["initial"] > 0:
            db_insert(
                "material_proficiency",
                {
                    "character_id": char["id"],
                    "material_type": mat_code,
                    "value": mat_info["initial"],
                },
            )
    for skill_name, initial_value in SKILL_DEFINITIONS.items():
        db_insert(
            "character_skills",
            {
                "character_id": char["id"],
                "skill_name": skill_name,
                "value": initial_value,
            },
        )
    return RedirectResponse("/dashboard", status_code=302)
