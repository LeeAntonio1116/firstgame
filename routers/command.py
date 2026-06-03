from datetime import UTC, date, datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from config import CANCEL_CUTOFF_SECONDS
from database import (
    adjust_gold,
    adjust_stamina,
    db_delete,
    db_insert,
    db_select,
    db_update,
    hold_npc_fee,
    release_npc_fee,
)
from engine import dice
from engine.batch import _accumulate_exp, next_batch_at
from engine.market import calculate_weapon_price, get_current_price
from engine.materials import (
    ALLOY_CODES,
    ALLOY_RECIPES,
    MATERIALS,
    ORE_CODES,
    WEAPON_CODES,
    WEAPON_RECIPES,
    get_material_status,
    get_stamina_cost,
    get_trade_stamina_cost,
    get_weapon_stamina_cost,
)
from routers.auth import get_current_user

SMALL_INVENTORY_SIZE = 5

router = APIRouter(prefix="/commands")


# ── P5 actor 헬퍼 (캐릭터·NPC 통합 소유 검증) ─────────────
def _owned_actors(user_id: str) -> list[dict]:
    chars = db_select("characters", user_id=user_id)
    npcs = db_select("npcs", owner_id=user_id)
    for c in chars:
        c["_kind"] = "character"
    for n in npcs:
        n["_kind"] = "npc"
    return list(chars) + list(npcs)


def _user_has_blacksmith(user_id: str) -> bool:
    """본인 char가 대장간을 시작했어야 본인+NPC 모두 명령 가능."""
    chars = db_select("characters", user_id=user_id)
    return any(c.get("has_blacksmith") for c in chars)


def _actor_table(actor: dict) -> str:
    return "npcs" if actor.get("_kind") == "npc" else "characters"


def _actor_user_id(actor: dict) -> str | None:
    """캐릭터=user_id / NPC=owner_id. P5 창고 공유의 키."""
    return actor.get("user_id") or actor.get("owner_id")


def _actor_mat_proficiency(actor: dict) -> dict:
    if actor.get("_kind") == "npc":
        rows = db_select("npc_material_proficiency", npc_id=actor["id"])
    else:
        rows = db_select("material_proficiency", character_id=actor["id"])
    return {r["material_type"]: r["value"] for r in rows}


def _talent_check_on_npc_dispatch(user_id: str, char: dict, command_type: str) -> dict:
    """P6 S2-B: NPC 명령 발주 시 본인 캐릭터 인재관리 스킬 d100 → (actor, command_type) 풀 재계산.

    2026-05-31 통솔 stat → 인재관리 skill 전환 ([[인재관리_스킬_전환]]).
    판정 주체 = 비파견(대장간·거래)이면 지시자 본인 캐릭터의 인재관리 스킬. (파견=대장은 P7+)

    묶음 단위 = (char.id, command_type) 풀. 같은 묶음 모든 pending row가 풀 값 공유.
    풀 토큰 = max 룰 (대성공 ≥ 1번이면 2, 극단 ≥ 1번이면 1).
    풀 페널티 = 한 번이라도 대실패면 -3 박힘 (min 룰 → 한 번 박히면 유지).
    꼼수 봉쇄: 명령서 하나씩 쪼개 발주해도 토큰 누적 안 됨.

    반환: {"rerolls": int, "penalty": int} — 호출 측에서 새 commands row INSERT 시 박음.
    NPC 아니면 {"rerolls": 0, "penalty": 0}.
    """
    if char.get("_kind") != "npc":
        return {"rerolls": 0, "penalty": 0}

    owner_chars = db_select("characters", user_id=user_id)
    if not owner_chars:
        return {"rerolls": 0, "penalty": 0}
    owner = owner_chars[0]

    # 인재관리 스킬 d100 + 결과별 토큰·페널티
    tm_rows = db_select(
        "character_skills", character_id=owner["id"], skill_name="talent_management"
    )
    tm_value = int(tm_rows[0].get("value") or 0) if tm_rows else 0
    injured = bool(owner.get("is_injured"))
    check = dice.talent_management_check(tm_value, injured=injured)

    # 실패·대실패 시 인재관리 skill exp 누적 (feedback-growth-failure-only 룰)
    if check["exp_accumulated"]:
        owner_with_kind = {**owner, "_kind": "character"}
        _accumulate_exp(owner_with_kind, "skill", "talent_management")

    # 같은 묶음 (actor + command_type) pending row 조회
    actor_id = char["id"]
    existing = db_select(
        "commands",
        character_id=actor_id,
        command_type=command_type,
        status="pending",
    )

    # 풀 재계산: max 토큰 / min 페널티 (음수가 페널티)
    existing_max_rerolls = max(
        (int(c.get("rerolls_remaining") or 0) for c in existing),
        default=0,
    )
    new_pool_rerolls = max(existing_max_rerolls, check["rerolls_granted"])

    existing_min_penalty = min(
        (int(c.get("penalty_modifier") or 0) for c in existing),
        default=0,
    )
    new_pool_penalty = min(existing_min_penalty, check["penalty_modifier"])

    # 같은 묶음 기존 pending row들도 풀 값으로 update (변동 있는 row만)
    for c in existing:
        cur_rerolls = int(c.get("rerolls_remaining") or 0)
        cur_penalty = int(c.get("penalty_modifier") or 0)
        if cur_rerolls != new_pool_rerolls or cur_penalty != new_pool_penalty:
            db_update(
                "commands",
                {
                    "rerolls_remaining": new_pool_rerolls,
                    "penalty_modifier": new_pool_penalty,
                },
                id=c["id"],
            )

    return {"rerolls": new_pool_rerolls, "penalty": new_pool_penalty}


