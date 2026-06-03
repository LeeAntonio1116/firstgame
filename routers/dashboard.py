import asyncio
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import StrictUndefined

from database import db_select_async
from engine.batch import BATCH_HOURS_KST, next_batch_at_iso
from engine.gold import format_gold
from engine.items import (
    CATEGORY_BY_TYPE,
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    ITEM_TYPE_LABELS,
    item_descriptions_for_js,
)
from engine.market import get_current_price
from engine.materials import (
    ALLOY_CODES,
    ALLOY_RECIPES,
    MATERIALS,
    ORE_CODES,
    PREREQUISITES,
    QUALITY_MULTIPLIERS,
    WEAPON_CODES,
    WEAPON_LABELS,
    WEAPON_RECIPES,
    WEAPON_STAMINA_BONUS,
    get_material_status,
    get_prerequisite_bonus,
    get_stamina_cost,
    get_trade_stamina_cost,
    get_weapon_stamina_cost,
)
from routers.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.undefined = StrictUndefined
templates.env.filters["gold"] = format_gold


def _material_dropdown(code: str, mat_proficiency: dict, force_locked: bool = False) -> dict:
    info = MATERIALS[code]
    if force_locked:
        return {
            "code": code,
            "name": info["name"],
            "rarity": info["rarity"],
            "status": "locked",
            "proficiency": 0,
            "prereq_bonus": 0,
        }
    prereq = PREREQUISITES.get(code)
    prereq_bonus = get_prerequisite_bonus(mat_proficiency.get(prereq, 0)) if prereq else 0
    return {
        "code": code,
        "name": info["name"],
        "rarity": info["rarity"],
        "status": get_material_status(code, mat_proficiency),
        "proficiency": mat_proficiency.get(code, 0),
        "prereq_bonus": prereq_bonus,
    }


def _build_material_groups(mat_proficiency: dict) -> dict:
    ores = sorted(
        [_material_dropdown(c, mat_proficiency) for c in ORE_CODES],
        key=lambda x: (x["rarity"], x["code"]),
    )
    ingots = sorted(
        [_material_dropdown(c, mat_proficiency) for c in ORE_CODES if MATERIALS[c].get("ingot")],
        key=lambda x: (x["rarity"], x["code"]),
    )
    # P3-2: 합금주괴 옵션은 일반 잠금 정책 (force_locked 제거).
    # 통제실 '주괴 제작' 모드에서는 UI상 합금 노출 안 함, '무기 제작' 모드에서 매핑 따라 노출.
    alloys = sorted(
        [_material_dropdown(c, mat_proficiency) for c in ALLOY_CODES],
        key=lambda x: (x["rarity"], x["code"]),
    )
    return {"ores": ores, "ingots": ingots, "alloys": alloys}


_INPUT_TYPE_LABELS = {"ore": "광석", "ingot": "주괴", "alloy_ingot": "합금주괴"}


def _command_result_label(cmd: dict) -> str:
    """통제실 § 상세용 결과물 한글. 무기/합금/주괴/거래 분기."""
    mat = cmd.get("target_material") or ""
    mat_name = MATERIALS.get(mat, {}).get("name", mat)
    input_type = cmd.get("input_type") or "ore"
    work_type = cmd.get("work_type") or "ingot"
    weapon_cat = cmd.get("weapon_category")
    qty = int(cmd.get("quantity") or 0)
    if cmd.get("command_type") == "trade":
        action = cmd.get("trade_action")
        if input_type in WEAPON_CODES:
            weap = WEAPON_LABELS.get(input_type, input_type)
            quality = int(cmd.get("quality") or 0)
            base = f"{mat_name} {weap} (품질 {quality}등급)"
        else:
            base = f"{mat_name} {_INPUT_TYPE_LABELS.get(input_type, input_type)}"
        suffix = " 구매" if action == "buy" else " 판매"
        return f"{base} × {qty}{suffix}"
    if work_type == "weapon" and weapon_cat:
        return f"{mat_name} {WEAPON_LABELS.get(weapon_cat, weapon_cat)} × {qty}"
    if work_type == "alloy":
        return f"{mat_name} 합금주괴 × {qty}"
    return f"{mat_name} 주괴 × {qty}"


