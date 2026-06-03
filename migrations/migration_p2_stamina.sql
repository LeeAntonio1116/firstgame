-- P2 기획 6: 스태미너 시스템
-- stamina_current = floor(health / 5) — 배치 시작 시 풀 회복, 명령 처리 시 차감
ALTER TABLE characters
    ADD COLUMN IF NOT EXISTS stamina_current INTEGER NOT NULL DEFAULT 0;

-- 기존 캐릭터 row 초기값: floor(health / 5)
UPDATE characters
SET stamina_current = FLOOR(health / 5.0)
WHERE stamina_current = 0;
