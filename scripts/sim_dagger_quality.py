"""주괴(생철광)→단검 제작 품질 시뮬레이션 (2026-06-01).

요청: 무작위 스탯 직원(NPC) 3명이 각 품질(1~5등급) 생철광 주괴로 단검을 각 1000회 제작.
'성장 판정 정상 진행' vs '성장 판정 스킵' 두 모드 비교.

설계 — 게임 엔진 충실 복제:
- 제작 판정은 engine.blacksmith.process_blacksmith_command를 **직접 호출** (게임과 100% 동일).
  단검=주괴 입력 → 3공정(단조→열처리→마감, STEPS_INGOT). 생철광=선행소재 없음 → prereq_bonus 0.
- 품질 보너스: 입력 등급 Q → total 시드 += max(0, Q-1)  (Q1=+0 … Q5=+4).
- NPC 생성: engine.npcs.generate_candidate_payload와 동일 분포를 인메모리 복제(DB import 회피).
- 성장(정상 모드): 게임의 _accumulate_exp + _apply_growth_due 로직 인메모리 복제.
    * 소재 대실패(mat_fumble) → 즉시 숙련 -fumble수 (game batch.py)
    * 일반 실패(소재/공정) → 해당 exp +1 (95 이상 또는 0 스킬은 누적 안 함)
    * 단조 실패→무력 exp / 열처리 실패→지략 exp / 안전망 통과→운 exp / 부상→건강 exp
    * 성장: is_growth_due(value, exp) = exp >= value//7 (value<95)면 value+1, exp 0
      (저값<7은 필요exp 0이라 자연 상승 — 게임 코드 그대로)
    * 마일스톤: 숙련 75+ 소재 보너스주사위 1, 85+ 대실패 안전(get_milestone_flags)
- [가정] 각 제작은 회복 상태(부상 비지속)에서 시작 — 부상 제작은 결과물 없음으로 별도 집계
  (game은 부상 시 명령 중단·회복 배치 필요. sim_quality.py와 동일한 단순화). 성장은 제작마다 성장판정 1회.

실행: firstgame/ 에서  .venv\\Scripts\\python.exe scripts/sim_dagger_quality.py
"""

# ruff: noqa: E402
import os
import random
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # firstgame 루트
sys.stdout.reconfigure(encoding="utf-8")

from engine import blacksmith, dice
from engine.materials import STEPS_INGOT, get_milestone_flags

RUNS = 1000
SEED = 20260601  # 재현성 — 같은 NPC 3명·결과 보장

STAT_NAMES = ("strength", "intelligence", "charisma", "health", "luck", "dexterity")
STAT_KR = {
    "strength": "무력",
    "intelligence": "지략",
    "charisma": "매력",
    "health": "건강",
    "luck": "운",
    "dexterity": "민첩",
}
CRAFT_SKILLS = ("forging", "heat_treat", "finishing")  # 단검(주괴) 3공정
SKILL_KR = {"forging": "단조", "heat_treat": "열처리", "finishing": "마감"}

# NPC 비용 구간 (engine/npcs.py NPC_FEE_BRACKETS)
FEE_BRACKETS = [
    (260, 200, 20),
    (300, 800, 60),
    (385, 2000, 150),
    (470, 5000, 400),
    (10_000, 12000, 1000),
]


def cost_bracket(stat_total: int) -> tuple[int, int]:
    for cap, hire, fee in FEE_BRACKETS:
        if stat_total <= cap:
            return hire, fee
    return FEE_BRACKETS[-1][1], FEE_BRACKETS[-1][2]


def roll_npc_stat() -> int:
    """engine/npcs.py _roll_npc_stat: 3d6*5 cap 75, -10, 하한 10 → 10~65."""
    return max(10, min(sum(random.randint(1, 6) for _ in range(3)) * 5, 75) - 10)


