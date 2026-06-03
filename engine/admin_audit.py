"""P4-2 admin 작업 감사 로그.

모든 /admin/* POST 엔드포인트가 호출 시 자동으로 admin_audit_log 행을 INSERT.
실패 시에도 result에 에러 메시지를 남긴다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from database import db_insert, db_select

logger = logging.getLogger(__name__)


def mask_email(value: str | None) -> str | None:
    """이메일을 부분 마스킹 (로그·감사 PII 보호). 'foo@bar.com' → 'f***@b***'."""
    if not value or "@" not in value:
        return value
    local, _, domain = value.partition("@")
    ml = (local[0] + "***") if local else "***"
    md = (domain[0] + "***") if domain else "***"
    return f"{ml}@{md}"


def _json_safe(payload: dict | None) -> dict | None:
    if payload is None:
        return None
    # password 등 민감 필드 마스킹
    masked = {}
    for k, v in payload.items():
        kl = k.lower()
        if kl in ("password", "password_confirm", "otp_code", "token"):
            masked[k] = "***"
        elif kl in ("to", "email") and isinstance(v, str):
            masked[k] = mask_email(v)
        else:
            masked[k] = v
    return masked


def record(admin_user_id: str | None, endpoint: str, payload: dict | None, result: str) -> None:
    """admin 작업 한 건을 기록. 실패해도 호출자에게 영향 없음."""
    try:
        safe_payload = _json_safe(payload)
        db_insert(
            "admin_audit_log",
            {
                "admin_user_id": admin_user_id,
                "endpoint": endpoint,
                "payload": safe_payload,
                "result": result,
            },
        )
    except Exception as e:
        logger.error("audit_log 기록 실패 (endpoint=%s): %s", endpoint, e)


def fetch_last_24h() -> list[dict]:
    """지난 24시간 audit_log 행을 created_at 오름차순으로 반환."""
    try:
        cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        # db_select는 eq 필터만 지원 — 전부 가져온 뒤 파이썬에서 필터
        all_rows = db_select("admin_audit_log")
        rows = [r for r in all_rows if (r.get("created_at") or "") >= cutoff]
        rows.sort(key=lambda r: r.get("created_at") or "")
        return rows
    except Exception as e:
        logger.error("audit_log 조회 실패: %s", e)
        return []
