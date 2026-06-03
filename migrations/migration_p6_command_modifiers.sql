-- ============================================================
-- P6 통솔 재굴림 시스템 마이그레이션 (2026-05-28)
--   - 단일 출처: websimulgamewiki/.../통솔_재굴림_시스템.md
--   - 사용자 결정 (2026-05-28, S2-B 진입 결정 9건):
--       * 묶음 단위 = (actor_id, command_type) 풀 — 명령서당 X
--       * 통솔 d100 = 명령서 발주마다 (모델 A — 시뮬 95 도달 평균 311일)
--       * 풀 토큰 = max 룰 (대성공 ≥ 1번이면 2, 극단 ≥ 1번이면 1)
--       * 풀 페널티 = 한 번이라도 대실패면 -3, 한 번 박히면 끝까지 유지
--       * 재굴림 = min(roll1, roll2) — 더 좋은 결과 채택
--       * 발주 시 같은 묶음 모든 pending 명령서 row를 풀 값으로 update
--
-- 실행 방법: Supabase 대시보드 SQL Editor에서 통째로 실행.
-- 안전망: ADD COLUMN IF NOT EXISTS — 부분 재실행 OK.
-- ============================================================

-- ── 1. commands 컬럼 추가 ──
ALTER TABLE commands ADD COLUMN IF NOT EXISTS rerolls_remaining INTEGER NOT NULL DEFAULT 0;
ALTER TABLE commands ADD COLUMN IF NOT EXISTS penalty_modifier  INTEGER NOT NULL DEFAULT 0;

-- ── 2. 기존 pending row 모두 0으로 명시 (안전망, 이미 DEFAULT 0이라 사실상 no-op) ──
UPDATE commands SET rerolls_remaining = 0 WHERE rerolls_remaining IS NULL;
UPDATE commands SET penalty_modifier  = 0 WHERE penalty_modifier  IS NULL;

-- ============================================================
-- 검증 쿼리 (사용자가 SQL Editor에서 직접 실행)
-- ============================================================
-- 1) 컬럼 추가 확인
-- SELECT column_name, data_type, column_default
--   FROM information_schema.columns
--   WHERE table_name = 'commands'
--     AND column_name IN ('rerolls_remaining', 'penalty_modifier')
--   ORDER BY column_name;
--   (2 rows, data_type=integer, default=0 기대)
--
-- 2) 기존 row 모두 0 확인
-- SELECT
--   MAX(rerolls_remaining) AS max_rerolls,
--   MIN(rerolls_remaining) AS min_rerolls,
--   MAX(penalty_modifier)  AS max_penalty,
--   MIN(penalty_modifier)  AS min_penalty
-- FROM commands;
--   (모두 0/0 기대)
--
-- 3) NULL 없음 확인
-- SELECT COUNT(*) FROM commands
--   WHERE rerolls_remaining IS NULL OR penalty_modifier IS NULL;
--   (0 기대)