def _owned_quantity(user_id: str, item_type: str, material: str, quality: int | None = None) -> int:
    """대장간 명령용 — user 공유 창고(warehouse) 자원 합산 (P5).
    인자명은 user_id (호출 측에서 _actor_user_id로 변환). ingot/alloy_ingot은 quality별 row 합계.
    quality 지정(>=1)이면 그 등급 row만 합산(재료 품질 보너스, 2026-06-01), 미지정이면 전체 합."""
    rows = db_select(
        "items", owner_id=user_id, item_type=item_type, material=material, location="warehouse"
    )
    if quality and quality >= 1:
        rows = [r for r in rows if (r.get("quality") or 0) == quality]
    return sum(r.get("quantity", 0) for r in rows)


def _pending_warehouse_demand(user_id: str) -> dict:
    """B-1·B-2: 같은 user의 모든 pending 대장간 명령이 약정한 창고 자원 수요 합산.
    반환: {(item_type, material, quality): 약정 수량}. alloy 명령은 ALLOY_RECIPES 광석(quality 0)으로 환산.
    제출 시 '보유 − 약정 ≥ 요청'을 (선택 등급 단위로) 검증해 공유 창고 과다발주(→ 무료 제작)를 차단.
    품질 세분화(2026-06-01): 같은 소재라도 등급별로 약정을 분리해 등급별 재고를 정확히 비교."""
    demand: dict = {}
    for actor in _owned_actors(user_id):
        rows = db_select(
            "commands", character_id=actor["id"], command_type="blacksmith", status="pending"
        )
        for c in rows:
            qty = int(c.get("quantity") or 0)
            if qty <= 0:
                continue
            c_input = c.get("input_type") or "ore"
            c_mat = c.get("target_material")
            c_quality = int(c.get("input_quality") or 0)
            if c_input == "alloy":
                for ore_code in ALLOY_RECIPES.get(c_mat, ()):
                    demand[("ore", ore_code, 0)] = demand.get(("ore", ore_code, 0), 0) + qty
            else:
                key = (c_input, c_mat, c_quality)
                demand[key] = demand.get(key, 0) + qty
    return demand


# ── F-5 NPC 수수료 선불 홀드 (발주 시 선차감, 배치 정산·취소·해고 환불) ────
def _reserve_npc_fee(char: dict, user_id: str) -> int | None:
    """NPC 명령 발주 시 그 NPC의 이번 배치 첫 명령이면 fee_per_batch를 gold에서 원자 선차감(홀드).
    fee_held=0 게이트 + gold 차감을 hold_npc_fee RPC가 NPC 행 FOR UPDATE로 직렬화 → 동시 발주에도
    정확히 1회만 홀드(이중차감 없음). 반환: 홀드액(0 = 불필요/이미 홀드됨), None = 자금 부족(발주 거부)."""
    if char.get("_kind") != "npc":
        return 0
    fee = int(char.get("fee_per_batch") or 0)
    if fee <= 0:
        return 0
    return hold_npc_fee(char["id"], user_id, fee)


def _release_npc_fee(char: dict, user_id: str, amount: int) -> None:
    """발주 도중 다른 검증/INSERT 실패 시 방금 홀드한 수수료 원자 롤백."""
    if amount <= 0:
        return
    release_npc_fee(char["id"], user_id)


