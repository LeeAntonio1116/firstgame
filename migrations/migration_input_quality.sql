-- ============================================================
-- 재료 품질 → 완성품 보너스: commands.input_quality 컬럼 (2026-06-01)
--   - 단일 출처: websimulgamewiki/.../제작_품질_체계.md
--   - 사용자 결정 (2026-06-01):
--       * 입력 재료 품질 등급 저장 = 신규 input_quality 컬럼 (거래용 quality와 분리)
--       * 보너스 = max(0, input_quality - 1) → 제작 total 시작값에 가산
--       * ingot/alloy_ingot 입력만 1~5 의미, ore/alloy 입력은 0 (광석 품질은 미래)
--
-- 실행 방법: Supabase 대시보드 SQL Editor에서 통째로 실행.
-- 안전망: ADD COLUMN IF NOT EXISTS — 부분 재실행 OK.
-- 기존 테이블 ALTER이므로 RLS 비활성 지침 비해당 (commands는 이미 비활성).
-- ============================================================

-- ── 1. commands 컬럼 추가 ──
-- nullable: 옛 제작·거래 명령 row는 NULL → 코드에서 (cmd.get("input_quality") or 0) = 0 → 보너스 0.
ALTER TABLE commands ADD COLUMN IF NOT EXISTS input_quality INTEGER;

-- ============================================================
-- 검증 쿼리 (사용자가 SQL Editor에서 직접 실행)
-- ============================================================
-- 1) 컬럼 추가 확인
-- SELECT column_name, data_type, is_nullable
--   FROM information_schema.columns
--   WHERE table_name = 'commands'
--     AND column_name = 'input_quality';
--   (1 row, data_type=integer, is_nullable=YES 기대)
--
-- 2) 옛 row는 NULL (보너스 0 취급) 확인
-- SELECT COUNT(*) AS null_rows FROM commands WHERE input_quality IS NULL;
--   (기존 명령 수만큼 기대 — 정상)
