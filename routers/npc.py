"""P5 NPC 고용·해고 라우트.

매력 판정: engine/dice.py roll_d100 + get_success_level. char.charisma 를 skill로 사용.
일반_성공 이상 → 합격. 영입금 차감 + npcs INSERT + npc_skills/npc_material_proficiency 시드.
실패 → 비용 차감 없음, 후보는 풀에 잔존 (재시도 가능).
"""

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from database import adjust_gold, db_delete, db_insert, db_select, db_update, release_npc_fee
from engine import dice
from engine.batch import _accumulate_exp
from engine.npcs import NPC_TALENT_MANAGEMENT_INIT
from routers.auth import get_current_user
from routers.command import _refund_command_assets, _refund_item_row

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/npc")

_PASS_LEVELS = {"일반_성공", "어려운_성공", "극단적_성공", "대성공"}
FUMBLE_REMOVAL_THRESHOLD = 3  # 누적 대실패 N회 도달 시 후보 제거
FUMBLE_COST_STEP = 0.10  # 대실패당 영입금 +10%
CRIT_HIRE_DISCOUNT = 0.10  # 대성공 시 영입금 -10%
CRIT_FEE_DISCOUNT = 0.10  # 대성공 시 수수료 영구 -10%
EXTREME_HIRE_DISCOUNT = 0.03  # 극단적_성공 시 영입금 -3% (수수료 영향 없음)