def _release_npc_fee_if_no_pending(char: dict) -> None:
    """NPC의 마지막 pending 명령 취소 시 선불 홀드 수수료 환불 (다른 pending 남으면 유지).
    환불 자체는 release_npc_fee RPC가 단일 승자라 동시 취소/해고에도 이중 환불 없음."""
    if char.get("_kind") != "npc":
        return
    if int(char.get("fee_held") or 0) <= 0:
        return  # 빠른 skip (요청 스냅샷)
    if db_select("commands", character_id=char["id"], status="pending"):
        return  # 아직 이번 창에 다른 명령 남음 — 홀드 유지
    owner = _actor_user_id(char)
    if owner:
        release_npc_fee(char["id"], owner)


@router.post("/submit")
async def submit_command(
    request: Request,
    target_character_id: str = Form(...),
    material_input: str = Form(...),  # "{material_code}|{input_type}"
    quantity: int = Form(1),
    work_type: str = Form("ingot"),  # 'ingot' / 'weapon' / (P3-3) 'alloy'
    weapon_category: str = Form(""),  # work_type='weapon'일 때 필수
    input_quality: int = Form(0),  # 입력 재료 품질 등급 (ingot/alloy_ingot=1~5, ore/alloy=0)
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    if quantity < 1:
        return RedirectResponse("/dashboard#workshop", status_code=302)

    parts = material_input.split("|", 1)
    if len(parts) != 2:
        return RedirectResponse("/dashboard#workshop", status_code=302)
    target_material, input_type = parts[0], parts[1]

    # 본인 캐릭터 또는 고용 NPC + (본인 char) 대장간 시작 + 중상 여부
    actors = _owned_actors(user["sub"])
    char = next((a for a in actors if a["id"] == target_character_id), None)
    if not char or char.get("is_serious_injured"):
        return RedirectResponse("/dashboard#workshop", status_code=302)
    if not _user_has_blacksmith(user["sub"]):
        return RedirectResponse("/dashboard#workshop", status_code=302)

    # input_type ↔ material 정합성
    if target_material not in MATERIALS:
        return RedirectResponse("/dashboard#workshop", status_code=302)
    if input_type == "ore":
        if target_material not in ORE_CODES:
            return RedirectResponse("/dashboard#workshop", status_code=302)
    elif input_type == "ingot":
        if target_material not in ORE_CODES or not MATERIALS[target_material].get("ingot"):
            return RedirectResponse("/dashboard#workshop", status_code=302)
    elif input_type == "alloy_ingot":
        if target_material not in ALLOY_CODES:
            return RedirectResponse("/dashboard#workshop", status_code=302)
    elif input_type == "alloy":
        # P3-3 합금주괴 제작 — material은 합금 코드, 광석 2종을 자동 소모
        if target_material not in ALLOY_CODES:
            return RedirectResponse("/dashboard#workshop", status_code=302)
    else:
        return RedirectResponse("/dashboard#workshop", status_code=302)

    # work_type 검증
    if work_type not in ("ingot", "weapon", "alloy"):
        return RedirectResponse("/dashboard#workshop", status_code=302)
    if work_type == "weapon":
        if weapon_category not in WEAPON_CODES:
            return RedirectResponse("/dashboard#workshop", status_code=302)
        if target_material not in WEAPON_RECIPES[weapon_category]:
            return RedirectResponse("/dashboard#workshop", status_code=302)
        # 합금 코드는 alloy_ingot 입력만 허용 (광석 직접 입력으로 합금 무기 X)
        if target_material in ALLOY_CODES and input_type != "alloy_ingot":
            return RedirectResponse("/dashboard#workshop", status_code=302)
    elif work_type == "alloy":
        # 합금주괴 제작은 input_type='alloy' 강제
        if input_type != "alloy":
            return RedirectResponse("/dashboard#workshop", status_code=302)
    elif work_type == "ingot":
        # 주괴 제작은 ore 입력만
        if input_type != "ore":
            return RedirectResponse("/dashboard#workshop", status_code=302)

    # 재료 품질 등급 검증(2026-06-01) — ingot/alloy_ingot 입력만 1~5, ore/alloy는 0(품질 보너스 미대상).
    if input_quality < 0 or input_quality > 5:
        return RedirectResponse("/dashboard#workshop", status_code=302)
    if input_type in ("ingot", "alloy_ingot"):
        if input_quality < 1:
            return RedirectResponse("/dashboard#workshop", status_code=302)
    else:
        input_quality = 0  # ore/alloy 입력은 광석(quality 0) 소비 → 보너스 0

    # 소재 잠금 검증 (소재 숙련도 기준 — locked면 차단). NPC는 npc_material_proficiency.
    mat_proficiency = _actor_mat_proficiency(char)
    if get_material_status(target_material, mat_proficiency) == "locked":
        return RedirectResponse("/dashboard#workshop", status_code=302)

    # 보유 검증 — P5: user 공유 창고 기준
    # B-1·B-2: 이미 제출된 pending 대장간 명령의 약정 수요를 차감해 과다발주(→ 무료 제작) 차단.
    #          막힐 때 조용히 중단하지 않고 사유(예약 선점 vs 보유 부족)를 경고 배너로 노출.
    actor_user_id = _actor_user_id(char) or user["sub"]
    demand = _pending_warehouse_demand(actor_user_id)
    # (item_type, material, quality) 단위 — 선택 등급 재고/약정을 정확히 비교(2026-06-01).
    targets = (
        [("ore", oc, 0) for oc in ALLOY_RECIPES.get(target_material, ())]
        if input_type == "alloy"
        else [(input_type, target_material, input_quality)]
    )
    for it, mat, q in targets:
        owned = _owned_quantity(actor_user_id, it, mat, q)
        if owned - demand.get((it, mat, q), 0) < quantity:
            # 보유는 충분하나 pending 명령이 선점 → 'reserved' / 보유 자체 부족 → 'short'
            warn = "material_reserved" if owned >= quantity else "material_short"
            return RedirectResponse(f"/dashboard?warn={warn}#workshop", status_code=302)

    # 스태미너 — 무기면 가산 포함
    if work_type == "weapon":
        cost_per = get_weapon_stamina_cost(weapon_category, input_type)
    else:
        cost_per = get_stamina_cost(input_type)
    total_cost = cost_per * quantity

    # F-5: NPC면 이번 배치 첫 명령 시 수수료 선불 홀드 (자금 부족이면 발주 거부)
    held_fee = _reserve_npc_fee(char, user["sub"])
    if held_fee is None:
        return RedirectResponse("/dashboard?warn=fee_short#workshop", status_code=302)
    # A-2: 스태미너 원자 차감 (부족이면 홀드 롤백 후 거부)
    if adjust_stamina(_actor_table(char), char["id"], -total_cost) is None:
        _release_npc_fee(char, user["sub"], held_fee)
        return RedirectResponse("/dashboard?warn=stamina_short#workshop", status_code=302)

    # 명령 INSERT — 실패 시 예약 자원(스태미너·수수료 홀드) 원자 롤백 (고아 홀드 누수 방지)
    try:
        modifiers = _talent_check_on_npc_dispatch(user["sub"], char, "blacksmith")
        db_insert(
            "commands",
            {
                "character_id": char["id"],
                "command_type": "blacksmith",
                "target_material": target_material,
                "input_type": input_type,
                "input_quality": input_quality,
                "work_type": work_type,
                "weapon_category": weapon_category if work_type == "weapon" else None,
                "quantity": quantity,
                "status": "pending",
                "rerolls_remaining": modifiers["rerolls"],
                "penalty_modifier": modifiers["penalty"],
            },
        )
    except Exception:
        adjust_stamina(_actor_table(char), char["id"], total_cost)
        _release_npc_fee(char, user["sub"], held_fee)
        raise
    return RedirectResponse("/dashboard#workshop", status_code=302)


# ── P4-1 거래 명령 (buy) ────────────────────────────────
def _inventory_slot_count(owner_id: str) -> int:
    rows = db_select("items", owner_id=owner_id, location="inventory")
    return len(rows)


def _inventory_has_same_slot(owner_id: str, item_type: str, material: str, quality: int) -> bool:
    rows = db_select(
        "items",
        owner_id=owner_id,
        location="inventory",
        item_type=item_type,
        material=material,
        quality=quality,
    )
    return len(rows) > 0


@router.post("/trade-buy")
async def trade_buy(
    request: Request,
    target_character_id: str = Form(...),
    merchant_id: str = Form(...),
    target_item_type: str = Form(...),
    target_material: str = Form(...),
    quantity: int = Form(1),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if quantity < 1:
        return RedirectResponse("/dashboard#plaza-main", status_code=302)

    # 본인 캐릭터 또는 고용 NPC + 중상 아님 (P5)
    actors = _owned_actors(user["sub"])
    char = next((a for a in actors if a["id"] == target_character_id), None)
    if not char or char.get("is_serious_injured"):
        return RedirectResponse("/dashboard#plaza-main", status_code=302)

    # 거래 가능 카테고리: 광석·주괴·합금주괴만 buy (무기는 P5+ 또는 sell 흐름)
    if target_item_type not in ("ore", "ingot", "alloy_ingot"):
        return RedirectResponse("/dashboard#plaza-main", status_code=302)
    if target_material not in MATERIALS:
        return RedirectResponse("/dashboard#plaza-main", status_code=302)

    # 상인 검증 — 광물 매입은 fixed/random만, officer_buyer는 매입만
    merchant_rows = db_select("merchants", id=merchant_id)
    if not merchant_rows:
        return RedirectResponse("/dashboard#plaza-main", status_code=302)
    merchant = merchant_rows[0]
    if merchant["merchant_type"] not in ("fixed", "random"):
        return RedirectResponse("/dashboard#plaza-main", status_code=302)

    # 상인 라인업 존재 확인 (재고 0이어도 row 자체는 있어야 — 라인업 외 차단)
    inv_rows = db_select(
        "merchant_inventory",
        merchant_id=merchant_id,
        item_type=target_item_type,
        material=target_material,
    )
    if not inv_rows:
        return RedirectResponse("/dashboard#plaza-main", status_code=302)

    # 인벤 5칸 검증
    has_same = _inventory_has_same_slot(char["id"], target_item_type, target_material, 0)
    if not has_same and _inventory_slot_count(char["id"]) >= SMALL_INVENTORY_SIZE:
        return RedirectResponse("/dashboard#plaza-main", status_code=302)

    # 자금 — 세션 3-b 정정: 상인별 시세 분리
    unit_price = get_current_price(target_item_type, target_material, merchant_id)
    if unit_price <= 0:
        return RedirectResponse("/dashboard#plaza-main", status_code=302)
    total_price = unit_price * quantity
    stamina_cost = get_trade_stamina_cost(quantity)  # 거래는 명령당 고정 1 (수량 무관)

    # A-2 스태미너 → A-1 자금(가격) → F-5 수수료 홀드 순 원자 차감. 단계별 실패 시 앞 단계 롤백.
    if adjust_stamina(_actor_table(char), char["id"], -stamina_cost) is None:
        return RedirectResponse("/dashboard#plaza-main", status_code=302)
    if adjust_gold(user["sub"], -total_price) is None:
        adjust_stamina(_actor_table(char), char["id"], stamina_cost)
        return RedirectResponse("/dashboard#plaza-main", status_code=302)
    held_fee = _reserve_npc_fee(char, user["sub"])
    if held_fee is None:
        adjust_gold(user["sub"], total_price)
        adjust_stamina(_actor_table(char), char["id"], stamina_cost)
        return RedirectResponse("/dashboard#plaza-main", status_code=302)

    # 명령 INSERT — 실패 시 예약 자원(스태미너·자금·수수료 홀드) 원자 롤백
    try:
        modifiers = _talent_check_on_npc_dispatch(user["sub"], char, "trade")
        # input_type 컬럼을 재사용해 거래 대상 카테고리 저장 ('ore'/'ingot'/'alloy_ingot')
        db_insert(
            "commands",
            {
                "character_id": char["id"],
                "command_type": "trade",
                "trade_action": "buy",
                "merchant_id": merchant_id,
                "target_material": target_material,
                "input_type": target_item_type,
                "quantity": quantity,
                "status": "pending",
                "unit_price_at_submit": unit_price,
                "rerolls_remaining": modifiers["rerolls"],
                "penalty_modifier": modifiers["penalty"],
            },
        )
    except Exception:
        adjust_gold(user["sub"], total_price)
        adjust_stamina(_actor_table(char), char["id"], stamina_cost)
        _release_npc_fee(char, user["sub"], held_fee)
        raise
    return RedirectResponse("/dashboard#plaza-main", status_code=302)


# ── P4-1 거래 명령 (sell) ───────────────────────────────
def _inventory_owned_quantity(owner_id: str, item_type: str, material: str, quality: int) -> int:
    """인벤(inventory)의 같은 슬롯 보유 합산. stack 초과로 row 2개일 수 있어 합계."""
    rows = db_select(
        "items",
        owner_id=owner_id,
        item_type=item_type,
        material=material,
        quality=quality,
        location="inventory",
    )
    return sum(r.get("quantity", 0) for r in rows)


def _consume_inventory_items(
    owner_id: str, item_type: str, material: str, quality: int, amount: int
) -> None:
    """인벤에서 amount개 차감. 오래된 row부터, 0이 되면 row 삭제.
    제출 시 보유 검증되므로 부족분은 발생 안 함."""
    rows = db_select(
        "items",
        owner_id=owner_id,
        item_type=item_type,
        material=material,
        quality=quality,
        location="inventory",
    )
    rows = sorted(rows, key=lambda r: r.get("created_at", ""))
    remaining = amount
    for row in rows:
        if remaining <= 0:
            break
        take = min(remaining, row.get("quantity", 0))
        new_qty = row.get("quantity", 0) - take
        if new_qty <= 0:
            db_delete("items", id=row["id"])
        else:
            db_update("items", {"quantity": new_qty}, id=row["id"])
        remaining -= take


@router.post("/trade-sell")
async def trade_sell(
    request: Request,
    item_id: str = Form(...),
    quantity: int = Form(1),
):
    """인벤 아이템을 시장에 판매. 광물·주괴·합금주괴 → 고정상인 / 무기 → 태수.
    제출 시 인벤에서 즉시 차감(예약), 자금 입금은 배치에서 처리."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if quantity < 1:
        return RedirectResponse("/dashboard#plaza-main", status_code=302)

    # 판매 대상 — 인벤(inventory)에 있어야 하고 본인 캐릭터 소유여야
    item_rows = db_select("items", id=item_id)
    if not item_rows:
        return RedirectResponse("/dashboard#plaza-main", status_code=302)
    item = item_rows[0]
    if item.get("location") != "inventory":
        return RedirectResponse("/dashboard#plaza-main", status_code=302)

    actors = _owned_actors(user["sub"])
    char = next((a for a in actors if a["id"] == item["owner_id"]), None)
    if not char or char.get("is_serious_injured"):
        return RedirectResponse("/dashboard#plaza-main", status_code=302)

    item_type = item["item_type"]
    material = item["material"]
    quality = int(item.get("quality") or 0)

    # 매입 상인 — 무기는 태수, 광물·주괴·합금주괴는 고정상인
    if item_type in WEAPON_CODES:
        merchant_code = "officer_buyer"
    elif item_type in ("ore", "ingot", "alloy_ingot"):
        merchant_code = "fixed_official"
    else:
        return RedirectResponse("/dashboard#plaza-main", status_code=302)
    merchant_rows = db_select("merchants", code=merchant_code)
    if not merchant_rows:
        return RedirectResponse("/dashboard#plaza-main", status_code=302)
    merchant_id = merchant_rows[0]["id"]

    # 보유 수량 검증
    if _inventory_owned_quantity(char["id"], item_type, material, quality) < quantity:
        return RedirectResponse("/dashboard#plaza-main", status_code=302)

    # P5: 매입처가 사주지 않는 자원(시세 0) 차단 — NPC 수수료만 손해 보는 거래 방지
    if item_type in WEAPON_CODES:
        unit_check = calculate_weapon_price(item_type, material, quality)
    else:
        unit_check = int(get_current_price(item_type, material, merchant_id) * 0.9)
    if unit_check <= 0:
        return RedirectResponse("/dashboard#plaza-main", status_code=302)

    # 스태미너 / 수수료
    stamina_cost = get_trade_stamina_cost(quantity)  # 거래는 명령당 고정 1 (수량 무관)

    # A-2 스태미너 → F-5 수수료 홀드 순 원자 차감 (인벤 차감은 통과 후). 실패 시 앞 단계 롤백.
    if adjust_stamina(_actor_table(char), char["id"], -stamina_cost) is None:
        return RedirectResponse("/dashboard#plaza-main", status_code=302)
    held_fee = _reserve_npc_fee(char, user["sub"])
    if held_fee is None:
        adjust_stamina(_actor_table(char), char["id"], stamina_cost)
        return RedirectResponse("/dashboard#plaza-main", status_code=302)

    # 검증 통과 — 인벤 즉시 차감 + 명령 INSERT (INSERT 실패 시 인벤·수수료·스태미너 롤백)
    _consume_inventory_items(char["id"], item_type, material, quality, quantity)
    try:
        modifiers = _talent_check_on_npc_dispatch(user["sub"], char, "trade")
        db_insert(
            "commands",
            {
                "character_id": char["id"],
                "command_type": "trade",
                "trade_action": "sell",
                "merchant_id": merchant_id,
                "target_material": material,
                "input_type": item_type,
                "quality": quality,
                "quantity": quantity,
                "status": "pending",
                "rerolls_remaining": modifiers["rerolls"],
                "penalty_modifier": modifiers["penalty"],
            },
        )
    except Exception:
        _refund_item_row(char["id"], item_type, material, quality, quantity, location="inventory")
        _release_npc_fee(char, user["sub"], held_fee)
        adjust_stamina(_actor_table(char), char["id"], stamina_cost)
        raise
    return RedirectResponse("/dashboard#plaza-main", status_code=302)


# ── A-2 능동 취소 — pending 명령 환불 후 cancelled로 전환 ────────
def _refund_item_row(
    owner_id: str,
    item_type: str,
    material: str,
    quality: int,
    quantity: int,
    location: str = "inventory",
) -> None:
    """trade sell 취소/해고 시 아이템 복원. F-4: items_unique 제약상 키당 1행 → 같은 슬롯이면
    항상 병합(무제한 누적), 없으면 새 row. location='inventory'(취소) | 'warehouse'(해고 — user 창고)."""
    existing = db_select(
        "items",
        owner_id=owner_id,
        item_type=item_type,
        material=material,
        quality=quality,
        location=location,
    )
    if existing:
        merged = existing[0].get("quantity", 0) + quantity
        db_update("items", {"quantity": merged}, id=existing[0]["id"])
        return
    db_insert(
        "items",
        {
            "owner_id": owner_id,
            "item_type": item_type,
            "material": material,
            "quality": quality,
            "quantity": quantity,
            "location": location,
        },
    )


def _refund_command_assets(cmd: dict, owner_user_id: str, *, sell_to: str = "inventory") -> None:
    """trade 명령의 자산 환불 — 취소(cancel)·해고(fire) 공용 (E-1).
    buy: 발주 시점 동결가(unit_price_at_submit, 없으면 created_at 일자 시세)로 gold 환불.
    sell: 차감했던 아이템 복원. sell_to='inventory'(취소 — 본인 인벤) | 'warehouse'(해고 — NPC가
          삭제되므로 user 공유 창고).
    blacksmith 명령은 제출 시 자산 예약이 없어 no-op (재료는 배치 차감, 스태미너는 호출 측 별도 처리)."""
    if (cmd.get("command_type") or "blacksmith") != "trade":
        return
    action = cmd.get("trade_action")
    quantity = int(cmd.get("quantity") or 0)
    input_type = cmd.get("input_type") or "ore"
    material = cmd.get("target_material")
    if action == "buy":
        submit_price = cmd.get("unit_price_at_submit")
        if submit_price is not None:
            unit = int(submit_price)
        else:
            # 옛 row 호환 — 발주 일자 시세 재계산
            try:
                cmd_date = date.fromisoformat((cmd.get("created_at") or "")[:10])
            except ValueError:
                cmd_date = None
            unit = get_current_price(input_type, material, cmd.get("merchant_id"), today=cmd_date)
        refund_gold = max(0, unit) * quantity
        if refund_gold > 0 and owner_user_id:
            adjust_gold(owner_user_id, refund_gold)  # A-1: 원자 입금
    elif action == "sell":
        quality = int(cmd.get("quality") or 0)
        owner = owner_user_id if sell_to == "warehouse" else cmd.get("character_id")
        _refund_item_row(owner, input_type, material, quality, quantity, location=sell_to)


@router.post("/cancel")
async def cancel_command(
    request: Request,
    command_id: str = Form(...),
):
    """pending 명령 능동 취소. 본인/소유 NPC 소유 명령만, 10분 컷 통과 시.
    blacksmith=스태미너 / trade buy=자금+스태미너 / trade sell=인벤+스태미너 환불.
    우편함 알림 없음 (사용자 능동 행동)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    cmd_rows = db_select("commands", id=command_id)
    if not cmd_rows:
        return RedirectResponse("/dashboard#control", status_code=302)
    cmd = cmd_rows[0]

    # 본인 캐릭터 또는 고용 NPC (P5)
    actors = _owned_actors(user["sub"])
    char = next((a for a in actors if a["id"] == cmd.get("character_id")), None)
    if not char:
        return RedirectResponse("/dashboard#control", status_code=302)

    if cmd.get("status") != "pending":
        return RedirectResponse("/dashboard#control", status_code=302)

    # 10분 컷 — 다음 배치까지 남은 시간
    now = datetime.now(UTC)
    remaining = (next_batch_at(now) - now).total_seconds()
    if remaining < CANCEL_CUTOFF_SECONDS:
        return RedirectResponse("/dashboard#control", status_code=302)

    quantity = int(cmd.get("quantity") or 0)
    input_type = cmd.get("input_type") or "ore"
    cmd_type = cmd.get("command_type") or "blacksmith"

    # A-4: 조건부 claim — pending→cancelled 원자 전환. 빈 결과면 배치(_claim_command)나 다른
    # 취소가 이미 선점한 것 → 환불하지 않고 종료 (취소↔배치 이중환급 차단).
    claimed = db_update("commands", {"status": "cancelled"}, id=cmd["id"], status="pending")
    if not claimed:
        return RedirectResponse("/dashboard#control", status_code=302)

    if cmd_type == "blacksmith":
        work_type = cmd.get("work_type") or "ingot"
        weapon_cat = cmd.get("weapon_category")
        if work_type == "weapon" and weapon_cat:
            per = get_weapon_stamina_cost(weapon_cat, input_type)
        else:
            per = get_stamina_cost(input_type)
        # A-2: 스태미너 원자 환불 (health/5 클램프)
        adjust_stamina(_actor_table(char), char["id"], per * quantity)
    elif cmd_type == "trade":
        adjust_stamina(_actor_table(char), char["id"], get_trade_stamina_cost(quantity))
        # 자산 환불 (buy=발주시세 gold / sell=본인 인벤 복원) — 해고와 공용 헬퍼 (E-1)
        _refund_command_assets(cmd, user["sub"], sell_to="inventory")

    # F-5: NPC의 마지막 pending 명령 취소면 선불 홀드 수수료 환불
    _release_npc_fee_if_no_pending(char)
    return RedirectResponse("/dashboard#control", status_code=302)


# ── P5 인벤↔창고 즉시 이동 (창고는 user 공유, 인벤은 actor 각자) ─────
@router.post("/move-item")
async def move_item(
    request: Request,
    item_id: str = Form(...),
    direction: str = Form(...),  # 'to_warehouse' / 'to_inventory'
    quantity: int = Form(0),  # 창고→인벤만 사용. 0=row 전체
    target_character_id: str = Form(""),  # 창고→인벤만 사용. 빈문자=본인 캐릭터
):
    """P5 창고 공유 정책:
    - 인벤→창고: actor 인벤 row를 user 공유 창고로 이동 (owner_id를 user_id로 변경 + stack 병합)
    - 창고→인벤: user 창고에서 quantity 차감 + target actor 인벤에 추가 (stack 병합 또는 5칸 검증)
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if direction == "to_warehouse":
        redirect = "/dashboard#plaza-main"
    elif direction == "to_inventory":
        redirect = "/dashboard#storage"
    else:
        return RedirectResponse("/dashboard", status_code=302)

    item_rows = db_select("items", id=item_id)
    if not item_rows:
        return RedirectResponse(redirect, status_code=302)
    item = item_rows[0]

    actors = _owned_actors(user["sub"])
    owned_actor_ids = {a["id"] for a in actors}
    item_type, material = item["item_type"], item["material"]
    item_quality = int(item.get("quality") or 0)
    row_quantity = int(item.get("quantity") or 0)

    # ── 인벤 → user 창고 ──
    if direction == "to_warehouse":
        if item["owner_id"] not in owned_actor_ids:
            return RedirectResponse(redirect, status_code=302)
        if item.get("location") != "inventory":
            return RedirectResponse(redirect, status_code=302)
        existing = db_select(
            "items",
            owner_id=user["sub"],
            item_type=item_type,
            material=material,
            quality=item_quality,
            location="warehouse",
        )
        if existing:
            merged = existing[0].get("quantity", 0) + row_quantity
            db_update("items", {"quantity": merged}, id=existing[0]["id"])
            db_delete("items", id=item["id"])
        else:
            db_update("items", {"owner_id": user["sub"], "location": "warehouse"}, id=item["id"])
        return RedirectResponse(redirect, status_code=302)

    # ── user 창고 → target actor 인벤 ──
    if item["owner_id"] != user["sub"]:
        return RedirectResponse(redirect, status_code=302)
    if item.get("location") != "warehouse":
        return RedirectResponse(redirect, status_code=302)

    move_qty = quantity if quantity > 0 else row_quantity
    if move_qty < 1 or move_qty > row_quantity:
        return RedirectResponse(redirect, status_code=302)

    target_owner = target_character_id.strip() if target_character_id else None
    if not target_owner:
        char_only = [a for a in actors if a.get("_kind") == "character"]
        if not char_only:
            return RedirectResponse(redirect, status_code=302)
        target_owner = char_only[0]["id"]
    if target_owner not in owned_actor_ids:
        return RedirectResponse(redirect, status_code=302)

    existing_inv = db_select(
        "items",
        owner_id=target_owner,
        item_type=item_type,
        material=material,
        quality=item_quality,
        location="inventory",
    )
    if existing_inv:
        # F-4: 무제한 누적 (items_unique 제약상 키당 1행). 5칸 제한은 신규 슬롯에만 적용.
        merged = existing_inv[0]["quantity"] + move_qty
        db_update("items", {"quantity": merged}, id=existing_inv[0]["id"])
    else:
        if _inventory_slot_count(target_owner) >= SMALL_INVENTORY_SIZE:
            return RedirectResponse(redirect, status_code=302)
        db_insert(
            "items",
            {
                "owner_id": target_owner,
                "item_type": item_type,
                "material": material,
                "quality": item_quality,
                "quantity": move_qty,
                "location": "inventory",
            },
        )

    # user 창고 원본 차감
    if move_qty >= row_quantity:
        db_delete("items", id=item["id"])
    else:
        db_update("items", {"quantity": row_quantity - move_qty}, id=item["id"])

    return RedirectResponse(redirect, status_code=302)
