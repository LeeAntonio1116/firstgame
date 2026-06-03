from engine import dice


def _quality_grade(total: int) -> int:
    if total >= 5:
        return 5
    if total >= 2:
        return 4
    if total >= -1:
        return 3
    if total >= -4:
        return 2
    return 1


INJURY_PENALTY = 20  # 부상 중인 캐릭터의 모든 판정에 적용 (공정·소재 양쪽 skill에서 차감)

# P6 (2026-05-28): 공정별 별도 스탯 d100 트리거 — craft skill 판정과 독립.
# 실패 시 해당 스탯 exp +1 (성장 속도 조절 — 미래 파견·농사·공방 등 다른 작업 도입 시 과성장 방지).
# 적용 공정: 단조=무력 / 열처리=지략. 부상 페널티 -20 동일 적용.
STAT_TRIGGER_MAP = {
    "forging": "strength",
    "heat_treat": "intelligence",
}


def process_blacksmith_command(
    character: dict,
    steps: list,
    skills: dict,
    mat_proficiency: int,
    prereq_bonus: int,
    is_injured: bool = False,
    mat_bonus_dice: int = 0,
    mat_fumble_safe: bool = False,
    rerolls_remaining: int = 0,
    penalty_modifier: int = 0,
    quality_bonus: int = 0,
) -> dict:
    """P6 S2-B / S2-B v2: 통솔 재굴림 시스템.
    - quality_bonus (재료 품질 보너스, 2026-06-01): total **시작값**에 가산.
      `bonus = max(0, 입력재료등급 - 1)` (배치에서 계산해 전달). 공정 d100 누적 전 시드라,
      공정 실패가 누적되면 보너스가 상쇄·역전될 수 있음("좋은 재료 + 나쁜 솜씨 = 망침").
      default 0 → 광석 입력·기존 호출·sim 스크립트 하위호환.
    - penalty_modifier (음수 -3 등): craft·material·stat_trigger 모든 skill에 더해짐
    - rerolls_remaining 사용 순서:
      ① step loop 중 **대실패 즉시** 재굴림 (안전망 가기 전, 라* 그리디)
      ② step loop 정상 종료 후 **일반 실패 후처리** (S2-B v2):
         1순위 = 남은 대실패, 2순위 = 실패 중 max(현재 skill), 같으면 step 순서
         재굴림 후 step_points·total·quality·has_mat_failure·failed_craft_skills 재계산
      stat_trigger는 재굴림 X (성장 트리거 보호).
    - 부상 break 시 후처리 X (이미 끝난 명령).
    """
    luck = character["luck"]
    health = character["health"]
    results = []
    total = quality_bonus  # 재료 품질 보너스를 시작값으로 시드 (공정 d100 점수는 아래서 누적)
    is_injured_new = False  # 이번 작업에서 새로 부상 발생
    has_mat_failure = False  # 소재 판정 일반 실패 발생 여부 (성장 판정 트리거)
    mat_fumble_count = 0  # 소재 대실패 횟수 (안전망 통과/실패 무관, 진입 즉시 카운트)
    failed_craft_skills: set = set()  # 공정 판정 일반 실패가 난 skill_name 집합
    rerolls_used = 0  # 본 호출에서 사용한 재굴림 수
    penalty = INJURY_PENALTY if is_injured else 0
    # penalty_modifier가 음수(-3)면 skill에 그대로 더해 차감 효과
    mat_skill = mat_proficiency + prereq_bonus - penalty + penalty_modifier

    for step in steps:
        skill_name = step["skill_name"]
        craft_skill = skills.get(skill_name, 0) - penalty + penalty_modifier

        # ① 제작공정 판정
        craft_roll = dice.roll_d100()
        craft_level = dice.get_success_level(craft_roll, craft_skill)
        craft_reroll = None

        # P6 S2-B: 대실패 즉시 재굴림 (안전망 가기 전, 라* 그리디)
        if craft_level == "대실패" and rerolls_remaining > 0:
            new_roll = dice.reroll_d100(craft_roll)
            craft_reroll = {"orig_roll": craft_roll, "new_roll": new_roll}
            craft_roll = new_roll
            craft_level = dice.get_success_level(craft_roll, craft_skill)
            rerolls_remaining -= 1
            rerolls_used += 1

        craft_points = dice.get_quality_points(craft_level)

        # ①-bis. P6 공정별 별도 스탯 트리거 d100 (단조=무력, 열처리=지략)
        # craft 판정과 독립 — 결과는 quality에 영향 없음, exp 누적만. 부상·통솔 페널티 적용.
        # 재굴림은 X (성장 트리거라 실패 유지가 캐릭터에게 유리).
        stat_trigger = None
        trig_stat = STAT_TRIGGER_MAP.get(skill_name)
        if trig_stat:
            stat_value = character.get(trig_stat, 0) - penalty + penalty_modifier
            stat_roll = dice.roll_d100()
            stat_level = dice.get_success_level(stat_roll, stat_value)
            stat_trigger = {
                "stat_name": trig_stat,
                "roll": stat_roll,
                "value": stat_value,
                "level": stat_level,
            }

        craft_safety = None
        if craft_level == "대실패":
            craft_safety = dice.fumble_safety_check(luck, health)
            if craft_safety["is_injured"]:
                is_injured_new = True
                results.append(
                    {
                        "step": step["name"],
                        "craft": {
                            "roll": craft_roll,
                            "skill": craft_skill,
                            "level": craft_level,
                            "points": craft_points,
                            "safety": craft_safety,
                            "reroll": craft_reroll,
                        },
                        "material": None,
                        "stat_trigger": stat_trigger,
                    }
                )
                break
            if craft_safety["downgraded"]:
                craft_level = "실패"
                craft_points = -1

        if craft_level == "실패":
            failed_craft_skills.add(skill_name)

        # ② 소재 숙련도 판정
        mat_roll = dice.roll_d100(bonus_dice=mat_bonus_dice)
        mat_level = dice.get_success_level(mat_roll, mat_skill, fumble_safe=mat_fumble_safe)
        mat_reroll = None

        # P6 S2-B: 대실패 즉시 재굴림 (안전망 가기 전)
        if mat_level == "대실패" and rerolls_remaining > 0:
            new_roll = dice.reroll_d100(mat_roll)
            mat_reroll = {"orig_roll": mat_roll, "new_roll": new_roll}
            mat_roll = new_roll
            mat_level = dice.get_success_level(mat_roll, mat_skill, fumble_safe=mat_fumble_safe)
            rerolls_remaining -= 1
            rerolls_used += 1

        mat_points = dice.get_quality_points(mat_level)

        mat_safety = None
        if mat_level == "대실패":
            mat_fumble_count += 1  # 안전망 결과 무관 — 균형형 패널티 적용 대상
            mat_safety = dice.fumble_safety_check(luck, health)
            if mat_safety["is_injured"]:
                is_injured_new = True
                results.append(
                    {
                        "step": step["name"],
                        "craft": {
                            "roll": craft_roll,
                            "skill": craft_skill,
                            "level": craft_level,
                            "points": craft_points,
                            "safety": craft_safety,
                            "reroll": craft_reroll,
                        },
                        "material": {
                            "roll": mat_roll,
                            "skill": mat_skill,
                            "level": mat_level,
                            "points": mat_points,
                            "safety": mat_safety,
                            "reroll": mat_reroll,
                        },
                        "stat_trigger": stat_trigger,
                    }
                )
                break
            if mat_safety["downgraded"]:
                mat_level = "실패"
                mat_points = -1

        if mat_level == "실패":
            has_mat_failure = True

        step_points = craft_points + mat_points
        total += step_points
        results.append(
            {
                "step": step["name"],
                "skill_name": skill_name,  # S2-B v2: 후처리 루프에서 failed_craft_skills 재계산에 사용
                "craft": {
                    "roll": craft_roll,
                    "skill": craft_skill,
                    "level": craft_level,
                    "points": craft_points,
                    "safety": craft_safety,
                    "reroll": craft_reroll,
                },
                "material": {
                    "roll": mat_roll,
                    "skill": mat_skill,
                    "level": mat_level,
                    "points": mat_points,
                    "safety": mat_safety,
                    "reroll": mat_reroll,
                },
                "stat_trigger": stat_trigger,
                "step_points": step_points,
            }
        )

    # P6 S2-B v2: 일반 실패 후처리 재굴림 루프
    # 정상 종료(break 없음) + 토큰 잔량 > 0 일 때만 동작.
    # 우선순위: ① 남은 대실패 (step 순서) → ② 일반 실패 중 max(현재 skill), 같으면 step 순서.
    # 재굴림 후 step_points·total·has_mat_failure·failed_craft_skills 재계산.
    # quality는 mat_fumble_count 기준 동일 (안전망 진입 시점 카운트 — 후처리로 변동 X).
    reroll_log: list = []
    if rerolls_remaining > 0 and not is_injured_new:
        while rerolls_remaining > 0:
            crit_candidates = []  # (step_idx, layer)
            fail_candidates = []  # (step_idx, layer, skill)
            for idx, r in enumerate(results):
                for layer in ("craft", "material"):
                    layer_data = r.get(layer)
                    if not layer_data:
                        continue
                    lvl = layer_data["level"]
                    if lvl == "대실패":
                        crit_candidates.append((idx, layer))
                    elif lvl == "실패":
                        fail_candidates.append((idx, layer, layer_data["skill"]))

            if crit_candidates:
                tgt_idx, tgt_layer = crit_candidates[0]
            elif fail_candidates:
                # max skill 우선, 같으면 step 순서(작은 idx)
                fail_candidates.sort(key=lambda x: (-x[2], x[0]))
                tgt_idx, tgt_layer, _ = fail_candidates[0]
            else:
                break  # 후처리 후보 없음

            layer_data = results[tgt_idx][tgt_layer]
            orig_roll = layer_data["roll"]
            orig_level = layer_data["level"]
            skill_used = layer_data["skill"]
            new_roll = dice.reroll_d100(orig_roll)
            if tgt_layer == "material":
                new_level = dice.get_success_level(
                    new_roll, skill_used, fumble_safe=mat_fumble_safe
                )
            else:
                new_level = dice.get_success_level(new_roll, skill_used)
            new_points = dice.get_quality_points(new_level)

            layer_data["roll"] = new_roll
            layer_data["level"] = new_level
            layer_data["points"] = new_points
            layer_data["reroll"] = {
                "orig_roll": orig_roll,
                "new_roll": new_roll,
                "postprocessed": True,
            }

            reroll_log.append(
                {
                    "step": results[tgt_idx]["step"],
                    "layer": tgt_layer,
                    "orig_roll": orig_roll,
                    "new_roll": new_roll,
                    "orig_level": orig_level,
                    "new_level": new_level,
                    "skill_used": skill_used,
                    "postprocessed": True,
                }
            )
            rerolls_remaining -= 1
            rerolls_used += 1

        # 재계산 — 후처리가 한 번이라도 일어났으면
        if reroll_log:
            total = quality_bonus  # 재시드 — 후처리 재합산에도 재료 품질 보너스 유지
            has_mat_failure = False
            failed_craft_skills = set()
            for r in results:
                craft = r["craft"]
                material = r["material"]
                r["step_points"] = craft["points"] + material["points"]
                total += r["step_points"]
                if craft["level"] == "실패":
                    failed_craft_skills.add(r["skill_name"])
                if material["level"] == "실패":
                    has_mat_failure = True

    return {
        "process_results": results,
        "total_points": total,
        "quality": max(
            1, _quality_grade(total) - mat_fumble_count
        ),  # 균형형: 소재 대실패 1회당 quality -1 (후처리 무관 — 안전망 진입 시점 카운트)
        "is_injured": is_injured_new,
        "cascade": is_injured and is_injured_new,
        "quality_bonus": quality_bonus,  # 재료 품질 보너스 (예측·결과 메일 분해 표시용)
        "has_mat_failure": has_mat_failure,
        "mat_fumble_count": mat_fumble_count,
        "failed_craft_skills": sorted(failed_craft_skills),
        "rerolls_used": rerolls_used,
        "rerolls_remaining": rerolls_remaining,
        "penalty_modifier": penalty_modifier,
        "reroll_log": reroll_log,  # S2-B v2: 후처리 재굴림 로그 ({step,layer,orig_roll,new_roll,orig_level,new_level,skill_used,postprocessed})
    }
