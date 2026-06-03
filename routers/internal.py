"""[S10 배포] Cloud Scheduler 전용 내부 엔드포인트.

공개 앱(--allow-unauthenticated)이라 OIDC 대신 공유 시크릿 헤더로 보호한다.
- X-Cron-Secret 헤더를 CRON_SECRET(env)과 상수시간 비교. 불일치/누락 시 401.
- CSRF 전역 의존성은 /internal/* 경로를 예외 처리(routers/csrf.py) — 폼이 아닌 헤더 인증.
- Cloud Run scale-to-zero라 main.py의 APScheduler가 못 도는 자정 작업을
  Cloud Scheduler가 여기로 호출해 대체한다(로컬 dev는 APScheduler가 그대로 수행).
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Header, HTTPException

from config import CRON_SECRET
from engine.batch import run_batch
from routers.auth import purge_expired_blacklist

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal")


def _verify_cron(provided: str | None) -> None:
    """공유 시크릿 검증. CRON_SECRET 미설정이면 항상 거부(fail-closed)."""
    if not CRON_SECRET:
        logger.error("CRON_SECRET 미설정 — /internal 거부")
        raise HTTPException(status_code=503, detail="cron not configured")
    if not provided or not secrets.compare_digest(provided, CRON_SECRET):
        raise HTTPException(status_code=401, detail="unauthorized")


@router.post("/run-batch")
async def cron_run_batch(x_cron_secret: str | None = Header(default=None)):
    """Cloud Scheduler 하루 2회(10·22 KST) 게임 배치 트리거. (기존 /admin/run-batch는 OTP 수동용 유지)"""
    _verify_cron(x_cron_secret)
    run_batch()
    logger.info("[cron] run_batch 완료")
    return {"ok": True, "job": "run-batch"}


@router.post("/maintenance")
async def cron_maintenance(x_cron_secret: str | None = Header(default=None)):
    """Cloud Scheduler 자정 유지보수 — admin 로그 이메일 + jwt_blacklist 정리."""
    _verify_cron(x_cron_secret)
    from main import _send_daily_admin_log  # 지연 import — main↔internal 순환 회피

    _send_daily_admin_log()
    purged = purge_expired_blacklist()
    logger.info("[cron] maintenance 완료 (purged=%d)", purged)
    return {"ok": True, "job": "maintenance", "purged": purged}
