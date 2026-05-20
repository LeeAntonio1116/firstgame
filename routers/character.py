import random
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import db_select, db_insert
from routers.auth import get_current_user
from engine.materials import MATERIALS, SKILL_DEFINITIONS

router = APIRouter(prefix="/character")
templates = Jinja2Templates(directory="templates")

STAT_FIELDS = [
    ("strength",     "무력"),
    ("intelligence", "지략"),
    ("charisma",     "매력"),
    ("leadership",   "통솔"),
    ("health",       "건강"),
    ("luck",         "운"),
]


def _roll_stat() -> int:
    return min(sum(random.randint(1, 6) for _ in range(3)) * 5, 75)


def _roll_all() -> dict:
    while True:
        stats = {key: _roll_stat() for key, _ in STAT_FIELDS}
        if sum(stats.values()) <= 350:
            return stats


@router.get("/create", response_class=HTMLResponse)
async def create_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if db_select("characters", user_id=user["sub"]):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("character_create.html", {
        "request": request,
        "stats": _roll_all(),
        "stat_fields": STAT_FIELDS,
        "error": None,
    })


@router.post("/confirm")
async def confirm(
    request: Request,
    name: str = Form(...),
    strength: int = Form(...),
    intelligence: int = Form(...),
    charisma: int = Form(...),
    leadership: int = Form(...),
    health: int = Form(...),
    luck: int = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if db_select("characters", user_id=user["sub"]):
        return RedirectResponse("/dashboard", status_code=302)

    name = name.strip()
    stats = {
        "strength": strength, "intelligence": intelligence,
        "charisma": charisma, "leadership": leadership,
        "health": health, "luck": luck,
    }

    if not (1 <= len(name) <= 20):
        return templates.TemplateResponse("character_create.html", {
            "request": request,
            "stats": stats,
            "stat_fields": STAT_FIELDS,
            "error": "이름은 1~20자 사이여야 합니다.",
        })

    if not all(15 <= v <= 75 for v in stats.values()):
        return RedirectResponse("/character/create", status_code=302)

    char = db_insert("characters", {"user_id": user["sub"], "name": name, **stats})
    for mat_code, mat_info in MATERIALS.items():
        if mat_info["initial"] > 0:
            db_insert("material_proficiency", {
                "character_id": char["id"],
                "material_type": mat_code,
                "value": mat_info["initial"],
            })
    for skill_name, initial_value in SKILL_DEFINITIONS.items():
        db_insert("character_skills", {
            "character_id": char["id"],
            "skill_name": skill_name,
            "value": initial_value,
        })
    return RedirectResponse("/dashboard", status_code=302)
