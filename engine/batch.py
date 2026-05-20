from datetime import datetime, timezone
from database import db_select, db_insert, db_update
from engine import blacksmith, dice
from engine.materials import PREREQUISITES, STEPS_ORE, STEPS_INGOT, get_prerequisite_bonus, get_milestone_flags
from engine.items import STACK_LIMITS, DEFAULT_STACK_LIMIT


def _get_mat_proficiency(character_id: str, material_type: str) -> int:
    rows = db_select("material_proficiency", character_id=character_id, material_type=material_type)
    return rows[0]["value"] if rows else 0


def _get_character_skills(character_id: str) -> dict:
    rows = db_select("character_skills", character_id=character_id)
    return {row["skill_name"]: row["value"] for row in rows}


def _save_item(owner_id: str, batch_id: str, item_type: str, material: str, quality: int, process_log: list) -> None:
    """items 테이블 stack 저장. (owner, type, material, quality) 동일 시 quantity++,
    stack 상한 초과 시 새 row 생성."""
    existing = db_select("items", owner_id=owner_id, item_type=item_type, material=material, quality=quality)
    limit = STACK_LIMITS.get(item_type, DEFAULT_STACK_LIMIT)
    if existing and existing[0]["quantity"] < limit:
        db_update("items", {"quantity": existing[0]["quantity"] + 1}, id=existing[0]["id"])
    else:
        db_insert("items", {
            "owner_id": owner_id,
            "item_type": item_type,
            "material": material,
            "quality": quality,
            "quantity": 1,
            "batch_id": batch_id,
            "process_log": process_log,
        })


def _process_recovery(batch_id: str, cmd_char_ids: set) -> None:
    """배치 시작 시 부상·중상 회복 처리.
    - 부상: 이번 배치에 명령 미제출(cmd_char_ids에 없음) → 자동 회복
    - 중상: serious_injury_remaining 카운트다운, 0이 되면 회복
    """
    # 일반 부상 회복 (중상 아닌 부상)
    injured = db_select("characters", is_injured=True, is_serious_injured=False)
    for char in injured:
        if char["id"] in cmd_char_ids:
            continue
        db_update("characters", {"is_injured": False}, id=char["id"])
        db_insert("mailbox", {
            "character_id": char["id"], "command_id": None, "batch_id": batch_id,
            "title": "부상 회복", "body": {"type": "injury_recovery"},
        })

    # 중상 카운트다운
    serious = db_select("characters", is_serious_injured=True)
    for char in serious:
        remaining = char.get("serious_injury_remaining", 0) - 1
        if remaining <= 0:
            db_update("characters", {
                "is_serious_injured": False, "is_injured": False, "serious_injury_remaining": 0,
            }, id=char["id"])
            db_insert("mailbox", {
                "character_id": char["id"], "command_id": None, "batch_id": batch_id,
                "title": "중상 회복", "body": {"type": "serious_recovery"},
            })
        else:
            db_update("characters", {"serious_injury_remaining": remaining}, id=char["id"])


