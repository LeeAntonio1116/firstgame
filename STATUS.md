# STATUS — 현재 개발 상태
> 세션 시작 시 CLAUDE.md 다음으로 읽는다. 세션 종료 시 반드시 갱신한다.
> Last updated: 2026-05-20

---

## 완료된 기능

| 기능 | 파일 | 비고 |
|------|------|------|
| 로그인 / 로그아웃 | routers/auth.py | JWT 쿠키 |
| 회원가입 | routers/auth.py | bcrypt + 초대코드 |
| 회원탈퇴 | routers/auth.py | 비밀번호 확인 후 삭제 |
| 캐릭터 생성 | routers/character.py | 3d6×5, 합계 350 상한, material_proficiency + character_skills 초기값 자동 INSERT |
| 메인 페이지(대시보드) | templates/dashboard.html | 3열 레이아웃, 상단/사이드 탭 JS 전환, hash 자동 탭 전환 |
| 대장간 사업 시작 | routers/blacksmith.py | POST /blacksmith/start |
| 명령서 제출 | routers/command.py | POST /commands/submit (raw_iron 고정), 중상 차단 |
| d100 주사위 엔진 | engine/dice.py | 성공 레벨 판정 + 대실패 안전망 + bonus_dice + growth_check |
| 소재 정의 | engine/materials.py | 광석 10종, 합금 4종, 선행 트리, 공정 구성, SKILL_DEFINITIONS |
| 대장간 판정 (2회) | engine/blacksmith.py | 공정당 제작+소재 판정 2회, 부상 -20 패널티, cascade 반환 |
| 배치 처리기 | engine/batch.py | 회복 처리 + 숙련도/선행/마일스톤 + 성장 판정 + items stack + cascade 중상 처리 |
| 수동 배치 트리거 | routers/admin.py | POST /admin/run-batch (대시보드 하단 버튼) |
| 우편함 결과 표시 | templates/dashboard.html | 2회 판정 내역 + 품질 등급 + 성장 판정 표시 |
| 소재 숙련도 UI | templates/dashboard.html | material_proficiency 테이블 기반 동적 표시 |
| 대장간 기술 UI | templates/dashboard.html | character_skills 테이블 기반 (제련/단조/열처리/마감) |
| **character_skills** | migrations + DB + 코드 | 5개 기술(제련 15, 단조 20, 열처리 15, 마감 10, 감정 0) DB 저장, 공정 실패 시 skill별 성장 판정 |
| **부상·중상·NPC사망** | migrations + DB + 코드 | 부상=도박 허용 -20 패널티 / 중상=2배치 행동불능 / npcs.is_dead 컬럼 (NPC 작업은 P2) |
| **부상 회복** | engine/batch.py | 부상=명령 미제출 1배치, 중상=2배치 카운트다운, 회복 mailbox 발송 |
| **items 인벤토리** | migrations + 코드 | stack 시스템 (owner+type+material+quality UNIQUE, quantity++), 창고 탭 표시 |
| **품질 임계값 재조정** | engine/blacksmith.py | ≥5/2/-1/-4 — 시뮬레이션 기반 (광석 평균 50 → 1·2·3등급 균형) |

## 현재 상태

- **레벨 1 완료 + 소재 숙련도 B방식 + P1 4항목 완료 (2026-05-20)**
- 판정 구조: 공정당 2회 (제작공정 판정 + 소재 숙련도 판정), 부상 시 양쪽 -20
- 소재: 광석 10종 + 합금 4종, 초기 해금 raw_iron(30), chalcopyrite(20), malachite(5), galena(5)
- 기술치: 제련(15)/단조(20)/열처리(15)/마감(10)/감정(0) — character_skills 테이블 (감정 UI 미노출)
- 부상 시스템: 부상은 도박 허용 -20 / 중상은 차단 + 2배치 / NPC 사망 컬럼 추가 (작업은 P2)
- 아이템: stack 시스템 (`(owner, item_type, material, quality)` UNIQUE), P1엔 ingot만 생성

## 다음 작업 (우선순위 순)

### P2 진입 (다음 세션)
1. **소재 선택 UI** — 현재 raw_iron 하드코딩, 통제실 탭에 해금 소재 드롭다운
2. **스태미너 시스템** — 체력/5 회당, ORE 공정 4 / INGOT 공정 3 소모, 부족 시 차단
3. **대실패 패널티 분리** — 공정 대실패(현행 유지) vs 소재 대실패(중단·부상 없음·숙련도 -1%)

### P3
4. 합금 제작 UI (ALLOY_RECIPES 활용)
5. 고용인(NPC 장인) 시스템 — character_skills 기반
6. admin 패널 분리 (현재 대시보드 하단 배치 버튼 노출)

### Wiki 정리 미완료
- `대장간_기술체계.md:85`의 "성공 시 +d5%" 제거 (`소재_체계.md`로 일원화)
- 기술치 성장 룰 명시: "공정 일반 실패 시 해당 skill 1회 성장 판정 (skill별 배치당 1회)"
- `아이템_인벤토리.md` process_log 구조: wiki 평탄화 스키마 vs 구현 중첩 구조 — 구현 그대로 유지로 통일 권장

---

## 핵심 파일 구조

```
firstgame/
├── main.py              ← 앱 진입점, 라우터 등록 (5개)
├── config.py            ← 환경변수 (JWT, Supabase, 초대코드)
├── database.py          ← Supabase REST API 래퍼 (select/insert/update/delete)
├── engine/
│   ├── dice.py          ← d100 판정 엔진
│   ├── blacksmith.py    ← 5공정 판정 + 품질 등급
│   └── batch.py         ← 배치 처리기
├── routers/
│   ├── auth.py          ← 인증 전반 + 대시보드 (commands/mailbox 포함 전달)
│   ├── character.py     ← 캐릭터 생성
│   ├── blacksmith.py    ← 대장간 사업 시작
│   ├── command.py       ← 명령서 제출
│   └── admin.py         ← 수동 배치 트리거
└── templates/
    ├── base.html
    ├── login.html
    ├── register.html
    ├── dashboard.html   ← 메인 페이지 (통제실/우편함 실제 구현 완료)
    └── character_create.html
```

## Supabase 주의사항
- 새 테이블 생성 시 RLS 자동 활성화 → INSERT/SELECT 전부 차단됨
- 해결: `alter table {테이블명} disable row level security;`
- 이 프로젝트는 자체 JWT 인증 사용 → RLS 대신 앱 레벨에서 권한 관리
