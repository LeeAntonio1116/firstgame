-- P3-1 소재 인벤토리화: items.quality CHECK 완화
-- ore는 quality=0으로 저장. 무기·주괴는 기존대로 1~5.
-- UNIQUE (owner_id, item_type, material, quality)는 그대로 — quality=0 row가 같은 owner+ore+material에 단 하나만 존재.

ALTER TABLE items DROP CONSTRAINT IF EXISTS items_quality_check;
ALTER TABLE items ADD CONSTRAINT items_quality_check CHECK (quality BETWEEN 0 AND 5);
