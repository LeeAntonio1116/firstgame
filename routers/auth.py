from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta, timezone
from jinja2 import StrictUndefined
import bcrypt
import jwt

from database import db_select, db_insert, db_delete
from config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_DAYS, INVITE_CODE
from engine.materials import MATERIALS
from engine.items import ITEM_TYPE_LABELS

router = APIRouter()
templates = Jinja2Templates(directory="templates", undefined=StrictUndefined)


def create_token(user_id: str, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": user_id, "username": username, "exp": expire},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def get_current_user(request: Request) -> dict | None:
    token = request.cookies.get("token")
    if not token:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# ── 로그인 ──────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    rows = db_select("users", username=username)
    if not rows:
        return templates.TemplateResponse("login.html", {"request": request, "error": "아이디 또는 비밀번호가 틀렸습니다."})

    user = rows[0]
    if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return templates.TemplateResponse("login.html", {"request": request, "error": "아이디 또는 비밀번호가 틀렸습니다."})

    token = create_token(user["id"], user["username"])
    response = RedirectResponse("/dashboard", status_code=302)
    response.set_cookie("token", token, httponly=True, max_age=JWT_EXPIRE_DAYS * 86400)
    return response


# ── 회원가입 ─────────────────────────────────────────────
@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("register.html", {"request": request, "error": None})


@router.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    invite_code: str = Form(...),
):
    if invite_code != INVITE_CODE:
        return templates.TemplateResponse("register.html", {"request": request, "error": "초대코드가 올바르지 않습니다."})
    if password != password_confirm:
        return templates.TemplateResponse("register.html", {"request": request, "error": "비밀번호가 일치하지 않습니다."})
    if len(username) < 2 or len(username) > 20:
        return templates.TemplateResponse("register.html", {"request": request, "error": "아이디는 2~20자 사이여야 합니다."})
    if len(password) < 6:
        return templates.TemplateResponse("register.html", {"request": request, "error": "비밀번호는 6자 이상이어야 합니다."})

    if db_select("users", username=username):
        return templates.TemplateResponse("register.html", {"request": request, "error": "이미 사용 중인 아이디입니다."})

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    db_insert("users", {"username": username, "password_hash": hashed})
    return RedirectResponse("/login?registered=1", status_code=302)


# ── 대시보드 ─────────────────────────────────────────────
def _build_dashboard_context(request: Request, user: dict, delete_error: str | None = None) -> dict:
    characters = db_select("characters", user_id=user["sub"])
    char = characters[0] if characters else None
    if char:
        char.setdefault("is_injured", False)
        char.setdefault("is_serious_injured", False)
        char.setdefault("serious_injury_remaining", 0)
        all_commands = db_select("commands", character_id=char["id"])
        pending_commands = [c for c in all_commands if c["status"] == "pending"]
        mailbox = sorted(db_select("mailbox", character_id=char["id"]), key=lambda x: x["created_at"], reverse=True)
        mat_prof_rows = db_select("material_proficiency", character_id=char["id"])
        mat_proficiency = {row["material_type"]: row["value"] for row in mat_prof_rows}
        skill_rows = db_select("character_skills", character_id=char["id"])
        character_skills = {row["skill_name"]: row["value"] for row in skill_rows}
        items = sorted(
            db_select("items", owner_id=char["id"]),
            key=lambda x: x.get("created_at", ""),
            reverse=True,
        )
    else:
        pending_commands, mailbox, mat_proficiency, character_skills, items = [], [], {}, {}, []
    material_labels = {code: info["name"] for code, info in MATERIALS.items()}
    return {
        "request": request,
        "username": user["username"],
        "character": char,
        "pending_commands": pending_commands,
        "mailbox": mailbox,
        "mat_proficiency": mat_proficiency,
        "character_skills": character_skills,
        "items": items,
        "material_labels": material_labels,
        "item_type_labels": ITEM_TYPE_LABELS,
        "delete_error": delete_error,
    }


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    characters = db_select("characters", user_id=user["sub"])
    if not characters:
        return RedirectResponse("/character/create", status_code=302)
    return templates.TemplateResponse("dashboard.html", _build_dashboard_context(request, user))


# ── 로그아웃 ─────────────────────────────────────────────
@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("token")
    return response


# ── 회원탈퇴 ─────────────────────────────────────────────
@router.post("/delete-account")
async def delete_account(request: Request, password: str = Form(...)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    rows = db_select("users", id=user["sub"])
    if not rows:
        return RedirectResponse("/login", status_code=302)

    if not bcrypt.checkpw(password.encode(), rows[0]["password_hash"].encode()):
        return templates.TemplateResponse("dashboard.html",
            _build_dashboard_context(request, user, delete_error="비밀번호가 틀렸습니다."))

    db_delete("users", id=user["sub"])
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("token")
    return response
