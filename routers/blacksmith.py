from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from database import db_select, db_update
from routers.auth import get_current_user

router = APIRouter(prefix="/blacksmith")


@router.post("/start")
async def start_blacksmith(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    chars = db_select("characters", user_id=user["sub"])
    if not chars:
        return RedirectResponse("/character/create", status_code=302)

    char = chars[0]
    if not char.get("has_blacksmith"):
        db_update("characters", {"has_blacksmith": True}, id=char["id"])

    return RedirectResponse("/dashboard", status_code=302)
