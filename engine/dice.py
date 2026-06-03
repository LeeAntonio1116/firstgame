import random

QUALITY_POINTS = {
    "대성공": 3,
    "극단적_성공": 2,
    "어려운_성공": 1,
    "일반_성공": 0,
    "실패": -1,
    "대실패": -2,
}


def roll_d100(bonus_dice: int = 0) -> int:
    """d100 판정. bonus_dice > 0 이면 10의 자리 주사위를 (bonus_dice+1)개 굴려 가장 낮은 값 사용."""
    ones = random.randint(0, 9)
    tens_rolls = [random.randint(0, 9) for _ in range(1 + abs(bonus_dice))]
    tens = min(tens_rolls) if bonus_dice > 0 else tens_rolls[0]
    result = tens * 10 + ones
    return 100 if result == 0 else result


def get_success_level(roll: int, skill: int, fumble_safe: bool = False) -> str:
    if roll == 1:
        return "대성공"
    fumble_min = 100 if fumble_safe else (96 if skill < 50 else 100)
    if roll >= fumble_min:
        return "대실패"
    if roll <= max(1, skill // 5):
        return "극단적_성공"
    if roll <= max(1, skill // 2):
        return "어려운_성공"
    if roll <= skill:
        return "일반_성공"
    return "실패"


def get_quality_points(level: str) -> int:
    return QUALITY_POINTS[level]


def fumble_safety_check(luck: int, health: int) -> dict:
    luck_roll = roll_d100()
    if luck_roll <= luck:
        return {
            "luck_roll": luck_roll,
            "health_roll": None,
            "is_injured": False,
            "downgraded": True,
        }
    health_roll = roll_d100()
    is_injured = health_roll > health
    return {
        "luck_roll": luck_roll,
        "health_roll": health_roll,
        "is_injured": is_injured,
        "downgraded": False,
    }


def growth_check(current_proficiency: int) -> bool:
    """[Legacy P5 이하] 옛 즉시 +1 모델. P6+에서는 미사용 — `is_growth_due` 사용."""
    return roll_d100() > current_proficiency


# ── P6 경험치 누적 성장 모델 (2026-05-28 사용자 결정 / 2026-05-29 계수 조정) ─────────
# - 필요 경험치 = floor(current_value / GROWTH_EXP_DENOMINATOR)
#   2026-05-29: 분모 10 → 7 (전 구간 ~1.44배 감속). 시뮬 검증: 시작 30 → 95 = 549 trigger (274일)
#   사유: 옛 즉시 모델(growth_check)보다 전체적으로 느리게 하려던 원 의도 정합 + 95 도달 보장 유지
# - 실패 판정 시 exp +=1 누적 (호출 측에서 DB 갱신)
# - 다음 배치 시작 시점에 exp >= 필요 경험치 row 모두 value +=1, exp 0 리셋
# - 95 이상 row는 누적·성장 둘 다 봉쇄 (95 컷)
# - 단일 출처: wiki [[캐릭터_스탯_성장]] § 경험치 시스템 (공식 c//7 정정 의뢰 — RAW 2026-05-29)

GROWTH_EXP_DENOMINATOR = 7  # 필요 경험치 = floor(current / 7). 성장 속도 튜닝 시 이 값만 변경


def required_exp_for(current_value: int) -> int:
    """필요 경험치 = floor(current / GROWTH_EXP_DENOMINATOR). 95 이상이면 -1 (성장 봉쇄 표시)."""
    if current_value >= 95:
        return -1
    return current_value // GROWTH_EXP_DENOMINATOR


def is_growth_due(current_value: int, exp_value: int) -> bool:
    """필요 경험치 도달 여부. 95 이상은 항상 False."""
    if current_value >= 95:
        return False
    return exp_value >= (current_value // GROWTH_EXP_DENOMINATOR)


def first_learn_check(intelligence: int) -> bool:
    """0 → 1 진입 시 지략 d100 판정. d100 ≤ 지략이면 첫 학습 성공."""
    return roll_d100() <= intelligence


# ── P6 S2-B 재굴림 시스템 (2026-05-28) — 2026-05-31 통솔 stat → 인재관리 skill 전환 ─────────
# 단일 출처: wiki [[통솔_재굴림_시스템]] (재굴림 메커니즘) · [[인재관리_스킬_전환]] (판정 주체 stat→skill)
# - 트리거: NPC 명령 발주 시 (routers/command.py 3 라우트)
# - 판정 주체: 비파견(대장간·거래) = 지시자 본인 캐릭터의 인재관리 스킬 / 파견 = 각 팀 대장 (P7+)
# - 부상 페널티 -20 (매력 -20 패턴 확장)
# - 결과별: 대성공 → 재굴림 2개 / 극단 → 1개 / 대실패 → -3 페널티
# - exp 누적: 실패·대실패 (feedback-growth-failure-only 룰)


def talent_management_check(skill_value: int, injured: bool = False) -> dict:
    """NPC 명령 발주 시 인재관리 스킬 d100. 결과별 재굴림 토큰·페널티 반환.

    메커니즘은 입력값에 무관(값-agnostic) — 호출 측이 어떤 값(인재관리 스킬)을 넘길지 결정한다.
    반환:
        roll (int), level (str), effective_skill (int),
        rerolls_granted (int): 대성공 2 / 극단 1 / 그 외 0,
        penalty_modifier (int): 대실패 -3 / 그 외 0,
        exp_accumulated (bool): 실패·대실패 시 True (호출 측에서 exp +1 처리).
    """
    effective = max(0, skill_value - 20) if injured else skill_value
    roll = roll_d100()
    level = get_success_level(roll, effective, fumble_safe=False)
    rerolls = 0
    penalty = 0
    if level == "대성공":
        rerolls = 2
    elif level == "극단적_성공":
        rerolls = 1
    elif level == "대실패":
        penalty = -3
    return {
        "roll": roll,
        "level": level,
        "effective_skill": effective,
        "rerolls_granted": rerolls,
        "penalty_modifier": penalty,
        "exp_accumulated": level in ("실패", "대실패"),
    }


def reroll_d100(first_roll: int) -> int:
    """재굴림 d100 1회. 더 좋은 결과(낮은 값) 채택. wiki "min(roll1, roll2)".
    (wiki 초안에는 "더 높은 값"으로 박혔으나 d100 시스템(낮은 roll = 성공)과 모순 — 사용자 결정으로 정정 예정)
    """
    second = roll_d100()
    return min(first_roll, second)