def _enrich_pending_command(cmd: dict, char_name_map: dict) -> dict:
    """통제실 § 표시·취소 미리보기용 메타 부착.
    - reserved_gold: trade buy만 자금 예약 (현재 시세 기준 미리보기)
    - reserved_stamina: 제출 시 차감된 스태미너 (취소 시 복원량)
    """
    qty = int(cmd.get("quantity") or 0)
    input_type = cmd.get("input_type") or "ore"
    reserved_gold = 0
    if cmd.get("command_type") == "trade" and cmd.get("trade_action") == "buy":
        merchant_id = cmd.get("merchant_id")
        unit = (
            get_current_price(input_type, cmd.get("target_material"), merchant_id)
            if merchant_id
            else 0
        )
        reserved_gold = max(0, unit) * qty
        reserved_stamina = get_trade_stamina_cost(qty)  # 거래는 명령당 고정 1
    elif cmd.get("command_type") == "trade":
        reserved_stamina = get_trade_stamina_cost(qty)  # 거래는 명령당 고정 1
    else:
        weapon_cat = cmd.get("weapon_category")
        work_type = cmd.get("work_type") or "ingot"
        if work_type == "weapon" and weapon_cat:
            per = get_weapon_stamina_cost(weapon_cat, input_type)
        else:
            per = get_stamina_cost(input_type)
        reserved_stamina = per * qty
    return {
        **cmd,
        "character_name": char_name_map.get(cmd.get("character_id"), ""),
        "result_label": _command_result_label(cmd),
        "input_label": _INPUT_TYPE_LABELS.get(input_type, input_type),
        "reserved_gold": reserved_gold,
        "reserved_stamina": reserved_stamina,
    }


def _build_characters_data(
    char: dict,
    mat_proficiency: dict,
    skills: dict,
    ore_inventory: dict,
    ingot_inventory: dict,
    alloy_ingot_inventory: dict,
    mat_status: dict,
    ore_inventory_by_quality: dict,
    ingot_inventory_by_quality: dict,
    alloy_ingot_inventory_by_quality: dict,
) -> dict:
    """JS용 캐릭터 정보 — 향후 NPC 추가 시 같은 dict에 합쳐 전달."""
    prereq_bonus_map = {}
    for code in MATERIALS:
        prereq = PREREQUISITES.get(code)
        prereq_bonus_map[code] = (
            get_prerequisite_bonus(mat_proficiency.get(prereq, 0)) if prereq else 0
        )
    return {
        char["id"]: {
            "name": char["name"],
            "stamina_current": char.get("stamina_current", 0),
            "stamina_max": char["health"] // 5,
            "skills": skills,
            "mat_proficiency": mat_proficiency,
            "prereq_bonus": prereq_bonus_map,
            "mat_status": mat_status,
            "ore_inventory": ore_inventory,
            "ingot_inventory": ingot_inventory,
            "alloy_ingot_inventory": alloy_ingot_inventory,
            "ore_inventory_by_quality": ore_inventory_by_quality,
            "ingot_inventory_by_quality": ingot_inventory_by_quality,
            "alloy_ingot_inventory_by_quality": alloy_ingot_inventory_by_quality,
            "is_serious_injured": char.get("is_serious_injured", False),
            "is_injured": char.get("is_injured", False),
        }
    }


