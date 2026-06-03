-- ============================================================
-- P5 NPC 고용 시스템 마이그레이션 (2026-05-24)
--   - 단일 출처: websimulgamewiki/.../NPC_장인_시스템.md
--   - 사용자 결정 (2026-05-24):
--       매력 판정 d100+charisma / 후보 풀 배치마다 3명 갱신 /
--       영입금+수수료 5구간 (≤300/350/450/550/+) /
--       NPC 초기값 10~65 (캐릭터 한 단계 약함)
--
-- 실행 방법: Supabase 대시보드 SQL Editor에서 통째로 실행.
-- 안전망: IF EXISTS / IF NOT EXISTS 사용 — 부분 재실행 OK.
-- ============================================================

-- ── 1. commands.character_id FK 제거 (npcs.id도 받기 위함) ──
ALTER TABLE commands DROP CONSTRAINT IF EXISTS commands_character_id_fkey;
-- 컬럼명·NOT NULL은 유지. 코드 측 검증 + 정리(cancel/cascade)로 일관성 유지.

-- ── 2. mailbox.character_id FK 제거 ──
ALTER TABLE mailbox DROP CONSTRAINT IF EXISTS mailbox_character_id_fkey;

-- ── 3. items.owner_id FK 제거 (NPC 인벤·창고 수용) ──
ALTER TABLE items DROP CONSTRAINT IF EXISTS items_owner_id_fkey;

-- ── 4. npcs 테이블 컬럼 추가 (캐릭터와 통일) ──
ALTER TABLE npcs ADD COLUMN IF NOT EXISTS is_serious_injured       BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE npcs ADD COLUMN IF NOT EXISTS serious_injury_remaining INTEGER NOT NULL DEFAULT 0;
ALTER TABLE npcs ADD COLUMN IF NOT EXISTS stamina_current          INTEGER NOT NULL DEFAULT 0;
ALTER TABLE npcs ADD COLUMN IF NOT EXISTS hire_cost                INTEGER NOT NULL DEFAULT 0;
ALTER TABLE npcs ADD COLUMN IF NOT EXISTS fee_per_batch            INTEGER NOT NULL DEFAULT 0;

-- ── 5. npcs 옛 컬럼 폐기 (npc_skills · npc_material_proficiency로 분리) ──
-- 데이터 보존 필요 시 수동 백업 권장. 본 마이그레이션은 옛 P3 잔존 컬럼만 폐기.
ALTER TABLE npcs DROP COLUMN IF EXISTS skill_appraisal;
ALTER TABLE npcs DROP COLUMN IF EXISTS skill_smelting;
ALTER TABLE npcs DROP COLUMN IF EXISTS skill_forging;
ALTER TABLE npcs DROP COLUMN IF EXISTS skill_heat_treat;
ALTER TABLE npcs DROP COLUMN IF EXISTS skill_finishing;
ALTER TABLE npcs DROP COLUMN IF EXISTS proficiency_iron;
ALTER TABLE npcs DROP COLUMN IF EXISTS proficiency_copper;
ALTER TABLE npcs DROP COLUMN IF EXISTS proficiency_steel;
ALTER TABLE npcs DROP COLUMN IF EXISTS proficiency_jade;
ALTER TABLE npcs DROP COLUMN IF EXISTS proficiency_special;

-- ── 6. npc_skills 신규 (character_skills와 동일 구조) ──
CREATE TABLE IF NOT EXISTS npc_skills (
    npc_id     UUID    NOT NULL REFERENCES npcs(id) ON DELETE CASCADE,
    skill_name TEXT    NOT NULL,
    value      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (npc_id, skill_name)
);
ALTER TABLE npc_skills DISABLE ROW LEVEL SECURITY;

-- ── 7. npc_material_proficiency 신규 (material_proficiency와 동일 구조) ──
CREATE TABLE IF NOT EXISTS npc_material_proficiency (
    npc_id        UUID    NOT NULL REFERENCES npcs(id) ON DELETE CASCADE,
    material_type TEXT    NOT NULL,
    value         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (npc_id, material_type)
);
ALTER TABLE npc_material_proficiency DISABLE ROW LEVEL SECURITY;

-- ── 8. npc_candidates 신규 (배치마다 갱신되는 고용 후보 풀) ──
CREATE TABLE IF NOT EXISTS npc_candidates (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL,
    stats       JSONB       NOT NULL,    -- {strength, intelligence, charisma, leadership, health, luck, dexterity}
    skills      JSONB       NOT NULL,    -- {smelting, forging, heat_treat, finishing, appraisal}
    proficiency JSONB       NOT NULL,    -- {raw_iron, chalcopyrite, ...} — 0인 항목 포함
    stat_total  INTEGER     NOT NULL,    -- 비용 구간 계산용 (7스탯 합)
    hire_cost   INTEGER     NOT NULL,    -- 표시·차감 캐시값
    fee         INTEGER     NOT NULL,    -- 수수료 캐시값 (배치당)
    batch_id    UUID        REFERENCES batches(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_npc_candidates_user_id ON npc_candidates(user_id);
ALTER TABLE npc_candidates DISABLE ROW LEVEL SECURITY;

-- ============================================================
-- 검증 쿼리 (사용자가 SQL Editor에서 직접 실행해 확인)
-- ============================================================
-- 1) FK 제거 확인
-- SELECT conname FROM pg_constraint
--   WHERE conrelid IN ('commands'::regclass, 'mailbox'::regclass, 'items'::regclass)
--   AND contype = 'f';
-- (commands_character_id_fkey, mailbox_character_id_fkey, items_owner_id_fkey 결과에 없어야 함)
--
-- 2) npcs 컬럼 추가·폐기 확인
-- SELECT column_name FROM information_schema.columns WHERE table_name = 'npcs' ORDER BY ordinal_position;
-- (is_serious_injured, serious_injury_remaining, stamina_current, hire_cost, fee_per_batch 추가됨;
--  옛 skill_*, proficiency_* 컬럼은 사라짐)
--
-- 3) 신규 테이블 확인
-- SELECT tablename FROM pg_tables WHERE schemaname='public'
--   AND tablename IN ('npc_skills','npc_material_proficiency','npc_candidates');