@router.post("/hire")
async def hire_npc(request: Request, candidate_id: str = Form(...)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    cand_rows = db_select("npc_candidates", id=candidate_id)
    if not cand_rows:
        return RedirectResponse("/dashboard#employees", status_code=302)
    cand = cand_rows[0]
    if cand.get("user_id") != user["sub"]:
        return RedirectResponse("/dashboard#employees", status_code=302)

    # 본인 캐릭터 — 매력 판정 주체
    chars = db_select("characters", user_id=user["sub"])
    if not chars:
        return RedirectResponse("/dashboard#employees", status_code=302)
    char = chars[0]
    if char.get("is_serious_injured"):
        return RedirectResponse("/dashboard#employees", status_code=302)

    # 자금 검증
    user_rows = db_select("users", id=user["sub"])
    if not user_rows:
        return RedirectResponse("/login", status_code=302)
    cur_gold = int(user_rows[0].get("gold") or 0)
    hire_cost = int(cand.get("hire_cost") or 0)
    if cur_gold < hire_cost:
        return RedirectResponse("/dashboard#employees", status_code=302)

    # 매력 d100 + charisma 판정 (기존 시스템 재사용). 부상 시 -20 페널티.
    charisma = int(char.get("charisma") or 0)
    effective = max(0, charisma - 20) if char.get("is_injured") else charisma
    roll = dice.roll_d100()
    level = dice.get_success_level(roll, effective, fumble_safe=False)

    # P6: 매력 판정 실패 시 charisma exp 누적 (대실패·일반 실패 양쪽)
    char_with_kind = {**char, "_kind": "character"}
    if level in ("실패", "대실패"):
        _accumulate_exp(char_with_kind, "stat", "charisma")

    # ── 대실패 분기 ────────────────────────────────────────
    if level == "대실패":
        base_cost = int(cand.get("base_hire_cost") or cand.get("hire_cost") or 0)
        new_count = int(cand.get("fumble_count") or 0) + 1
        if new_count >= FUMBLE_REMOVAL_THRESHOLD:
            db_delete("npc_candidates", id=candidate_id)
            title = f"💥 고용 대실패 — {cand.get('name')} 후보가 떠남"
            body_extra = {
                "penalty": "removed",
                "fumble_count": new_count,
                "removal_threshold": FUMBLE_REMOVAL_THRESHOLD,
            }
        else:
            new_hire = int(base_cost * (1 + FUMBLE_COST_STEP * new_count))
            db_update(
                "npc_candidates",
                {"fumble_count": new_count, "hire_cost": new_hire},
                id=candidate_id,
            )
            title = (
                f"💥 고용 대실패 — {cand.get('name')} (영입금 +{int(FUMBLE_COST_STEP * new_count * 100)}%, "
                f"누적 {new_count}/{FUMBLE_REMOVAL_THRESHOLD - 1})"
            )
            body_extra = {
                "penalty": "cost_up",
                "fumble_count": new_count,
                "base_hire_cost": base_cost,
                "new_hire_cost": new_hire,
                "removal_threshold": FUMBLE_REMOVAL_THRESHOLD,
            }
        db_insert(
            "mailbox",
            {
                "character_id": char["id"],
                "command_id": None,
                "batch_id": None,
                "title": title,
                "body": {
                    "type": "npc_hire",
                    "result": "critical_fail",
                    "character_name": char.get("name"),
                    "candidate_name": cand.get("name"),
                    "charisma": charisma,
                    "roll": roll,
                    "level": level,
                    "hire_cost": hire_cost,
                    **body_extra,
                },
            },
        )
        return RedirectResponse("/dashboard#employees", status_code=302)

    # ── 일반 실패 분기 ─────────────────────────────────────
    if level not in _PASS_LEVELS:
        db_insert(
            "mailbox",
            {
                "character_id": char["id"],
                "command_id": None,
                "batch_id": None,
                "title": f"고용 실패 — {cand.get('name')} 영입 거절 (판정: {level})",
                "body": {
                    "type": "npc_hire",
                    "result": "failed",
                    "character_name": char.get("name"),
                    "candidate_name": cand.get("name"),
                    "charisma": charisma,
                    "roll": roll,
                    "level": level,
                    "hire_cost": hire_cost,
                },
            },
        )
        return RedirectResponse("/dashboard#employees", status_code=302)

    # ── 합격 분기 (대성공 / 극단적_성공 / 그 외 보너스 분리) ──
    is_crit = level == "대성공"
    is_extreme = level == "극단적_성공"
    base_fee = int(cand.get("fee") or 0)
    if is_crit:
        final_hire = int(hire_cost * (1 - CRIT_HIRE_DISCOUNT))
        final_fee = int(base_fee * (1 - CRIT_FEE_DISCOUNT))
    elif is_extreme:
        final_hire = int(hire_cost * (1 - EXTREME_HIRE_DISCOUNT))
        final_fee = base_fee
    else:
        final_hire = hire_cost
        final_fee = base_fee

    # A-1: 영입금 원자 차감 (검증~차감 사이 잔액 변동 레이스 방지). 부족이면 NPC 생성 중단.
    if adjust_gold(user["sub"], -final_hire) is None:
        return RedirectResponse("/dashboard#employees", status_code=302)
    stats = cand.get("stats") or {}
    stamina_max = (int(stats.get("health") or 0)) // 5
    new_npc = db_insert(
        "npcs",
        {
            "owner_id": user["sub"],
            "name": cand.get("name"),
            "npc_type": "장인",
            "strength": int(stats.get("strength") or 0),
            "intelligence": int(stats.get("intelligence") or 0),
            "charisma": int(stats.get("charisma") or 0),
            "health": int(stats.get("health") or 0),
            "luck": int(stats.get("luck") or 0),
            "dexterity": int(stats.get("dexterity") or 0),
            "is_injured": False,
            "is_serious_injured": False,
            "serious_injury_remaining": 0,
            "stamina_current": stamina_max,
            "hire_cost": final_hire,
            "fee_per_batch": final_fee,
        },
    )
    npc_id = new_npc["id"]
    skills = cand.get("skills") or {}
    # 인재관리 보강 — 마이그 전 생성된 stale 후보의 skills JSONB엔 talent_management가 없을 수 있다.
    # 그런 후보를 고용해도 NPC가 인재관리 스킬 row를 갖도록 보장 (적대적 리뷰 #2, 데이터 일관성).
    if "talent_management" not in skills:
        skills = {**skills, "talent_management": NPC_TALENT_MANAGEMENT_INIT}
    for skill_name, val in skills.items():
        db_insert(
            "npc_skills",
            {
                "npc_id": npc_id,
                "skill_name": skill_name,
                "value": int(val or 0),
            },
        )
    proficiency = cand.get("proficiency") or {}
    for mat, val in proficiency.items():
        if int(val or 0) > 0:
            db_insert(
                "npc_material_proficiency",
                {
                    "npc_id": npc_id,
                    "material_type": mat,
                    "value": int(val),
                },
            )
    db_delete("npc_candidates", id=candidate_id)

    if is_crit:
        title = (
            f"🌟 고용 대성공 — {cand.get('name')} 영입 "
            f"({final_hire}량 지급, 할인 -{int(CRIT_HIRE_DISCOUNT * 100)}% / "
            f"수수료 영구 -{int(CRIT_FEE_DISCOUNT * 100)}%)"
        )
        result = "critical_pass"
    elif is_extreme:
        title = (
            f"✨ 고용 성공 — {cand.get('name')} 영입 "
            f"({final_hire}량 지급, 매력 발휘 -{int(EXTREME_HIRE_DISCOUNT * 100)}%)"
        )
        result = "extreme_pass"
    else:
        title = f"고용 성공 — {cand.get('name')} 영입 ({final_hire}량 지급, 판정: {level})"
        result = "passed"
    db_insert(
        "mailbox",
        {
            "character_id": char["id"],
            "command_id": None,
            "batch_id": None,
            "title": title,
            "body": {
                "type": "npc_hire",
                "result": result,
                "character_name": char.get("name"),
                "npc_name": cand.get("name"),
                "npc_id": npc_id,
                "charisma": charisma,
                "roll": roll,
                "level": level,
                "hire_cost": final_hire,
                "original_hire_cost": hire_cost if (is_crit or is_extreme) else None,
                "fee_per_batch": final_fee,
                "original_fee": base_fee if is_crit else None,
            },
        },
    )
    return RedirectResponse("/dashboard#employees", status_code=302)


def _recover_npc_inventory(npc_id: str, user_id: str) -> None:
    """E-2: 해고되는 NPC의 인벤 아이템을 user 공유 창고로 회수 (stack 병합). 고아화 방지."""
    inv_items = db_select("items", owner_id=npc_id, location="inventory")
    for it in inv_items:
        _refund_item_row(
            user_id,
            it["item_type"],
            it["material"],
            int(it.get("quality") or 0),
            int(it.get("quantity") or 0),
            location="warehouse",
        )
        db_delete("items", id=it["id"])


@router.post("/fire")
async def fire_npc(request: Request, npc_id: str = Form(...)):
    """P5 정책: 자유 해고, 영입금(hire_cost)은 환불 안 함.
    단 진행 중(pending) 주문의 예약 자산은 환불(E-1): buy=발주시세 gold / sell=user 창고 복원.
    NPC 인벤 아이템은 user 창고로 회수(E-2), npc_stat_exp는 수동 삭제(FK 없음).
    (mailbox는 이력으로 보존 — character_id FK 없으니 NPC 메일이 그대로 남음)"""
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    npc_rows = db_select("npcs", id=npc_id)
    if not npc_rows or npc_rows[0].get("owner_id") != user["sub"]:
        return RedirectResponse("/dashboard#employees", status_code=302)

    # E-1: pending 주문의 예약 자산 환불 후 cancelled (영입금은 미환불 — 자유 해고 패널티 유지)
    # A-4 패턴(대칭 적용): 명령마다 pending→cancelled 원자 claim 후 이긴 경우에만 환불.
    # 취소·배치(_claim_command)와 동시 발생해도 한 명령은 한 곳만 처리 → 이중환급 차단.
    pending = db_select("commands", character_id=npc_id, status="pending")
    for cmd in pending:
        claimed = db_update("commands", {"status": "cancelled"}, id=cmd["id"], status="pending")
        if not claimed:
            continue  # 배치/사용자 취소가 이미 선점 — 환불하지 않음
        _refund_command_assets(cmd, user["sub"], sell_to="warehouse")
    # F-5: 선불 홀드된 이번 배치 수수료가 있으면 원자 환불 (단일 승자 — 동시 취소/해고에도 1회만)
    # RPC 미존재(404) 시에도 해고는 완료시킨다 — 홀드 RPC가 없었다면 환불할 것도 없음
    # (batch.py _charge_npc_fees settle 격리와 동일 패턴).
    try:
        release_npc_fee(npc_id, user["sub"])
    except Exception:
        logger.exception("해고 시 수수료 환불 실패 npc=%s", npc_id)

    # E-2: NPC 인벤 아이템 user 창고 회수 + npc_stat_exp 청소 (둘 다 FK 없어 자동삭제 안 됨)
    _recover_npc_inventory(npc_id, user["sub"])
    db_delete("npc_stat_exp", npc_id=npc_id)

    # 분리 테이블 (npc_skills, npc_material_proficiency)은 FK CASCADE로 자동 삭제됨.
    db_delete("npcs", id=npc_id)
    return RedirectResponse("/dashboard#employees", status_code=302)
