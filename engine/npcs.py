"""P5 NPC 고용 시스템 — 후보 생성·비용 구간·수수료·시드 헬퍼.

단일 출처: websimulgamewiki/.../NPC_장인_시스템.md, [[인재관리_스킬_전환]]
정책 (2026-05-24 사용자 결정, 2026-05-31 통솔 stat → 인재관리 skill 전환):
  - 초기값: 6스탯 max(10, _roll_stat()-10) → 10~65 (캐릭터보다 한 단계 약함)
  - 기술: 제련 5~12, 단조 5~15, 열처리 5~12, 마감 0~7, 감정 0, 인재관리 10(고정)
  - 후보 풀: 배치마다 자동 갱신 (10·22시 KST), 유저당 3명
  - 비용 5구간 (NPC 6스탯 합 기준 — 7스탯에서 6/7 비례 재산정, _sim_6stat.py):
      ≤260: 영입 200/수수료 20    261~300: 800/60   301~385: 2000/150
      386~470: 5000/400           471+: 12000/1000
      (현행 3d6 굴림상 상위 2등급은 사실상 도달 불가 — 미래 고스탯 NPC용 예약, 7스탯도 동일했음)
"""

import random

from database import db_delete, db_insert, db_select
from engine.materials import MATERIALS

CANDIDATES_PER_USER = 3

# (stat_total_upper_inclusive, hire_cost, fee_per_batch) — 6스탯 합 기준 (2026-05-31 재산정)
NPC_FEE_BRACKETS = [
    (260, 200, 20),
    (300, 800, 60),
    (385, 2000, 150),
    (470, 5000, 400),
    (10_000, 12000, 1000),  # 471+ — 상한 무한대 대용 (미래 고스탯 NPC용 예약)
]

# NPC 인재관리 스킬 초기값 (고정). 캐릭터 20보다 한 단계 약함 ([[인재관리_스킬_전환]]).
NPC_TALENT_MANAGEMENT_INIT = 10

# NPC 기술 초기 분포 (wiki 예정값에서 한 단계 낮춤)
_SKILL_RANGES = {
    "smelting": (5, 12),
    "forging": (5, 15),
    "heat_treat": (5, 12),
    "finishing": (0, 7),
    "appraisal": (0, 0),  # 백엔드 keep / UI 미노출
}

# 임시 한국어 인명 풀 (P6+에서 삼국지 인명 콘텐츠로 확장)
_NPC_GIVEN_NAMES = [
    "건우",
    "재현",
    "민호",
    "성훈",
    "지훈",
    "도윤",
    "현우",
    "정현",
    "수민",
    "지호",
    "동현",
    "준호",
    "태현",
    "영민",
    "상호",
    "기태",
    "은수",
    "예린",
    "지원",
    "서연",
    "수아",
    "다인",
    "유진",
    "혜린",
]
_NPC_FAMILY_NAMES = [
    "김",
    "이",
    "박",
    "최",
    "정",
    "강",
    "조",
    "윤",
    "장",
    "임",
    "한",
    "오",
    "서",
    "신",
    "권",
    "황",
]


def _roll_npc_stat() -> int:
    """캐릭터 _roll_stat()와 동형 (3d6 * 5 cap 75) 후 -10, 하한 10."""
    base = min(sum(random.randint(1, 6) for _ in range(3)) * 5, 75)
    return max(10, base - 10)


def _random_npc_name() -> str:
    return random.choice(_NPC_FAMILY_NAMES) + random.choice(_NPC_GIVEN_NAMES)


def cost_bracket(stat_total: int) -> tuple[int, int]:
    """(hire_cost, fee_per_batch) 반환. 5구간 단계."""
    for cap, hire, fee in NPC_FEE_BRACKETS:
        if stat_total <= cap:
            return hire, fee
    last = NPC_FEE_BRACKETS[-1]
    return last[1], last[2]


