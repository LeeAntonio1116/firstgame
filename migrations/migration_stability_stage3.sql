-- ============================================================
-- 안정성·무결성 취약점 fix — 3단계 (잔여 경계·정책) (2026-05-30)
--   단일 출처: firstgame/안정성_취약점_진입가이드.md § 3단계 + STATUS.md
--   ⚠️ stage1·stage2 마이그(migration_stability_stage1·stage2.sql)를 먼저 실행했어야 함.
--      (이 마이그는 stage2의 adjust_user_gold·hold_npc_fee를 gold BIGINT 대응으로 교체한다.)
--
-- 실행 위치: Supabase 대시보드 SQL Editor (통째로 실행). 안전망: IF NOT EXISTS / OR REPLACE.
-- ============================================================

-- ── A-5: 캐릭터 중복 생성 차단 (1 user 1 character 불변식 DB 강제) ──
-- character/confirm의 read-check를 통과한 동시 요청 2개가 모두 INSERT하는 레이스를 UNIQUE로 차단.
-- 코드는 INSERT 시 409를 catch해 대시보드로 보냄. 기존 데이터는 1:1 불변식이라 중복 없음(생성 성공해야 정상).
CREATE UNIQUE INDEX IF NOT EXISTS uniq_characters_user ON characters (user_id);

-- ── F-2: users.gold int4 → BIGINT (오버플로 500 방지) ──
-- 정·관·량 단위(1정=1,000,000량)라 누적·배치 입금·관리자 지급으로 int4 상한(약 2.1e9 ≈ 2147정)을
-- 넘으면 PostgreSQL이 'integer out of range' 500을 던졌음. BIGINT(약 9.2e18)로 사실상 해소.
ALTER TABLE users ALTER COLUMN gold TYPE BIGINT;

-- gold가 BIGINT가 됐으므로 자금 RPC를 bigint 대응으로 교체.
-- adjust_user_gold: p_delta·반환을 bigint로 (int4 시그니처는 DROP — 같은 이름 int4/bigint 중복 방지).
DROP FUNCTION IF EXISTS adjust_user_gold(uuid, integer);
CREATE OR REPLACE FUNCTION adjust_user_gold(p_user_id uuid, p_delta bigint)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
  new_gold bigint;
BEGIN
  UPDATE users
    SET gold = gold + p_delta
    WHERE id = p_user_id
      AND (p_delta >= 0 OR gold + p_delta >= 0)
    RETURNING gold INTO new_gold;
  RETURN new_gold;  -- NULL = 잔액 부족(조건 미충족) 또는 유저 없음
END;
$$;

-- hold_npc_fee: gold를 담는 내부 변수 new_gold를 bigint로 (시그니처·반환은 그대로 integer).
CREATE OR REPLACE FUNCTION hold_npc_fee(p_npc_id uuid, p_user_id uuid, p_fee integer)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
  cur_held integer;
  new_gold bigint;
BEGIN
  SELECT fee_held INTO cur_held FROM npcs WHERE id = p_npc_id FOR UPDATE;
  IF cur_held IS NULL THEN
    RETURN 0;          -- NPC 없음
  END IF;
  IF cur_held <> 0 THEN
    RETURN 0;          -- 이미 이번 창에 홀드됨
  END IF;
  UPDATE users SET gold = gold - p_fee
    WHERE id = p_user_id AND gold >= p_fee
    RETURNING gold INTO new_gold;
  IF new_gold IS NULL THEN
    RETURN NULL;       -- 자금 부족
  END IF;
  UPDATE npcs SET fee_held = p_fee WHERE id = p_npc_id;
  RETURN p_fee;
END;
$$;
-- (release_npc_fee·settle_npc_fee·adjust_actor_stamina는 gold를 변수에 담지 않아 교체 불필요.)

GRANT EXECUTE ON FUNCTION adjust_user_gold(uuid, bigint) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION hold_npc_fee(uuid, uuid, integer) TO anon, authenticated, service_role;

-- PostgREST 스키마 캐시 리로드
NOTIFY pgrst, 'reload schema';

-- ============================================================
-- 검증 쿼리 (사용자가 SQL Editor에서 직접 실행)
-- ============================================================
-- 1) characters.user_id UNIQUE 확인
-- SELECT indexname FROM pg_indexes WHERE tablename = 'characters' AND indexname = 'uniq_characters_user';
--   (1 row 기대)
--
-- 2) users.gold 타입 = bigint 확인
-- SELECT data_type FROM information_schema.columns WHERE table_name='users' AND column_name='gold';
--   (bigint 기대)
--
-- 3) adjust_user_gold 시그니처 = (uuid, bigint) RETURNS bigint, int4 버전 없음 확인
-- SELECT proname, pg_get_function_arguments(oid), pg_get_function_result(oid)
--   FROM pg_proc WHERE proname = 'adjust_user_gold';
--   (1 row: "p_user_id uuid, p_delta bigint" → bigint 기대)
--
-- 4) 큰 값 동작 — 본인 user_id로 (값 확인 후 원복)
-- SELECT adjust_user_gold('<user_id>', 3000000000);   -- 옛 int4면 오류였을 값, 이제 정상 (현재+30억)
-- SELECT adjust_user_gold('<user_id>', -3000000000);  -- 원복