def make_npc() -> dict:
    """engine/npcs.py generate_candidate_payload 동일 분포 (DB 없이)."""
    stats = {k: roll_npc_stat() for k in STAT_NAMES}
    skills = {
        "smelting": random.randint(5, 12),
        "forging": random.randint(5, 15),
        "heat_treat": random.randint(5, 12),
        "finishing": random.randint(0, 7),
        "talent_management": 10,
    }
    raw_iron = random.randint(5, 20)  # 생철광 숙련 (기초 광석 보장)
    stat_total = sum(stats.values())
    hire, fee = cost_bracket(stat_total)
    return {
        "name": random_name(),
        "stats": stats,
        "skills": skills,
        "raw_iron": raw_iron,
        "stat_total": stat_total,
        "hire": hire,
        "fee": fee,
    }


_FAM = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임"]
_GIV = ["건우", "재현", "민호", "성훈", "지훈", "도윤", "현우", "정현", "수민", "지호"]


def random_name() -> str:
    return random.choice(_FAM) + random.choice(_GIV)


def run_scenario(npc: dict, quality: int, grow: bool) -> dict:
    """한 NPC가 입력등급 quality 생철광 주괴로 단검을 RUNS회 제작. grow=True면 성장 누적."""
    stats = dict(npc["stats"])
    skills = dict(npc["skills"])
    raw_iron = npc["raw_iron"]
    exp_stat: dict = defaultdict(int)
    exp_skill: dict = defaultdict(int)
    exp_mat = 0
    quality_bonus = max(0, quality - 1)

    qcounter: Counter = Counter()
    injuries = 0

    for _ in range(RUNS):
        character = {
            "luck": stats["luck"],
            "health": stats["health"],
            "strength": stats["strength"],
            "intelligence": stats["intelligence"],
        }
        flags = get_milestone_flags(raw_iron)
        body = blacksmith.process_blacksmith_command(
            character=character,
            steps=STEPS_INGOT,
            skills=skills,
            mat_proficiency=raw_iron,
            prereq_bonus=0,  # 생철광은 선행소재 없음
            is_injured=False,  # 회복 상태에서 시작 (부상 비지속 가정)
            mat_bonus_dice=flags["bonus_dice"],
            mat_fumble_safe=flags["fumble_safe"],
            rerolls_remaining=0,  # NPC 단독 제작 — 본인 캐릭터 인재관리 재굴림은 발주 경로(여기선 0)
            penalty_modifier=0,
            quality_bonus=quality_bonus,
        )
        if body["is_injured"]:
            injuries += 1
        else:
            qcounter[body["quality"]] += 1

        if not grow:
            continue

        # ── 성장: exp 누적 (game engine/batch.py _process_blacksmith_commands) ──
        mf = body.get("mat_fumble_count", 0)
        if mf:
            raw_iron = max(0, raw_iron - mf)  # 소재 대실패 즉시 숙련 차감
        if body["has_mat_failure"] and raw_iron < 95:
            exp_mat += 1
        for sk in body["failed_craft_skills"]:
            if skills.get(sk, 0) > 0 and skills[sk] < 95:  # 0 스킬은 누적 안 함
                exp_skill[sk] += 1
        for step_r in body["process_results"]:
            st = step_r.get("stat_trigger")
            if st and st["level"] in ("실패", "대실패") and stats.get(st["stat_name"], 0) < 95:
                exp_stat[st["stat_name"]] += 1
            for layer in ("craft", "material"):
                safety = (step_r.get(layer) or {}).get("safety")
                if not safety:
                    continue
                if safety.get("downgraded") and stats["luck"] < 95:
                    exp_stat["luck"] += 1
                if safety.get("is_injured") and stats["health"] < 95:
                    exp_stat["health"] += 1

        # ── 성장: 필요 exp 도달 row value+1, exp 0 (game _apply_growth_due) ──
        for sname in list(exp_stat.keys()):
            if dice.is_growth_due(stats.get(sname, 0), exp_stat[sname]):
                stats[sname] += 1
                exp_stat[sname] = 0
        for sk in CRAFT_SKILLS:  # 저값<7 자연 상승 포함 (게임 코드 그대로)
            if dice.is_growth_due(skills.get(sk, 0), exp_skill[sk]):
                skills[sk] += 1
                exp_skill[sk] = 0
        if dice.is_growth_due(raw_iron, exp_mat):
            raw_iron += 1
            exp_mat = 0

    completed = sum(qcounter.values())
    mean_q = sum(q * c for q, c in qcounter.items()) / completed if completed else 0
    return {
        "qcounter": qcounter,
        "completed": completed,
        "injuries": injuries,
        "mean_q": mean_q,
        "end_skills": {sk: skills[sk] for sk in CRAFT_SKILLS},
        "end_raw_iron": raw_iron,
        "end_luck": stats["luck"],
        "end_health": stats["health"],
    }