def generate_candidate_payload() -> dict:
    """후보 1명의 raw payload 생성 — DB INSERT 전 단계."""
    stats = {
        k: _roll_npc_stat()
        for k in (
            "strength",
            "intelligence",
            "charisma",
            "health",
            "luck",
            "dexterity",
        )
    }
    stat_total = sum(stats.values())
    hire, fee = cost_bracket(stat_total)
    skills = {name: random.randint(lo, hi) for name, (lo, hi) in _SKILL_RANGES.items()}
    # 인재관리 스킬 고정 10 (통솔 stat → skill 전환). 단일 NPC 경로에선 NPC 본인 값은 미사용이나
    # P7+ 대장 시스템·성장을 위해 시드. 고용 시 npc_skills 로 복사됨 (routers/npc.py).
    skills["talent_management"] = NPC_TALENT_MANAGEMENT_INIT
    # 소재 숙련도 — 장인의 기초 자원은 1+ 보장 (0이면 잠금돼 작업 불가).
    # 캐릭터(raw_iron 30, chalcopyrite 20)보다 한 단계 약하게.
    proficiency = {code: 0 for code in MATERIALS}
    proficiency["raw_iron"] = random.randint(5, 20)  # 기초 광석 필수 보장
    proficiency["chalcopyrite"] = random.randint(1, 10)  # 구리 광석도 1+ 보장
    return {
        "name": _random_npc_name(),
        "stats": stats,
        "skills": skills,
        "proficiency": proficiency,
        "stat_total": stat_total,
        "hire_cost": hire,
        "fee": fee,
    }


def refresh_candidate_pool(
    user_id: str, batch_id: str | None = None, count: int = CANDIDATES_PER_USER
) -> int:
    """한 유저의 후보 풀 통째 교체. 이전 풀 전원 삭제 + 새 count명 생성.
    반환: 생성된 후보 수.
    """
    db_delete("npc_candidates", user_id=user_id)
    created = 0
    for _ in range(count):
        payload = generate_candidate_payload()
        db_insert(
            "npc_candidates",
            {
                "user_id": user_id,
                "name": payload["name"],
                "stats": payload["stats"],
                "skills": payload["skills"],
                "proficiency": payload["proficiency"],
                "stat_total": payload["stat_total"],
                "hire_cost": payload["hire_cost"],
                "base_hire_cost": payload["hire_cost"],  # 대실패 상승 시 원가 보존용
                "fee": payload["fee"],
                "fumble_count": 0,
                "batch_id": batch_id,
            },
        )
        created += 1
    return created


def refresh_all_user_pools(batch_id: str | None = None) -> dict:
    """모든 유저의 후보 풀 일괄 갱신. 배치 끝에서 호출.
    반환: {user_count, candidate_count}.
    """
    users = db_select("users")
    user_count = 0
    candidate_count = 0
    for u in users:
        c = refresh_candidate_pool(u["id"], batch_id=batch_id)
        user_count += 1
        candidate_count += c
    return {"user_count": user_count, "candidate_count": candidate_count}


def ensure_user_pool_seeded(user_id: str) -> dict:
    """유저 첫 진입(또는 부트 후 첫 요청) 시 풀이 비어있으면 시드.
    이미 후보가 있으면 멱등으로 통과.
    """
    existing = db_select("npc_candidates", user_id=user_id)
    if existing:
        return {"action": "skip", "count": len(existing)}
    created = refresh_candidate_pool(user_id)
    return {"action": "seeded", "count": created}


def ensure_all_pools_seeded() -> dict:
    """앱 부트 시 1회 호출. 후보 풀이 비어있는 유저만 시드 (멱등)."""
    users = db_select("users")
    seeded = 0
    for u in users:
        result = ensure_user_pool_seeded(u["id"])
        if result["action"] == "seeded":
            seeded += 1
    return {"users_seeded": seeded, "total_users": len(users)}
