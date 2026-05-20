-- ============================================================
-- 마이그레이션: 대장간 기술 / 소재 숙련도 / 부상 상태 추가
-- 실행 위치: Supabase 대시보드 > SQL Editor
-- ============================================================

-- 1. characters 테이블에 컬럼 추가
ALTER TABLE characters
  ADD COLUMN IF NOT EXISTS is_injured          boolean  NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS skill_appraisal     integer  NOT NULL DEFAULT 20,
  ADD COLUMN IF NOT EXISTS skill_smelting      integer  NOT NULL DEFAULT 15,
  ADD COLUMN IF NOT EXISTS skill_forging       integer  NOT NULL DEFAULT 20,
  ADD COLUMN IF NOT EXISTS skill_heat_treat    integer  NOT NULL DEFAULT 15,
  ADD COLUMN IF NOT EXISTS skill_finishing     integer  NOT NULL DEFAULT 10,
  ADD COLUMN IF NOT EXISTS proficiency_iron    integer  NOT NULL DEFAULT 30,
  ADD COLUMN IF NOT EXISTS proficiency_copper  integer  NOT NULL DEFAULT 20,
  ADD COLUMN IF NOT EXISTS proficiency_steel   integer  NOT NULL DEFAULT 5,
  ADD COLUMN IF NOT EXISTS proficiency_jade    integer  NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS proficiency_special integer  NOT NULL DEFAULT 0;

-- 2. npcs 테이블 신규 생성 (characters와 동일 구조, 처리 엔진 단일화 목적)
--    NPC 기술 초기값은 플레이어보다 낮게 설정 (추후 조정 가능)
CREATE TABLE IF NOT EXISTS npcs (
  id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id            uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name                text        NOT NULL,
  npc_type            text        NOT NULL DEFAULT '장인',
  strength            integer     NOT NULL DEFAULT 30,
  intelligence        integer     NOT NULL DEFAULT 30,
  charisma            integer     NOT NULL DEFAULT 30,
  leadership          integer     NOT NULL DEFAULT 30,
  health              integer     NOT NULL DEFAULT 30,
  luck                integer     NOT NULL DEFAULT 30,
  is_injured          boolean     NOT NULL DEFAULT false,
  skill_appraisal     integer     NOT NULL DEFAULT 10,
  skill_smelting      integer     NOT NULL DEFAULT 8,
  skill_forging       integer     NOT NULL DEFAULT 10,
  skill_heat_treat    integer     NOT NULL DEFAULT 8,
  skill_finishing     integer     NOT NULL DEFAULT 5,
  proficiency_iron    integer     NOT NULL DEFAULT 20,
  proficiency_copper  integer     NOT NULL DEFAULT 10,
  proficiency_steel   integer     NOT NULL DEFAULT 0,
  proficiency_jade    integer     NOT NULL DEFAULT 0,
  proficiency_special integer     NOT NULL DEFAULT 0,
  created_at          timestamptz NOT NULL DEFAULT now()
);
