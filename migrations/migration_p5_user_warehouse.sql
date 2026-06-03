-- ============================================================
-- P5 창고 공유 — 창고는 user 단위, 인벤은 actor(캐릭터/NPC) 단위 (2026-05-24)
--
-- 정책:
--   - location='warehouse' → items.owner_id = user_id (유저 1명이 모든 캐릭터/NPC 자원 공유)
--   - location='inventory' → items.owner_id = actor_id (캐릭터·NPC 각자 5칸)
--
-- 마이그레이션:
--   1. 기존 warehouse rows의 owner_id를 character.user_id 또는 npc.owner_id로 변환
--   2. user 단위로 (item_type, material, quality) 합산 (UNIQUE 충돌 회피)
--   3. 기존 row 삭제 후 합산 결과 재 INSERT
--
-- 실행 전 권장: Supabase 대시보드에서 items 테이블 데이터 export로 백업.
-- ============================================================

BEGIN;

-- batch_id는 통합 후 의미 없으므로 NULL 처리 (UUID 타입은 MIN/MAX 미지원).
CREATE TEMP TABLE _new_warehouse AS
SELECT
  COALESCE(c.user_id, n.owner_id) AS new_owner_id,
  i.item_type,
  i.material,
  i.quality,
  SUM(i.quantity)::INTEGER AS quantity,
  MIN(i.created_at) AS created_at
FROM items i
LEFT JOIN characters c ON i.owner_id = c.id
LEFT JOIN npcs n ON i.owner_id = n.id
WHERE i.location = 'warehouse'
GROUP BY 1, 2, 3, 4;

DELETE FROM items WHERE location = 'warehouse';

INSERT INTO items (owner_id, item_type, material, quality, quantity, location, created_at)
SELECT new_owner_id, item_type, material, quality, quantity, 'warehouse', created_at
FROM _new_warehouse
WHERE new_owner_id IS NOT NULL;

COMMIT;

-- ============================================================
-- 검증 쿼리
-- ============================================================
-- 1) 본인 user의 창고 전체 확인 (어느 actor 창고가 아닌 통합된 user 창고)
-- SELECT item_type, material, quality, quantity
-- FROM items
-- WHERE owner_id = '<user_id>' AND location = 'warehouse'
-- ORDER BY item_type, material, quality;
--
-- 2) 인벤은 여전히 actor별 (캐릭터·NPC 각자)
-- SELECT owner_id, item_type, material, quality, quantity
-- FROM items
-- WHERE location = 'inventory'
-- ORDER BY owner_id, item_type;
--
-- 3) orphan check — characters/npcs/users 어느 곳에도 없는 owner_id 있는지
-- SELECT i.owner_id, i.location, COUNT(*)
-- FROM items i
-- LEFT JOIN users u ON i.owner_id = u.id
-- LEFT JOIN characters c ON i.owner_id = c.id
-- LEFT JOIN npcs n ON i.owner_id = n.id
-- WHERE u.id IS NULL AND c.id IS NULL AND n.id IS NULL
-- GROUP BY i.owner_id, i.location;
-- (결과 0행이면 정상)
