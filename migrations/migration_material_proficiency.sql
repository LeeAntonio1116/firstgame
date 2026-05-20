-- 소재별 숙련도 테이블 생성
CREATE TABLE material_proficiency (
    character_id UUID REFERENCES characters(id) ON DELETE CASCADE,
    material_type TEXT NOT NULL,
    value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (character_id, material_type)
);

-- 다른 테이블과 동일하게 RLS 비활성화 (REST API 접근을 위해 필수)
ALTER TABLE material_proficiency DISABLE ROW LEVEL SECURITY;

-- 기존 캐릭터에 초기 숙련도 INSERT
INSERT INTO material_proficiency (character_id, material_type, value)
SELECT id, 'raw_iron', 30 FROM characters;

INSERT INTO material_proficiency (character_id, material_type, value)
SELECT id, 'chalcopyrite', 20 FROM characters;

INSERT INTO material_proficiency (character_id, material_type, value)
SELECT id, 'malachite', 5 FROM characters;

INSERT INTO material_proficiency (character_id, material_type, value)
SELECT id, 'galena', 5 FROM characters;

-- 기존 카테고리 숙련도 컬럼 제거
ALTER TABLE characters
    DROP COLUMN IF EXISTS proficiency_iron,
    DROP COLUMN IF EXISTS proficiency_copper,
    DROP COLUMN IF EXISTS proficiency_steel,
    DROP COLUMN IF EXISTS proficiency_jade,
    DROP COLUMN IF EXISTS proficiency_special;

-- commands 테이블에 input_type 추가 (Phase 1: ore만, Phase 2에서 ingot 활성화)
ALTER TABLE commands ADD COLUMN IF NOT EXISTS input_type TEXT NOT NULL DEFAULT 'ore';
