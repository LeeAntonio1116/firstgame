-- ============================================================
-- P6 경험치 성장 시스템 마이그레이션 (2026-05-28)
--   - 단일 출처: websimulgamewiki/.../캐릭터_스탯_성장.md
--   - 사용자 결정 (2026-05-28):
--       * 모든 성장은 d100 "실패" 판정에서만 트리거
--       * 5스탯 트리거 매핑 확정 (무력=단조 forging+무력 d100, 지략=열처리 heat_treat+지략 d100,
--         통솔=NPC 명령 발주 d100, 건강=부상 안전망 실패, 운=안전망 통과 성공)
--       * 통솔 재굴림·-3 페널티 시스템은 S2-B (별도 마이그 또는 commands/npcs 컬럼 추가)
--
-- 실행 방법: Supabase 대시보드 SQL Editor에서 통째로 실행.
-- 안전망: IF EXISTS / IF NOT EXISTS / ON CONFLICT DO NOTHING — 부분 재실행 OK.
-- ============================================================

-- ── 1. character_stat_exp 신규 ──
CREATE TABLE IF NOT EXISTS character_stat_exp (
    character_id UUID    NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    stat_name    TEXT    NOT NULL,  -- strength/intelligence/charisma/leadership/health/luck/dexterity
    exp          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (character_id, stat_name)
);
ALTER TABLE character_stat_exp DISABLE ROW LEVEL SECURITY;

-- ── 2. npc_stat_exp 신규 (FK 제거 — P5 패턴 통일) ──
CREATE TABLE IF NOT EXISTS npc_stat_exp (
    npc_id    UUID    NOT NULL,
    stat_name TEXT    NOT NULL,
    exp       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (npc_id, stat_name)
);
ALTER TABLE npc_stat_exp DISABLE ROW LEVEL SECURITY;

-- ── 3. 기존 분리 테이블 4개에 exp 컬럼 추가 ──
ALTER TABLE character_skills        ADD COLUMN IF NOT EXISTS exp INTEGER NOT NULL DEFAULT 0;
ALTER TABLE npc_skills              ADD COLUMN IF NOT EXISTS exp INTEGER NOT NULL DEFAULT 0;
ALTER TABLE material_proficiency    ADD COLUMN IF NOT EXISTS exp INTEGER NOT NULL DEFAULT 0;
ALTER TABLE npc_material_proficiency ADD COLUMN IF NOT EXISTS exp INTEGER NOT NULL DEFAULT 0;

-- ── 4. 기존 캐릭터 × 7스탯 시드 (exp=0) ──
INSERT INTO character_stat_exp (character_id, stat_name, exp)
SELECT c.id, s.stat_name, 0
FROM characters c
CROSS JOIN (VALUES
    ('strength'), ('intelligence'), ('charisma'), ('leadership'),
    ('health'), ('luck'), ('dexterity')
) AS s(stat_name)
ON CONFLICT (character_id, stat_name) DO NOTHING;

-- ── 5. 기존 NPC × 7스탯 시드 (exp=0) ──
INSERT INTO npc_stat_exp (npc_id, stat_name, exp)
SELECT n.id, s.stat_name, 0
FROM npcs n
CROSS JOIN (VALUES
    ('strength'), ('intelligence'), ('charisma'), ('leadership'),
    ('health'), ('luck'), ('dexterity')
) AS s(stat_name)
ON CONFLICT (npc_id, stat_name) DO NOTHING;

-- ============================================================
-- 검증 쿼리 (사용자가 SQL Editor에서 직접 실행)
-- ============================================================
-- 1) 신규 테이블 생성 확인
-- SELECT tablename FROM pg_tables WHERE schemaname='public'
--   AND tablename IN ('character_stat_exp', 'npc_stat_exp');
--   (2 rows 기대)
--
-- 2) 4테이블 exp 컬럼 추가 확인
-- SELECT table_name, column_name, data_type, column_default
--   FROM information_schema.columns
--   WHERE table_name IN ('character_skills','npc_skills',
--                        'material_proficiency','npc_material_proficiency')
--     AND column_name = 'exp'
--   ORDER BY table_name;
--   (4 rows, data_type=integer, default=0 기대)
--
-- 3) 시드 카운트 확인 — 기존 캐릭터 수 × 7 = character_stat_exp row 수
-- SELECT
--   (SELECT COUNT(*) FROM characters) AS char_count,
--   (SELECT COUNT(*) FROM character_stat_exp) AS char_stat_exp_count,
--   (SELECT COUNT(*) FROM npcs) AS npc_count,
--   (SELECT COUNT(*) FROM npc_stat_exp) AS npc_stat_exp_count;
--   (char_stat_exp_count = char_count × 7, npc_stat_exp_count = npc_count × 7 기대)
--
-- 4) 모든 exp=0 확인
-- SELECT MAX(exp), MIN(exp) FROM character_stat_exp;
-- SELECT MAX(exp), MIN(exp) FROM npc_stat_exp;
-- SELECT MAX(exp), MIN(exp) FROM character_skills;
-- SELECT MAX(exp), MIN(exp) FROM npc_skills;
-- SELECT MAX(exp), MIN(exp) FROM material_proficiency;
-- SELECT MAX(exp), MIN(exp) FROM npc_material_proficiency;
--   (모두 0/0 기대)
--
-- 5) RLS 비활성화 확인
-- SELECT relname, relrowsecurity FROM pg_class
--   WHERE relname IN ('character_stat_exp', 'npc_stat_exp');
--   (둘 다 relrowsecurity=false 기대)
