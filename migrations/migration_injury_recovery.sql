-- 부상·중상 컬럼 추가 (캐릭터)
ALTER TABLE characters
    ADD COLUMN IF NOT EXISTS is_injured BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_serious_injured BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS serious_injury_remaining INTEGER NOT NULL DEFAULT 0;

-- NPC 사망 컬럼 추가 (npcs.is_injured는 이미 존재)
ALTER TABLE npcs
    ADD COLUMN IF NOT EXISTS is_dead BOOLEAN NOT NULL DEFAULT FALSE;
