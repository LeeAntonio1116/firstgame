"""P4-2 SMTP 헬퍼.

Gmail SMTP(STARTTLS 587)를 기본으로 사용한다. 발송 실패 시 False 반환 + 로그만 남기고
예외는 호출자로 전파하지 않는다 (OTP·자정 이메일이 전체 서버를 막지 않도록).
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from config import SMTP_FROM_NAME, SMTP_HOST, SMTP_PASS, SMTP_PORT, SMTP_USER
from engine.admin_audit import mask_email

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> bool:
    """일반 텍스트 이메일 발송. 성공 True, 실패 False."""
    if not (SMTP_USER and SMTP_PASS):
        logger.warning(
            "SMTP 미설정 — 이메일 발송 스킵 (to=%s, subject=%s)", mask_email(to), subject
        )
        return False
    if not to:
        logger.warning("수신자 비어있음 — 발송 스킵 (subject=%s)", subject)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((SMTP_FROM_NAME, SMTP_USER))
    msg["To"] = to
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception as e:
        logger.error("이메일 발송 실패 (to=%s): %s", mask_email(to), e)
        return False


def send_otp(to: str, code: str) -> bool:
    subject = "[삼국지 길드] 관리자 인증 코드"
    body = (
        f"인증 코드: {code}\n"
        f"유효 시간: 5분\n\n"
        f"이 코드를 타인과 공유하지 마세요. 본인이 요청하지 않았다면 무시하세요."
    )
    return send_email(to, subject, body)


def send_admin_log(to: str, entries: list[dict]) -> bool:
    """24시간치 admin 작업 로그를 한 통으로 발송."""
    subject = f"[삼국지 길드] 일일 운영 로그 ({len(entries)}건)"
    if not entries:
        body = "지난 24시간 동안 관리자 작업이 없었습니다."
    else:
        lines = ["지난 24시간 관리자 작업 기록:\n"]
        for e in entries:
            lines.append(
                f"[{e.get('created_at', '?')}] {e.get('endpoint', '?')} ({e.get('result', '?')})"
            )
            payload = e.get("payload")
            if payload:
                lines.append(f"  payload: {payload}")
        body = "\n".join(lines)
    return send_email(to, subject, body)
