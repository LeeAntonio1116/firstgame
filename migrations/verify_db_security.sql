-- ============================================================
-- DB 보안 점검 (읽기 전용 — 스키마 변경 없음). 배포·마이그 후 Supabase SQL Editor에서 실행.
--   단일 출처: firstgame/STATUS.md § 보안 패스. RLS 상태 + RPC 완전성을 한 번에 확인.
--   * 'migration_' 접두사를 일부러 피함 — 점검용이지 적용 대상이 아니다.
-- ============================================================

-- ── A) RLS 상태: public 전 테이블이 켜졌는지 (rowsecurity 전부 t 기대) ──
SELECT tablename, rowsecurity
  FROM pg_tables
  WHERE schemaname = 'public'
  ORDER BY rowsecurity, tablename;   -- f가 위로 와야 누락이 즉시 보임

-- ── B) RPC 시그니처 + GRANT 전수 (service_role만 EXECUTE, anon/authenticated는 회수 기대) ──
-- 오버로드 중복(예: adjust_user_gold가 integer·bigint 둘 다 존재)도 행으로 드러난다.
SELECT p.proname AS fn,
       pg_get_function_identity_arguments(p.oid) AS args,
       has_function_privilege('anon', p.oid, 'EXECUTE')          AS anon_exec,
       has_function_privilege('authenticated', p.oid, 'EXECUTE')  AS auth_exec,
       has_function_privilege('service_role', p.oid, 'EXECUTE')   AS svc_exec
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname = 'public'
    AND p.proname IN
      ('adjust_user_gold', 'adjust_actor_stamina', 'hold_npc_fee', 'release_npc_fee', 'settle_npc_fee')
  ORDER BY p.proname, args;

-- ── C) 누락 함수: 기대 5개 중 아예 없는 것 (0행 기대) ──
SELECT e.fn AS missing_fn
  FROM (VALUES ('adjust_user_gold'), ('adjust_actor_stamina'),
               ('hold_npc_fee'), ('release_npc_fee'), ('settle_npc_fee')) AS e(fn)
  WHERE NOT EXISTS (
    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
      WHERE n.nspname = 'public' AND p.proname = e.fn
  );

-- ── D) F-5 fee_held 컬럼 (1행, integer, default 0 기대) ──
SELECT column_name, data_type, column_default
  FROM information_schema.columns
  WHERE table_name = 'npcs' AND column_name = 'fee_held';

-- ============================================================
-- 합격 기준
--   A) 모든 행 rowsecurity = t
--   B) 5개 함수 행, svc_exec = t · anon_exec = f · auth_exec = f
--      (adjust_user_gold이 integer·bigint 2행이면 stage3 정리 누락 → DROP 정리 마이그 검토)
--   C) 0행 (누락 없음)
--   D) 1행 (fee_held integer, default 0)
-- ============================================================
