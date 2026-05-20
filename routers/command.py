from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from database import db_select, db_insert
from routers.auth import get_current_user

router = APIRouter(prefix="/commands")


@router.post("/submit")
async def submit_command(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    chars = db_select("characters", user_id=user["sub"])
    if not chars or not chars[0].get("has_blacksmith"):
        return RedirectResponse("/dashboard", status_code=302)

    char = chars[0]
    # 중상은 명령 제출 차단 (부상은 도박 허용)
    if char.get("is_serious_injured"):
        return RedirectResponse("/dashboard#control", status_code=302)

    db_insert("commands", {
        "character_id": char["id"],
        "command_type": "blacksmith",
        "target_material": "raw_iron",
        "input_type": "ore",
        "status": "pending",
    })
    return RedirectResponse("/dashboard#control", status_code=302)
