-- [S8] JWT revocation 블랙리스트
-- 로그아웃·회원탈퇴·admin 로그아웃 시 토큰의 jti를 등록 →
-- get_current_user / _verify_admin_session이 decode 후 이 테이블을 조회해 거부.
-- jti 없는 옛 토큰(이 마이그 이전 발급분)은 미차단되어 exp(최대 7일)까지 자연 만료된다.

CREATE TABLE IF NOT EXISTS jwt_blacklist (
    jti TEXT PRIMARY KEY,
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jwt_blacklist_expires_at ON jwt_blacklist (expires_at);

-- 자체 JWT 인증을 쓰므로 Supabase RLS는 비활성화 (CLAUDE.md 정책)
ALTER TABLE jwt_blacklist DISABLE ROW LEVEL SECURITY;

-- ── 검증 쿼리 ──────────────────────────────────────────────
-- 1. 테이블 생성 확인
-- SELECT count(*) AS blacklist_rows FROM jwt_blacklist;
-- 2. 컬럼 확인
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'jwt_blacklist';
-- 3. 로그아웃 후 행 확인 (앱에서 로그아웃 1회 → 1행 증가)
-- SELECT jti, expires_at, revoked_at FROM jwt_blacklist ORDER BY revoked_at DESC LIMIT 5;
-- 4. RLS 비활성 확인
-- SELECT relname, relrowsecurity FROM pg_class WHERE relname = 'jwt_blacklist';
