from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from engine.batch import run_batch
from routers.auth import get_current_user

router = APIRouter(prefix="/admin")


@router.post("/run-batch")
async def trigger_batch(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login", status_code=302)
    run_batch()
    return RedirectResponse("/dashboard", status_code=302)
