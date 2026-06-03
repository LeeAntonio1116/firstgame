-- P4-2 admin 패널 분리
-- (1) users 권한·이메일 컬럼
-- (2) OTP 1회용 토큰 테이블
-- (3) admin 작업 감사 로그 테이블
--
-- 적용 후: .env의 ADMIN_EMAILS=... 콤마 구분 목록을 채우고 서버 재시작 시
-- main.py startup이 해당 이메일을 보유한 users 행을 is_admin=TRUE 로,
-- 그 외 모든 is_admin=TRUE 행을 FALSE 로 동기화한다 (단일 출처 부트스트랩).

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS email TEXT,
    ADD COLUMN IF NOT EXISTS gold INT NOT NULL DEFAULT 0;
-- gold 컬럼은 P4-1 시장 시스템에서 본격 사용. P4-2 admin grant-gold 디버그가
-- 미리 의존하므로 admin 마이그레이션에서 함께 추가한다.

CREATE TABLE IF NOT EXISTS admin_otp (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    otp_code TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_admin_otp_user_id ON admin_otp(user_id);
CREATE INDEX IF NOT EXISTS idx_admin_otp_expires_at ON admin_otp(expires_at);

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    endpoint TEXT NOT NULL,
    payload JSONB,
    result TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_created_at ON admin_audit_log(created_at);

ALTER TABLE admin_otp DISABLE ROW LEVEL SECURITY;
ALTER TABLE admin_audit_log DISABLE ROW LEVEL SECURITY;
