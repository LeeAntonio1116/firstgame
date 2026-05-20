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
    if bonus_dice > 0:
        tens = min(tens_rolls)
    else:
        tens = tens_rolls[0]
    result = tens * 10 + ones
    return 100 if result == 0 else result


def get_success_level(roll: int, skill: int, fumble_safe: bool = False) -> str:
    if roll == 1:
        return "대성공"
    if fumble_safe:
        fumble_min = 100
    else:
        fumble_min = 96 if skill < 50 else 100
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
        return {"luck_roll": luck_roll, "health_roll": None, "is_injured": False, "downgraded": True}
    health_roll = roll_d100()
    is_injured = health_roll > health
    return {"luck_roll": luck_roll, "health_roll": health_roll, "is_injured": is_injured, "downgraded": False}


def growth_check(current_proficiency: int) -> bool:
    """소재 숙련도 성장 판정. 실패 후 d100 > 현재 숙련도면 True."""
    return roll_d100() > current_proficiency
