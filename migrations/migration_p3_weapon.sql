-- P3-2 무기 제작: commands 테이블에 작업 종류·무기 카테고리 추가
-- work_type: 'ingot' (주괴 제작 — 기존 흐름) / 'weapon' (무기 제작) / 'alloy' (P3-3 합금주괴 제작)
-- weapon_category: work_type='weapon'일 때만 필수. dagger / greatsword / longsword / shortspear / longspear / axe / greataxe

ALTER TABLE commands
    ADD COLUMN IF NOT EXISTS work_type TEXT NOT NULL DEFAULT 'ingot',
    ADD COLUMN IF NOT EXISTS weapon_category TEXT;