def fmt_dist(qcounter: Counter, completed: int) -> str:
    parts = []
    for q in range(1, 6):
        cnt = qcounter.get(q, 0)
        pct = (cnt / completed * 100) if completed else 0
        parts.append(f"{q}등급 {pct:4.1f}%")
    return " ".join(parts)


def main() -> None:
    random.seed(SEED)
    print("=" * 78)
    print(f"주괴(생철광)→단검 제작 시뮬레이션 — 각 품질 {RUNS:,}회 × NPC 3명 × 성장/스킵")
    print("=" * 78)
    print("품질 보너스: 입력등급 Q → 완성품 초기 total 시드 +max(0,Q-1)  (Q1=+0 … Q5=+4)")
    print("등급 환산(blacksmith._quality_grade): total>=5→5등급 / >=2→4 / >=-1→3 / >=-4→2 / 그외→1")
    print(
        "공정: 단조→열처리→마감(주괴 3공정). 성장: exp누적+is_growth_due(c//7)+95컷, 대실패시 소재숙련-1."
    )
    print(
        "[가정] 각 제작 회복상태 시작(부상 비지속)·부상제작=결과물 없음(별도집계)·성장은 제작마다 1회.\n"
    )

    npcs = [make_npc() for _ in range(3)]

    for i, npc in enumerate(npcs, 1):
        s = npc["stats"]
        print("─" * 78)
        statline = " ".join(f"{STAT_KR[k]}{s[k]}" for k in STAT_NAMES)
        print(
            f"NPC {i}: {npc['name']}  |  {statline}  (합 {npc['stat_total']}, 영입 {npc['hire']}/수수료 {npc['fee']})"
        )
        sk = npc["skills"]
        print(
            f"  초기 기술: 단조 {sk['forging']} / 열처리 {sk['heat_treat']} / 마감 {sk['finishing']}"
            f"  |  생철광 숙련 {npc['raw_iron']}"
        )

        print("\n  [성장 스킵 — 고정 능력으로 1000회]")
        print("  품질 | 평균등급 | 분포(완성품 기준)                            | 부상%")
        for q in range(1, 6):
            r = run_scenario(npc, q, grow=False)
            print(
                f"   Q{q}  |  {r['mean_q']:.2f}   | {fmt_dist(r['qcounter'], r['completed'])} "
                f"| {r['injuries'] / RUNS * 100:4.1f}%"
            )

        print("\n  [성장 정상 — 1000회 누적 성장]")
        print(
            "  품질 | 평균등급 | 분포(완성품 기준)                            | 부상% | 종료 기술(단조/열처리/마감/숙련)"
        )
        for q in range(1, 6):
            r = run_scenario(npc, q, grow=True)
            es = r["end_skills"]
            print(
                f"   Q{q}  |  {r['mean_q']:.2f}   | {fmt_dist(r['qcounter'], r['completed'])} "
                f"| {r['injuries'] / RUNS * 100:4.1f}% | {es['forging']}/{es['heat_treat']}/{es['finishing']}/{r['end_raw_iron']}"
            )
        print()


if __name__ == "__main__":
    main()
