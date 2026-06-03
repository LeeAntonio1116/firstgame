-- ============================================================
-- 안정성·무결성 취약점 fix — 2단계 (근본 수술: 자금·자원 RMW 원자화) (2026-05-30)
--   단일 출처: firstgame/안정성_취약점_진입가이드.md § 2단계 + wiki [[게임시스템_취약점_점검]]
--
-- 근본 원인 #1: 모든 자금·스태미너가 트랜잭션 없는 read-modify-write (database.py는
-- PostgREST 래퍼라 원자 증감·조건부 갱신 불가). 멀티워커 전환 시 동시 차감 레이스로
-- 잔액 초과 차감·이중 환불이 실재화. → DB 함수(plpgsql)로 원자 조건부 증감을 제공한다.
--
-- 사용자 결정 (2026-05-30): 배포 모델 = 멀티워커 목표 → 본 RPC 원자화가 멀티워커 선결.
--                          F-5 수수료 체불 = 발주 시 선불 홀드 (npcs.fee_held 추적).
--
-- 실행 위치: Supabase 대시보드 SQL Editor (통째로 실행). 안전망: OR REPLACE / IF NOT EXISTS.
-- ⚠️ stage1 마이그(migration_stability_stage1.sql)를 아직 안 돌렸으면 그것부터 실행할 것.
-- ============================================================

-- ── A-1: users.gold 원자 증감 ──
-- p_delta < 0 (차감): gold + p_delta >= 0 일 때만 적용 (조건부). 부족하면 NULL 반환.
-- p_delta >= 0 (입금): 항상 적용. 반환 = 새 잔액 (NULL = 유저 없음 또는 잔액 부족).
CREATE OR REPLACE FUNCTION adjust_user_gold(p_user_id uuid, p_delta integer)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
  new_gold integer;
BEGIN
  UPDATE users
    SET gold = gold + p_delta
    WHERE id = p_user_id
      AND (p_delta >= 0 OR gold + p_delta >= 0)
    RETURNING gold INTO new_gold;
  RETURN new_gold;  -- NULL = 잔액 부족(조건 미충족) 또는 유저 없음
END;
$$;

-- ── A-2: characters/npcs.stamina_current 원자 증감 ──
-- p_delta < 0 (차감): 잔량 충분 시만 (부족하면 NULL). p_delta >= 0 (충전): health/5로 클램프.
-- 반환 = 새 stamina_current (NULL = actor 없음 또는 차감 부족).
CREATE OR REPLACE FUNCTION adjust_actor_stamina(p_table text, p_actor_id uuid, p_delta integer)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
  new_val integer;
BEGIN
  IF p_table NOT IN ('characters', 'npcs') THEN
    RAISE EXCEPTION 'adjust_actor_stamina: invalid table %', p_table;
  END IF;
  EXECUTE format(
    'UPDATE %I SET stamina_current = '
    'CASE WHEN $1 >= 0 THEN LEAST(health / 5, stamina_current + $1) '
    '     ELSE stamina_current + $1 END '
    'WHERE id = $2 AND ($1 >= 0 OR stamina_current + $1 >= 0) '
    'RETURNING stamina_current',
    p_table
  ) USING p_delta, p_actor_id INTO new_val;
  RETURN new_val;  -- NULL = 스태미너 부족(조건 미충족) 또는 actor 없음
END;
$$;

-- ── F-5: NPC 수수료 선불 홀드 추적 컬럼 ──
-- 발주 시 fee_per_batch를 gold에서 선차감(홀드)하면 그 NPC.fee_held에 기록.
-- 배치 정산 시 0으로 리셋(이미 선불). 마지막 pending 취소·해고 시 환불.
ALTER TABLE npcs ADD COLUMN IF NOT EXISTS fee_held INTEGER NOT NULL DEFAULT 0;

-- ── F-5: 수수료 홀드/환불/정산 — fee_held + gold를 한 트랜잭션에서 원자 처리 ──
-- (적대적 리뷰 반영: fee_held를 앱 레이어 RMW로 두면 동시 발주/취소에서 이중차감·이중환불.
--  FOR UPDATE로 NPC 행을 잠가 동시 호출을 직렬화 → 정확히 1회만 홀드/환불/정산.)

-- 홀드: fee_held=0(이번 창 첫 명령)일 때만 gold 조건부 차감 + fee_held=fee.
-- 반환: 홀드액 / 0(이미 홀드됨·NPC 없음) / NULL(자금 부족).
CREATE OR REPLACE FUNCTION hold_npc_fee(p_npc_id uuid, p_user_id uuid, p_fee integer)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
  cur_held integer;
  new_gold integer;
