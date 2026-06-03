-- ============================================================
-- P5 NPC 고용 — 대실패 누적 카운트 (2026-05-24)
--   - 한 후보의 대실패 누적 → 영입금 +10% × N
--   - N >= 3 시 후보 자동 제거 (npc.py /hire에서 처리)
-- ============================================================

ALTER TABLE npc_candidates
  ADD COLUMN IF NOT EXISTS fumble_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE npc_candidates
  ADD COLUMN IF NOT EXISTS base_hire_cost INTEGER;
-- base_hire_cost: 영입금 원가 (대실패로 hire_cost가 상승해도 원가 보존).
-- 기존 row는 NULL → 코드 측에서 NULL이면 현재 hire_cost를 원가로 간주.

-- ============================================================
-- 검증 쿼리 (사용자가 SQL Editor에서 직접 실행해 확인)
-- ============================================================
-- SELECT column_name FROM information_schema.columns
--   WHERE table_name = 'npc_candidates' ORDER BY ordinal_position;
-- (fumble_count, base_hire_cost 추가됨)
