-- ============================================================
-- 보안: public 스키마 전 테이블 RLS 활성 (deny-all) + anon/authenticated RPC GRANT 회수
--   단일 출처: firstgame/STATUS.md § 보안 패스 (Part A) + wiki [[게임시스템_취약점_점검]]
--
-- 근본 원인: 앱이 Supabase publishable 키(anon 역할)를 쓰는데 모든 테이블 RLS가 꺼져 있어,
-- 그 키 하나만 유출되면 /rest/v1/<table>로 앱의 JWT·CSRF·rate limit을 우회해 DB 전체를
-- 읽고 쓸 수 있었다(2차 방어선 없음). publishable 키는 본래 공개되도록 설계된 자격증명이라
-- RLS가 유일한 방어선인데 그게 비활성이었다.
--
-- 해결: 앱을 secret 키(service_role, RLS 우회)로 전환하고, 모든 public 테이블에 RLS를 켠다.
-- 정책을 만들지 않으므로 anon/authenticated는 전면 차단(deny-all). 앱은 secret 키라 우회 →
-- 거동 변화 0. publishable 키는 유출돼도 무력화된다.
--
-- ⚠️⚠️ 실행 순서 절대 준수 ⚠️⚠️
--   이 마이그를 돌리기 전에 반드시 SUPABASE_KEY를 secret 키(sb_secret_…)로 먼저 교체하고
--   재배포/재시작해 앱이 정상 동작함을 확인할 것. publishable 키인 채로 이 마이그를 돌리면
--   앱의 모든 쿼리가 RLS에 막혀 빈 결과 → 즉시 전면 outage가 발생한다.
--
-- 실행 위치: Supabase 대시보드 SQL Editor (통째로 실행). 멱등(ENABLE/REVOKE 재실행 안전).
-- ============================================================

-- ── 1) public 스키마 전 테이블 RLS 활성 (정책 없음 = deny-all to anon/authenticated) ──
-- service_role(secret 키)은 BYPASSRLS라 영향 없음. 뷰는 pg_tables에 없어 자동 제외.
DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
  END LOOP;
END $$;

-- ── 2) 심층 방어: 자금·자원 RPC의 anon/authenticated EXECUTE 회수 ──
-- (RLS가 켜지면 anon이 RPC를 호출해도 내부 UPDATE가 RLS에 막히지만, 호출 자체도 막아 둔다.
--  service_role GRANT는 유지 → 앱(secret 키)은 그대로 동작. 오버로드·미존재도 안전 처리.)
-- ⚠️ PUBLIC 필수: PostgreSQL은 함수 생성 시 EXECUTE를 PUBLIC(모든 역할)에 기본 부여한다.
--    anon/authenticated의 명시적 권한만 회수하면 PUBLIC 기본 권한이 남아 has_function_privilege가
--    여전히 true. PUBLIC에서도 회수해야 실제로 닫힌다. service_role은 명시적 GRANT라 유지됨.
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT p.oid::regprocedure AS sig
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.proname IN (
        'adjust_user_gold', 'adjust_actor_stamina',
        'hold_npc_fee', 'release_npc_fee', 'settle_npc_fee'
      )
  LOOP
    EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC, anon, authenticated', r.sig);
  END LOOP;
END $$;

-- PostgREST 스키마 캐시 리로드
NOTIFY pgrst, 'reload schema';

-- ============================================================
-- 검증 쿼리 (사용자가 SQL Editor에서 직접 실행 — 또는 migrations/verify_db_security.sql)
-- ============================================================
-- 1) 전 테이블 RLS 켜졌는지 (rowsecurity 전부 t 기대)
-- SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public' ORDER BY tablename;
--
-- 2) RPC GRANT — anon/authenticated=f, service_role=t 기대
-- SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS args,
--        has_function_privilege('anon', p.oid, 'EXECUTE')          AS anon_exec,
--        has_function_privilege('authenticated', p.oid, 'EXECUTE')  AS auth_exec,
--        has_function_privilege('service_role', p.oid, 'EXECUTE')   AS svc_exec
--   FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
--   WHERE n.nspname='public' AND p.proname IN
--     ('adjust_user_gold','adjust_actor_stamina','hold_npc_fee','release_npc_fee','settle_npc_fee')
--   ORDER BY p.proname;
--
-- 3) (앱 전환 확인) 옛 publishable 키로 직접 호출 시 차단되는지 — 셸에서:
-- curl "$SUPABASE_URL/rest/v1/users?select=*" -H "apikey: <publishable>" -H "Authorization: Bearer <publishable>"
--   → 이전엔 전체 행, 이제 [] 또는 권한 오류 기대
