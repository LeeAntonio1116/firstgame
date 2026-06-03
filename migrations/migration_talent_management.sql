-- ============================================================
-- 인재관리 스킬 전환 마이그레이션 (2026-05-31)
--   통솔(leadership) 스탯 → 인재관리(talent_management) 스킬. 7스탯 → 6스탯.
--   단일 출처: websimulgamewiki/.../인재관리_스킬_전환.md
--   사용자 결정(2026-05-30): 인재관리 초기값 캐릭터 20 / NPC 10. 점검 단계 — 데이터 리셋 허용.
--   시뮬(2026-05-31, _sim_6stat.py): 6스탯 STAT_TOTAL_CAP=355(기각률 9.88%≈7스탯 410의 10.22%),
--   NPC 비용 구간 6/7 비례 재산정(260/300/385/470).
--
-- 실행 방법: Supabase 대시보드 SQL Editor에서 통째로 실행.
-- ⚠️ 이 마이그를 실행해야 코드가 정상 동작한다. 코드는 더 이상 leadership 컬럼을 참조하지 않고
--    character_skills/npc_skills 의 'talent_management' row 를 참조한다. 안 돌리면 캐릭터/NPC/배치가 깨진다.
-- 안전망: IF EXISTS / ON CONFLICT DO NOTHING — 부분 재실행 OK. leadership 컬럼은 DROP IF EXISTS 라 멱등.
-- ============================================================

-- ── 1. 기존 캐릭터에 인재관리 스킬 시드 (value=20, exp=0) ──
--    SKILL_DEFINITIONS 에 talent_management=20 추가 → 신규 캐릭터는 코드가 자동 시드. 기존분만 여기서.
INSERT INTO character_skills (character_id, skill_name, value, exp)
SELECT c.id, 'talent_management', 20, 0
FROM characters c
ON CONFLICT (character_id, skill_name) DO NOTHING;

-- ── 2. 기존 NPC에 인재관리 스킬 시드 (value=10, exp=0) ──
--    신규 NPC 후보는 generate_candidate_payload 가 skills 에 talent_management=10 박음. 기존 고용분만 여기서.
INSERT INTO npc_skills (npc_id, skill_name, value, exp)
SELECT n.id, 'talent_management', 10, 0
FROM npcs n
ON CONFLICT (npc_id, skill_name) DO NOTHING;

-- ── 3. 통솔 stat_exp row 제거 (성장 트리거가 stat→skill 로 이동) ──
--    인재관리 exp 는 character_skills.exp / npc_skills.exp 에서 누적된다 (기존 스킬 exp 구조 재사용).
DELETE FROM character_stat_exp WHERE stat_name = 'leadership';
DELETE FROM npc_stat_exp        WHERE stat_name = 'leadership';

-- ── 4. leadership 스탯 컬럼 제거 (6스탯 전환) ──
--    점검 단계 — 데이터 리셋 허용. leadership 값→스킬 변환 공식 불필요(사용자 결정).
ALTER TABLE characters DROP COLUMN IF EXISTS leadership;
ALTER TABLE npcs       DROP COLUMN IF EXISTS leadership;

-- ============================================================
-- 검증 쿼리 (사용자가 SQL Editor 에서 직접 실행)
-- ============================================================
-- 1) leadership 컬럼 제거 확인 — 0 rows 기대
-- SELECT table_name, column_name FROM information_schema.columns
--   WHERE table_name IN ('characters','npcs') AND column_name = 'leadership';
--
-- 2) 인재관리 스킬 시드 확인 — char 수 = 캐릭터 수, npc 수 = NPC 수 기대
-- SELECT
--   (SELECT COUNT(*) FROM characters) AS char_count,
--   (SELECT COUNT(*) FROM character_skills WHERE skill_name='talent_management') AS char_tm,
--   (SELECT COUNT(*) FROM npcs) AS npc_count,
--   (SELECT COUNT(*) FROM npc_skills WHERE skill_name='talent_management') AS npc_tm;
--
-- 3) 인재관리 초기값 확인 — 캐릭터 20 / NPC 10 기대 (기존 row 한정; 이미 성장한 값이 있으면 그 값)
-- SELECT skill_name, MIN(value), MAX(value) FROM character_skills
--   WHERE skill_name='talent_management' GROUP BY skill_name;
-- SELECT skill_name, MIN(value), MAX(value) FROM npc_skills
--   WHERE skill_name='talent_management' GROUP BY skill_name;
--
-- 4) 통솔 stat_exp 제거 확인 — 둘 다 0 rows 기대
-- SELECT COUNT(*) FROM character_stat_exp WHERE stat_name='leadership';
-- SELECT COUNT(*) FROM npc_stat_exp        WHERE stat_name='leadership';
