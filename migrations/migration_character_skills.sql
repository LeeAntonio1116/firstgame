-- 캐릭터별 기술치 테이블 (제련/단조/열처리/마감/감정)
CREATE TABLE character_skills (
    character_id UUID REFERENCES characters(id) ON DELETE CASCADE,
    skill_name TEXT NOT NULL,
    value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (character_id, skill_name)
);

-- RLS 비활성화 (REST API 접근을 위해 필수)
ALTER TABLE character_skills DISABLE ROW LEVEL SECURITY;

-- 기존 캐릭터에 초기 기술치 INSERT
INSERT INTO character_skills (character_id, skill_name, value)
SELECT id, 'smelting', 15 FROM characters;

INSERT INTO character_skills (character_id, skill_name, value)
SELECT id, 'forging', 20 FROM characters;

INSERT INTO character_skills (character_id, skill_name, value)
SELECT id, 'heat_treat', 15 FROM characters;

INSERT INTO character_skills (character_id, skill_name, value)
SELECT id, 'finishing', 10 FROM characters;

INSERT INTO character_skills (character_id, skill_name, value)
SELECT id, 'appraisal', 0 FROM characters;
