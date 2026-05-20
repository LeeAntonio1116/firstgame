from engine import dice


def _quality_grade(total: int) -> int:
    if total >= 5: return 5
    if total >= 2: return 4
    if total >= -1: return 3
    if total >= -4: return 2
    return 1


INJURY_PENALTY = 20  # 부상 중인 캐릭터의 모든 판정에 적용 (공정·소재 양쪽 skill에서 차감)


def process_blacksmith_command(
    character: dict,
    steps: list,
    skills: dict,
    mat_proficiency: int,
    prereq_bonus: int,
    is_injured: bool = False,
    mat_bonus_dice: int = 0,
    mat_fumble_safe: bool = False,
) -> dict:
    luck = character["luck"]
    health = character["health"]
    results = []
    total = 0
    is_injured_new = False  # 이번 작업에서 새로 부상 발생
    has_mat_failure = False  # 소재 판정 일반 실패 발생 여부 (성장 판정 트리거)
    failed_craft_skills: set = set()  # 공정 판정 일반 실패가 난 skill_name 집합 (배치당 skill별 1회 성장 판정)
    penalty = INJURY_PENALTY if is_injured else 0
    mat_skill = mat_proficiency + prereq_bonus - penalty

    for step in steps:
        skill_name = step["skill_name"]
        craft_skill = skills.get(skill_name, 0) - penalty

        # ① 제작공정 판정
        craft_roll = dice.roll_d100()
        craft_level = dice.get_success_level(craft_roll, craft_skill)
        craft_points = dice.get_quality_points(craft_level)

        craft_safety = None
        if craft_level == "대실패":
            craft_safety = dice.fumble_safety_check(luck, health)
            if craft_safety["is_injured"]:
                is_injured_new = True
                results.append({
                    "step": step["name"],
                    "craft": {"roll": craft_roll, "skill": craft_skill, "level": craft_level, "points": craft_points, "safety": craft_safety},
                    "material": None,
                })
                break
            if craft_safety["downgraded"]:
                craft_level = "실패"
                craft_points = -1

        if craft_level == "실패":
            failed_craft_skills.add(skill_name)

        # ② 소재 숙련도 판정
        mat_roll = dice.roll_d100(bonus_dice=mat_bonus_dice)
        mat_level = dice.get_success_level(mat_roll, mat_skill, fumble_safe=mat_fumble_safe)
        mat_points = dice.get_quality_points(mat_level)

        mat_safety = None
        if mat_level == "대실패":
            mat_safety = dice.fumble_safety_check(luck, health)
            if mat_safety["is_injured"]:
                is_injured_new = True
                results.append({
                    "step": step["name"],
                    "craft": {"roll": craft_roll, "skill": craft_skill, "level": craft_level, "points": craft_points, "safety": craft_safety},
                    "material": {"roll": mat_roll, "skill": mat_skill, "level": mat_level, "points": mat_points, "safety": mat_safety},
                })
                break
            if mat_safety["downgraded"]:
                mat_level = "실패"
                mat_points = -1

        if mat_level == "실패":
            has_mat_failure = True

        step_points = craft_points + mat_points
        total += step_points
        results.append({
            "step": step["name"],
            "craft": {"roll": craft_roll, "skill": craft_skill, "level": craft_level, "points": craft_points, "safety": craft_safety},
            "material": {"roll": mat_roll, "skill": mat_skill, "level": mat_level, "points": mat_points, "safety": mat_safety},
            "step_points": step_points,
        })

    return {
        "process_results": results,
        "total_points": total,
        "quality": _quality_grade(total),
        "is_injured": is_injured_new,  # 이번 작업에서 새로 부상 발생 여부
        "cascade": is_injured and is_injured_new,  # 부상 중에 또 부상 트리거 발생
        "has_mat_failure": has_mat_failure,
        "failed_craft_skills": sorted(failed_craft_skills),
    }