def run_batch() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    batch = db_insert("batches", {"scheduled_at": now, "status": "running"})
    batch_id = batch["id"]

    commands = db_select("commands", status="pending")
    cmd_char_ids = {cmd["character_id"] for cmd in commands}
    _process_recovery(batch_id, cmd_char_ids)

    if not commands:
        db_update("batches", {"status": "done", "processed_at": now}, id=batch_id)
        return {"batch_id": batch_id, "processed_count": 0, "results": []}

    char_cache: dict = {}
    skills_cache: dict = {}
    for cmd in commands:
        cid = cmd["character_id"]
        if cid not in char_cache:
            rows = db_select("characters", id=cid)
            char_cache[cid] = rows[0] if rows else None
            skills_cache[cid] = _get_character_skills(cid)

    pairs = [(cmd, char_cache[cmd["character_id"]]) for cmd in commands if char_cache.get(cmd["character_id"])]
    pairs.sort(key=lambda x: x[1]["leadership"], reverse=True)

    results = []
    for cmd, char in pairs:
        material = cmd.get("target_material", "raw_iron")
        input_type = cmd.get("input_type", "ore")

        # 소재 숙련도 + 선행 보너스
        mat_prof = _get_mat_proficiency(char["id"], material)
        prereq = PREREQUISITES.get(material)
        prereq_prof = _get_mat_proficiency(char["id"], prereq) if prereq else 0
        prereq_bonus = get_prerequisite_bonus(prereq_prof)

        # 마일스톤 플래그
        flags = get_milestone_flags(mat_prof)

        # input_type에 따라 공정 선택
        steps = STEPS_ORE if input_type == "ore" else STEPS_INGOT

        skills = skills_cache[char["id"]]
        body = blacksmith.process_blacksmith_command(
            character=char,
            steps=steps,
            skills=skills,
            mat_proficiency=mat_prof,
            prereq_bonus=prereq_bonus,
            is_injured=char.get("is_injured", False),
            mat_bonus_dice=flags["bonus_dice"],
            mat_fumble_safe=flags["fumble_safe"],
        )

        # 소재 숙련도 성장 판정 (일반 실패 발생 시, 배치당 1회)
        material_growth = None
        if body["has_mat_failure"] and mat_prof > 0:
            success = dice.growth_check(mat_prof)
            new_mat_value = mat_prof + 1 if success else mat_prof
            if success:
                db_update(
                    "material_proficiency",
                    {"value": new_mat_value},
                    character_id=char["id"],
                    material_type=material,
                )
            material_growth = {
                "name": material, "before": mat_prof, "after": new_mat_value, "success": success,
            }

        # 기술치 성장 판정 (공정 일반 실패 발생한 skill별 1회)
        skill_growth = []
        for skill_name in body["failed_craft_skills"]:
            current = skills.get(skill_name, 0)
            if current <= 0:
                continue
            success = dice.growth_check(current)
            new_value = current + 1 if success else current
            if success:
                db_update(
                    "character_skills",
                    {"value": new_value},
                    character_id=char["id"],
                    skill_name=skill_name,
                )
                skills[skill_name] = new_value
            skill_growth.append({
                "name": skill_name, "before": current, "after": new_value, "success": success,
            })

        body["growth_log"] = {"material": material_growth, "skills": skill_growth}

        # 부상 / 중상 DB 저장
        if body["cascade"]:
            # 부상 중 또 부상 트리거 → 중상 (2배치 행동 불능)
            db_update("characters", {
                "is_serious_injured": True,
                "serious_injury_remaining": 2,
                "is_injured": True,
            }, id=char["id"])
            char["is_serious_injured"] = True  # cache 갱신 (이번 run 안에서 더 쓰진 않지만 일관성)
        elif body["is_injured"]:
            db_update("characters", {"is_injured": True}, id=char["id"])
            char["is_injured"] = True

        if body["cascade"]:
            title = "⚠ 대장간 작업 — 중상 발생 (2배치 행동 불능)"
        elif body["is_injured"]:
            title = "⚠ 대장간 작업 — 부상 발생"
        else:
            title = f"대장간 작업 — 품질 {body['quality']}등급 완성"
            # 작업 정상 완료 → items 저장 (P1 단계: 광석 입력만 → ingot 결과)
            if input_type == "ore":
                _save_item(
                    owner_id=char["id"],
                    batch_id=batch_id,
                    item_type="ingot",
                    material=material,
                    quality=body["quality"],
                    process_log=body["process_results"],
                )
        db_insert("mailbox", {
            "character_id": char["id"],
            "command_id": cmd["id"],
            "batch_id": batch_id,
            "title": title,
            "body": body,
        })
        db_update("commands", {"status": "done", "batch_id": batch_id}, id=cmd["id"])
        results.append({"command_id": cmd["id"], "character": char["name"], "quality": body["quality"]})

    db_update("batches", {"status": "done", "processed_at": datetime.now(timezone.utc).isoformat()}, id=batch_id)
    return {"batch_id": batch_id, "processed_count": len(results), "results": results}
