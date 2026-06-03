import os

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
JWT_SECRET = os.getenv("JWT_SECRET")
INVITE_CODE = os.getenv("INVITE_CODE", "")  # 미설정 시 가입 차단(fail-closed). 실제 값은 .env.
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7

# P4-2 admin
ADMIN_EMAILS = [e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip()

# SMTP (Gmail)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "삼국지 길드 운영자")

# 운영/개발 분기 — Secure 쿠키, HTTPS 검증 등에서 사용
ENV = os.getenv("ENV", "development")
IS_PROD = ENV.lower() in ("prod", "production")

# 배치 처리 시각 — KST 기준 도래 시각 목록 (콤마 구분). 기본 10:00·22:00.
# 통제실 § 능동 취소는 다음 배치까지 10분 미만 남으면 차단.
BATCH_HOURS_KST = sorted(
    {
        int(h.strip())
        for h in os.getenv("BATCH_HOURS_KST", "10,22").split(",")
        if h.strip().isdigit() and 0 <= int(h.strip()) <= 23
    }
) or [10, 22]
# 능동 취소 컷오프 (초)
CANCEL_CUTOFF_SECONDS = int(os.getenv("CANCEL_CUTOFF_SECONDS", "600"))

# [S10 배포] Cloud Scheduler 전용 공유 시크릿 (미설정 시 /internal/* 거부 — fail-closed)
CRON_SECRET = os.getenv("CRON_SECRET", "")