async def _build_dashboard_context(
    request: Request,
    user: dict,
    delete_error: str | None = None,
    submit_warning: str | None = None,
) -> dict:
    # R-5: 1라운드 — users + characters 병렬 (2 round-trip)
    user_rows, characters = await asyncio.gather(
        db_select_async("users", id=user["sub"]),
        db_select_async("characters", user_id=user["sub"]),
    )
    is_admin = bool(user_rows and user_rows[0].get("is_admin"))
    user_gold = int(user_rows[0].get("gold") or 0) if user_rows else 0
    char = characters[0] if characters else None
    if char:
        char.setdefault("is_injured", False)
        char.setdefault("is_serious_injured", False)
        char.setdefault("serious_injury_remaining", 0)
        char.setdefault("stamina_current", 0)
        # R-5: 2라운드 — P5 창고 공유 정책 적용
        #   warehouse는 owner_id=user_id (유저 공유), 인벤은 owner_id=actor_id (각자)
        today_str = date.today().isoformat()
        (
            all_commands,
            mailbox_rows,
            mat_prof_rows,
            skill_rows,
            user_warehouse_rows,
            char_inv_rows,
            merchants_rows,
            merchant_inv_rows,
            market_price_rows,
            npc_rows,
            npc_candidate_rows,
        ) = await asyncio.gather(
            db_select_async("commands", character_id=char["id"]),
            db_select_async("mailbox", character_id=char["id"]),
            db_select_async("material_proficiency", character_id=char["id"]),
            db_select_async("character_skills", character_id=char["id"]),
            db_select_async("items", owner_id=user["sub"]),  # user 공유 창고
            db_select_async("items", owner_id=char["id"]),  # 본인 char 인벤
            db_select_async("merchants"),
            db_select_async("merchant_inventory"),
            db_select_async("market_prices", date=today_str),
            db_select_async("npcs", owner_id=user["sub"]),
            db_select_async("npc_candidates", user_id=user["sub"]),
        )
        # ── P5: NPC 종속 데이터 fetch (3라운드 — 본인 + 고용 NPC들) ──
        npcs_by_id: dict = {}
        npc_items_map: dict = {}
        npc_skills_map: dict = {}
        npc_prof_map: dict = {}
        if npc_rows:
            tasks = []
            for npc in npc_rows:
                npc["_kind"] = "npc"
                npcs_by_id[npc["id"]] = npc
                tasks.extend(
                    [
                        db_select_async("commands", character_id=npc["id"]),
                        db_select_async("mailbox", character_id=npc["id"]),
                        db_select_async("items", owner_id=npc["id"]),
                        db_select_async("npc_skills", npc_id=npc["id"]),
                        db_select_async("npc_material_proficiency", npc_id=npc["id"]),
                    ]
                )
            npc_extras = await asyncio.gather(*tasks)
            for i, npc in enumerate(npc_rows):
                ncmds, nmail, nitems, nskills, nprof = npc_extras[i * 5 : i * 5 + 5]
                all_commands = list(all_commands) + list(ncmds)
                mailbox_rows = list(mailbox_rows) + list(nmail)
                npc_items_map[npc["id"]] = nitems
                npc_skills_map[npc["id"]] = {r["skill_name"]: r["value"] for r in nskills}
                npc_prof_map[npc["id"]] = {r["material_type"]: r["value"] for r in nprof}

        # 통제실 § pending 명령 — 캐릭터/NPC별 그룹 + 결과물/환불 미리보기 메타 부착
        char_name_map = {char["id"]: char["name"]}
        for nid, npc in npcs_by_id.items():
            char_name_map[nid] = npc["name"]
        raw_pending = [c for c in all_commands if c["status"] == "pending"]
        raw_pending.sort(key=lambda c: (c.get("character_id", ""), c.get("created_at", "")))
        pending_commands = [_enrich_pending_command(c, char_name_map) for c in raw_pending]
        # 캐릭터별 그룹 (P5 NPC 합류 후 같은 dict 키로 자동 분류)
        pending_groups: dict[str, list] = {}
        for cmd in pending_commands:
            pending_groups.setdefault(cmd.get("character_id"), []).append(cmd)
        mailbox = sorted(mailbox_rows, key=lambda x: x["created_at"], reverse=True)
        # P4-1·P6 S2-C 우편함 3탭 분리 — 거래 / 성장 보고 / 그 외(대장간·회복)
        trade_mail = [m for m in mailbox if m.get("body") and m["body"].get("type") == "trade"]
        growth_mail = [m for m in mailbox if m.get("body") and m["body"].get("type") == "growth"]
        blacksmith_mail = [
            m
            for m in mailbox
            if not (m.get("body") and m["body"].get("type") in ("trade", "growth"))
        ]
        mat_proficiency = {row["material_type"]: row["value"] for row in mat_prof_rows}
        character_skills = {row["skill_name"]: row["value"] for row in skill_rows}
        # P5: warehouse = user 공유, 본인 char items에는 인벤만 들어있음 (마이그레이션 후 보장)
        warehouse_items = sorted(
            [it for it in user_warehouse_rows if it.get("location") == "warehouse"],
            key=lambda x: x.get("created_at", ""),
            reverse=True,
        )
        # 본인 char 인벤만 (warehouse는 위 user 공유로 분리됨)
        all_items = sorted(char_inv_rows, key=lambda x: x.get("created_at", ""), reverse=True)
        # 재료 품질 보너스(2026-06-01): 총합 dict {material: qty}에 더해
        # 등급별 재고 {material: {quality: qty}}도 같은 순회로 빌드 (품질 선택 UI·검증용).
        ore_inventory: dict = {}
        ingot_inventory: dict = {}
        alloy_ingot_inventory: dict = {}
        ore_inventory_by_quality: dict = {}
        ingot_inventory_by_quality: dict = {}
        alloy_ingot_inventory_by_quality: dict = {}
        _inv_by_type = {
            "ore": (ore_inventory, ore_inventory_by_quality),
            "ingot": (ingot_inventory, ingot_inventory_by_quality),
            "alloy_ingot": (alloy_ingot_inventory, alloy_ingot_inventory_by_quality),
        }
        for item in warehouse_items:
            slot = _inv_by_type.get(item.get("item_type"))
            if not slot:
                continue
            total_dict, by_q_dict = slot
            mat = item["material"]
            qty = item.get("quantity", 0)
            q = item.get("quality") or 0
            total_dict[mat] = total_dict.get(mat, 0) + qty
            grade_map = by_q_dict.setdefault(mat, {})
            grade_map[q] = grade_map.get(q, 0) + qty
        # P4-1 중앙광장 — 소형 인벤(거래 작업대) + 시장 데이터
        # P5: 본인 인벤 + 모든 고용 NPC 인벤 통합 (owner 정보 포함)
        inventory_items = [
            {
                "id": it["id"],
                "item_type": it["item_type"],
                "material": it["material"],
                "quality": it.get("quality") or 0,
                "quantity": it.get("quantity", 0),
                "owner_id": char["id"],
                "owner_name": char["name"],
            }
            for it in all_items
            if it.get("location") == "inventory"
        ]
        for npc in npc_rows:
            for it in npc_items_map.get(npc["id"], []):
                if it.get("location") == "inventory":
                    inventory_items.append(
                        {
                            "id": it["id"],
                            "item_type": it["item_type"],
                            "material": it["material"],
                            "quality": it.get("quality") or 0,
                            "quantity": it.get("quantity", 0),
                            "owner_id": npc["id"],
                            "owner_name": npc["name"],
                        }
                    )
        merchants_list = sorted(merchants_rows, key=lambda m: m.get("code", ""))
        # 세션 3-b 정정: 상인별 시세 분리 — 키 = "merchant_id|item_type|material"
        market_price_map = {
            f"{r['merchant_id']}|{r['item_type']}|{r['material']}": r["current_price"]
            for r in market_price_rows
        }
        mat_status = {code: get_material_status(code, mat_proficiency) for code in MATERIALS}
        stamina_max = char["health"] // 5
        material_groups = _build_material_groups(mat_proficiency)
        characters_data = _build_characters_data(
            char,
            mat_proficiency,
            character_skills,
            ore_inventory,
            ingot_inventory,
            alloy_ingot_inventory,
            mat_status,
            ore_inventory_by_quality,
            ingot_inventory_by_quality,
            alloy_ingot_inventory_by_quality,
        )
        # 드롭다운에 표시할 actor 후보 — 본인 캐릭터 + 고용 NPC 합류 (P5)
        character_options = [
            {
                "id": char["id"],
                "name": char["name"],
                "disabled": char.get("is_serious_injured", False),
            }
        ]
        hired_npcs: list = []
        for npc in npc_rows:
            n_prof = npc_prof_map.get(npc["id"], {})
            n_skills = npc_skills_map.get(npc["id"], {})
            n_mat_status = {code: get_material_status(code, n_prof) for code in MATERIALS}
            # P5 창고 공유: NPC도 본인과 같은 user 창고 dict 공유 (보유 수치 동일)
            characters_data.update(
                _build_characters_data(
                    npc,
                    n_prof,
                    n_skills,
                    ore_inventory,
                    ingot_inventory,
                    alloy_ingot_inventory,
                    n_mat_status,
                    ore_inventory_by_quality,
                    ingot_inventory_by_quality,
                    alloy_ingot_inventory_by_quality,
                )
            )
            character_options.append(
                {
                    "id": npc["id"],
                    "name": npc["name"],
                    "disabled": npc.get("is_serious_injured", False),
                }
            )
            hired_npcs.append(
                {
                    "id": npc["id"],
                    "name": npc["name"],
                    "stats": {
                        k: npc.get(k, 0)
                        for k in (
                            "strength",
                            "intelligence",
                            "charisma",
                            "health",
                            "luck",
                            "dexterity",
                        )
                    },
                    "skills": n_skills,
                    "proficiency": n_prof,
                    "stamina_current": npc.get("stamina_current", 0),
                    "stamina_max": (npc.get("health") or 0) // 5,
                    "fee_per_batch": npc.get("fee_per_batch", 0),
                    # F-5 선불 홀드 표시용 — >0이면 이번 배치 창에 이미 수수료 선불됨(추가 명령 무차감)
                    "fee_held": npc.get("fee_held", 0),
                    "hire_cost": npc.get("hire_cost", 0),
                    "is_injured": npc.get("is_injured", False),
                    "is_serious_injured": npc.get("is_serious_injured", False),
                    "serious_injury_remaining": npc.get("serious_injury_remaining", 0),
                    "created_at": npc.get("created_at"),
                }
            )
        # NPC 후보 풀 (배치마다 갱신, 3명) — 표시용 카드
        npc_candidates = sorted(
            [
                {
                    "id": c["id"],
                    "name": c["name"],
                    "stats": c.get("stats", {}),
                    "skills": c.get("skills", {}),
                    "proficiency": c.get("proficiency", {}),
                    "stat_total": c.get("stat_total", 0),
                    "hire_cost": c.get("hire_cost", 0),
                    "fee": c.get("fee", 0),
                    "created_at": c.get("created_at"),
                }
                for c in npc_candidate_rows
            ],
            key=lambda x: x.get("created_at", ""),
        )
    else:
        pending_commands, mailbox, mat_proficiency, character_skills = [], [], {}, {}
        pending_groups = {}
        trade_mail, blacksmith_mail, growth_mail = [], [], []
        warehouse_items, inventory_items = [], []
        stamina_max = 0
        material_groups = {"ores": [], "ingots": [], "alloys": []}
        characters_data = {}
        character_options = []
        merchants_list, merchant_inv_rows, market_price_map = [], [], {}
        hired_npcs, npc_candidates = [], []
    material_labels = {code: info["name"] for code, info in MATERIALS.items()}
    ore_admin_options = sorted(
        [
            {"code": c, "name": MATERIALS[c]["name"], "rarity": MATERIALS[c]["rarity"]}
            for c in ORE_CODES
        ],
        key=lambda x: (x["rarity"], x["code"]),
    )
    # 디버그: 모든 소재 (광석 + 합금) 숙련도 set 용
    material_admin_options = sorted(
        [
            {
                "code": c,
                "name": MATERIALS[c]["name"],
                "rarity": MATERIALS[c]["rarity"],
                "is_alloy": c in ALLOY_CODES,
            }
            for c in MATERIALS
        ],
        key=lambda x: (x["is_alloy"], x["rarity"], x["code"]),
    )
    skill_admin_options = [
        {"code": "smelting", "name": "제련"},
        {"code": "forging", "name": "단조"},
        {"code": "heat_treat", "name": "열처리"},
        {"code": "finishing", "name": "마감"},
        {"code": "appraisal", "name": "감정"},
        {"code": "talent_management", "name": "인재관리"},
    ]
    return {
        "request": request,
        "username": user["username"],
        "is_admin": is_admin,
        "user_gold": user_gold,
        "item_descriptions": item_descriptions_for_js(),
        "character": char,
        "pending_commands": pending_commands,
        "pending_groups": pending_groups,
        "next_batch_at": next_batch_at_iso(),
        "batch_hours_kst": BATCH_HOURS_KST,
        "mailbox": mailbox,
        "mat_proficiency": mat_proficiency,
        "character_skills": character_skills,
        "blacksmith_mail": blacksmith_mail,
        "trade_mail": trade_mail,
        "growth_mail": growth_mail,
        "items": warehouse_items,
        "inventory_items": inventory_items,
        "merchants": merchants_list,
        "merchant_inventory": merchant_inv_rows,
        "market_prices": market_price_map,
        "quality_multipliers": QUALITY_MULTIPLIERS,
        "material_labels": material_labels,
        "item_type_labels": ITEM_TYPE_LABELS,
        "stamina_max": stamina_max,
        "material_groups": material_groups,
        "characters_data": characters_data,
        "character_options": character_options,
        "hired_npcs": hired_npcs,
        "npc_candidates": npc_candidates,
        "ore_admin_options": ore_admin_options,
        "material_admin_options": material_admin_options,
        "skill_admin_options": skill_admin_options,
        "category_by_type": CATEGORY_BY_TYPE,
        "category_labels": CATEGORY_LABELS,
        "category_order": CATEGORY_ORDER,
        "alloy_recipes": {k: list(v) for k, v in ALLOY_RECIPES.items()},
        "material_info": {
            code: {"ingot": info.get("ingot"), "name": info["name"], "rarity": info["rarity"]}
            for code, info in MATERIALS.items()
        },
        "weapon_codes": WEAPON_CODES,
        "weapon_labels": WEAPON_LABELS,
        "weapon_recipes": WEAPON_RECIPES,
        "weapon_stamina_bonus": WEAPON_STAMINA_BONUS,
        "ore_codes": ORE_CODES,
        "alloy_codes": ALLOY_CODES,
        "delete_error": delete_error,
        "submit_warning": submit_warning,
    }