BEGIN
  SELECT fee_held INTO cur_held FROM npcs WHERE id = p_npc_id FOR UPDATE;
  IF cur_held IS NULL THEN
    RETURN 0;          -- NPC 없음
  END IF;
  IF cur_held <> 0 THEN
    RETURN 0;          -- 이미 이번 창에 홀드됨 (추가 홀드 없음)
  END IF;
  UPDATE users SET gold = gold - p_fee
    WHERE id = p_user_id AND gold >= p_fee
    RETURNING gold INTO new_gold;
  IF new_gold IS NULL THEN
    RETURN NULL;       -- 자금 부족 → 홀드 안 함 (NPC 행 잠금은 트랜잭션 종료 시 해제)
  END IF;
  UPDATE npcs SET fee_held = p_fee WHERE id = p_npc_id;
  RETURN p_fee;
END;
$$;

-- 환불: fee_held>0이면 gold 환불 + 0 리셋 (단일 승자 — 동시 취소/해고에도 1회만).
-- 반환: 환불액 (0 = 홀드 없음/NPC 없음).
CREATE OR REPLACE FUNCTION release_npc_fee(p_npc_id uuid, p_user_id uuid)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
  held integer;
BEGIN
  SELECT fee_held INTO held FROM npcs WHERE id = p_npc_id FOR UPDATE;
  IF held IS NULL OR held = 0 THEN
    RETURN 0;
  END IF;
  UPDATE npcs SET fee_held = 0 WHERE id = p_npc_id;
  UPDATE users SET gold = gold + held WHERE id = p_user_id;
  RETURN held;
END;
$$;

-- 배치 정산: fee_held>0이면 0 리셋(이미 선불, 차감 X). fee_held=0이면 fallback 차감(잔액 충분 시).
-- 반환: fallback 차감액 (0 = 선불 정산됨).
CREATE OR REPLACE FUNCTION settle_npc_fee(p_npc_id uuid, p_user_id uuid, p_fee integer)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
  held integer;
BEGIN
  SELECT fee_held INTO held FROM npcs WHERE id = p_npc_id FOR UPDATE;
  IF held IS NULL THEN
    RETURN 0;          -- NPC 없음
  END IF;
  IF held <> 0 THEN
    UPDATE npcs SET fee_held = 0 WHERE id = p_npc_id;  -- 선불 소진(정산)
    RETURN 0;
  END IF;
  UPDATE users SET gold = gold - p_fee
    WHERE id = p_user_id AND gold >= p_fee;            -- 안전망 fallback (insolvent면 무차감)
  RETURN p_fee;
END;
$$;

-- ── C-4/동시실행 가드: 'running' 배치 단일성을 DB 차원에서 강제 ──
-- (적대적 리뷰 반영: SELECT-then-INSERT는 TOCTOU. 부분 unique 인덱스로 두 번째 INSERT를 거부.)
-- 기존 'running' 잔류(직전 비정상 종료)는 인덱스 생성 전 'failed'로 정리 (마이그 시점엔 배치 미실행 가정).
UPDATE batches SET status = 'failed' WHERE status = 'running';
CREATE UNIQUE INDEX IF NOT EXISTS uniq_batches_one_running
  ON batches (status) WHERE status = 'running';

-- ── 권한: PostgREST 노출 (service_role/anon/authenticated 모두 EXECUTE) ──
GRANT EXECUTE ON FUNCTION adjust_user_gold(uuid, integer) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION adjust_actor_stamina(text, uuid, integer) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION hold_npc_fee(uuid, uuid, integer) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION release_npc_fee(uuid, uuid) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION settle_npc_fee(uuid, uuid, integer) TO anon, authenticated, service_role;

-- PostgREST 스키마 캐시 리로드 (신규 함수 즉시 인식)
NOTIFY pgrst, 'reload schema';

-- ============================================================
-- 검증 쿼리 (사용자가 SQL Editor에서 직접 실행)
-- ============================================================
-- 1) 함수 생성 확인
-- SELECT proname, pg_get_function_arguments(oid)
--   FROM pg_proc WHERE proname IN ('adjust_user_gold', 'adjust_actor_stamina');
--   (2 rows 기대)
--
-- 2) fee_held 컬럼 확인
-- SELECT column_name, data_type, column_default FROM information_schema.columns
--   WHERE table_name = 'npcs' AND column_name = 'fee_held';
--   (1 row, integer, 0 기대)
--
-- 3) 자금 원자 차감 동작 — 본인 user_id로 테스트 (값 확인 후 원복)
-- SELECT gold FROM users WHERE id = '<user_id>';                 -- 현재 잔액 A
-- SELECT adjust_user_gold('<user_id>', -10);                     -- A-10 반환
-- SELECT adjust_user_gold('<user_id>', 10);                      -- A 반환 (원복)
-- SELECT adjust_user_gold('<user_id>', -999999999);              -- NULL 기대 (잔액 부족 → 차감 안 됨)
-- SELECT gold FROM users WHERE id = '<user_id>';                 -- 여전히 A 기대
--
-- 4) 스태미너 원자 차감/충전 — 본인 캐릭터로 테스트
-- SELECT adjust_actor_stamina('characters', '<char_id>', -1);    -- (현재-1) 또는 NULL(부족)
-- SELECT adjust_actor_stamina('characters', '<char_id>', 9999);  -- health/5로 클램프된 값