# 명령 제출이 막힌 사유 → /dashboard?warn=<code> 플래시 메시지 (작업실 배너로 표시)
_SUBMIT_WARNINGS = {
    "material_reserved": (
        "이미 제출한 명령서가 그 자원을 예약 중입니다. 공유 창고라 다른 작업자의 명령까지 "
        "합산되어, 남은 자원으로는 더 발주할 수 없습니다. 명령을 취소하거나 자원을 더 확보한 뒤 "
        "다시 시도하세요."
    ),
    "material_short": "창고에 해당 자원이 부족해 명령을 제출할 수 없습니다.",
    "stamina_short": "스태미너가 부족해 명령을 제출할 수 없습니다.",
    "fee_short": (
        "이 NPC의 이번 배치 수수료(선불)를 낼 자금이 부족합니다. 자금을 확보한 뒤 다시 시도하세요."
    ),
    "service_unavailable": "일시적인 오류로 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
}


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    warn = _SUBMIT_WARNINGS.get(request.query_params.get("warn"))
    context = await _build_dashboard_context(request, user, submit_warning=warn)
    # R-3: 중복 characters fetch 제거 — context의 character 빈 체크로 분기
    if context["character"] is None:
        return RedirectResponse("/character/create", status_code=302)
    return templates.TemplateResponse(request, "dashboard.html", context)
