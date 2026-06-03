import logging
import random
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import httpx

from config import BATCH_HOURS_KST as _BATCH_HOURS_KST_CFG
from database import adjust_gold, db_delete, db_insert, db_select, db_update, settle_npc_fee
from engine import blacksmith, dice
from engine.market import calculate_weapon_price, get_current_price
from engine.materials import (
    ALLOY_RECIPES,
    MATERIALS,
    PREREQUISITES,
    STEPS_INGOT,
    STEPS_ORE,
    WEAPON_CODES,
    WEAPON_LABELS,
    get_milestone_flags,
    get_prerequisite_bonus,
)

# KST = UTC+9 (DST 없음)
_KST_OFFSET = timedelta(hours=9)
BATCH_HOURS_KST = list(_BATCH_HOURS_KST_CFG)
logger = logging.getLogger(__name__)


def next_batch_at(now_utc: datetime | None = None) -> datetime:
    """다음 배치 도래 시각 (UTC). KST 기준 BATCH_HOURS_KST 중 가장 가까운 미래.
    오늘 남은 시각이 없으면 내일 첫 시각."""
    if now_utc is None:
        now_utc = datetime.now(UTC)
    now_kst = now_utc + _KST_OFFSET
    for h in BATCH_HOURS_KST:
        candidate_kst = now_kst.replace(hour=h, minute=0, second=0, microsecond=0)
        if candidate_kst > now_kst:
            return (candidate_kst - _KST_OFFSET).replace(tzinfo=UTC)
    # 오늘 시각 모두 지남 → 내일 첫 시각
    tomorrow_kst = (now_kst + timedelta(days=1)).replace(
        hour=BATCH_HOURS_KST[0],
        minute=0,
        second=0,
        microsecond=0,
    )
    return (tomorrow_kst - _KST_OFFSET).replace(tzinfo=UTC)


def next_batch_at_iso() -> str:
    return next_batch_at().isoformat()


_ITEM_TYPE_KOR = {"ore": "광석", "ingot": "주괴", "alloy_ingot": "합금주괴"}


def _item_label(item_type: str, material: str, quality: int = 0) -> str:
    """우편함 제목용 한글 라벨. 무기면 '생철광 단검 (품질 N등급)', 그 외 '생철광 광석'."""
    mat_name = MATERIALS.get(material, {}).get("name", material)
    if item_type in WEAPON_CODES:
        weap = WEAPON_LABELS.get(item_type, item_type)
        return f"{mat_name} {weap} (품질 {quality}등급)" if quality else f"{mat_name} {weap}"
    return f"{mat_name} {_ITEM_TYPE_KOR.get(item_type, item_type)}"


def _get_mat_proficiency(character_id: str, material_type: str) -> int:
    rows = db_select("material_proficiency", character_id=character_id, material_type=material_type)
    return rows[0]["value"] if rows else 0


def _get_character_skills(character_id: str) -> dict:
    rows = db_select("character_skills", character_id=character_id)
    return {row["skill_name"]: row["value"] for row in rows}


# ── P5 actor 추상화 (캐릭터/NPC 공용) ─────────────────────
def _actor_kind(actor: dict) -> str:
    return actor.get("_kind", "character")


def _actor_table(actor: dict) -> str:
    return "npcs" if _actor_kind(actor) == "npc" else "characters"


def _actor_user_id(actor: dict) -> str | None:
    return actor.get("user_id") or actor.get("owner_id")


def _fetch_actor(actor_id: str) -> dict | None:
    """commands.character_id가 character이거나 npc일 수 있음 — 양쪽 조회."""
    rows = db_select("characters", id=actor_id)
    if rows:
        a = dict(rows[0])
        a["_kind"] = "character"
        return a
    rows = db_select("npcs", id=actor_id)
    if rows:
        a = dict(rows[0])
        a["_kind"] = "npc"
        return a
    return None


def _fetch_actor_skills(actor: dict) -> dict:
    if _actor_kind(actor) == "npc":
        rows = db_select("npc_skills", npc_id=actor["id"])
    else:
        rows = db_select("character_skills", character_id=actor["id"])
    return {r["skill_name"]: r["value"] for r in rows}


def _get_actor_mat_proficiency(actor: dict, material_type: str) -> int:
    if _actor_kind(actor) == "npc":
        rows = db_select(
            "npc_material_proficiency", npc_id=actor["id"], material_type=material_type
        )
    else:
        rows = db_select(
            "material_proficiency", character_id=actor["id"], material_type=material_type
        )
    return rows[0]["value"] if rows else 0


def _upsert_actor_mat_proficiency(actor: dict, material_type: str, value: int) -> None:
    if _actor_kind(actor) == "npc":
        existing = db_select(
            "npc_material_proficiency", npc_id=actor["id"], material_type=material_type
        )
        if existing:
            db_update(
                "npc_material_proficiency",
                {"value": value},
                npc_id=actor["id"],
                material_type=material_type,
            )
        else:
            db_insert(
                "npc_material_proficiency",
                {
                    "npc_id": actor["id"],
                    "material_type": material_type,
                    "value": value,
                },
            )
    else:
        existing = db_select(
            "material_proficiency", character_id=actor["id"], material_type=material_type
        )
        if existing:
            db_update(
                "material_proficiency",
                {"value": value},
                character_id=actor["id"],
                material_type=material_type,
            )
        else:
            db_insert(
                "material_proficiency",
                {
                    "character_id": actor["id"],
                    "material_type": material_type,
                    "value": value,
                },
            )


def _update_actor_skill(actor: dict, skill_name: str, value: int) -> None:
    if _actor_kind(actor) == "npc":
        db_update("npc_skills", {"value": value}, npc_id=actor["id"], skill_name=skill_name)
    else:
        db_update(
            "character_skills", {"value": value}, character_id=actor["id"], skill_name=skill_name
        )


# ── P6 경험치 누적 성장 (2026-05-28) ──────────────────────
# 단일 출처: wiki [[캐릭터_스탯_성장]] / dice.is_growth_due·required_exp_for
# 실패 판정 시 accumulate_exp → 다음 배치 시작 시점에 apply_growth_due가 일괄 +1

# ── P6 S2-C: 배치 처리 중 actor별 성장 collector (2026-05-28) ──
# run_batch 안에서만 활성 (routers/* 발주 시점 호출은 추적 X).
# 배치 끝 시점에 actor별 통합 "성장 보고" mailbox INSERT (type=growth).
_growth_collector: dict = {}
_collector_active: bool = False


def _ensure_collector(actor: dict) -> dict:
    actor_id = actor["id"]
    if actor_id not in _growth_collector:
        _growth_collector[actor_id] = {
            "name": actor.get("name") or "",
            "kind": _actor_kind(actor),
            "stat_accs": {},  # name -> exp 누적 카운트 (그 배치 내)
            "skill_accs": {},
            "material_accs": {},
            "growths": [],  # +1 발생 항목 ({kind, name, before, after})
            "commands": [],  # 명령 풀 요약 ({cmd_id, command_type, rerolls, penalty, label})
        }
    return _growth_collector[actor_id]


def _collect_exp(actor: dict, kind: str, name: str) -> None:
    if not _collector_active:
        return
    bucket = _ensure_collector(actor)[f"{kind}_accs"]
    bucket[name] = bucket.get(name, 0) + 1


def _collect_growth(actor: dict, kind: str, name: str, before: int, after: int) -> None:
    if not _collector_active:
        return
    _ensure_collector(actor)["growths"].append(
        {"kind": kind, "name": name, "before": before, "after": after}
    )


def _collect_command(actor: dict, cmd: dict, label: str) -> None:
    if not _collector_active:
        return
    _ensure_collector(actor)["commands"].append(
        {
            "cmd_id": cmd.get("id"),
            "command_type": cmd.get("command_type"),
            "rerolls_remaining": int(cmd.get("rerolls_remaining") or 0),
            "penalty_modifier": int(cmd.get("penalty_modifier") or 0),
            "label": label,
        }
    )


def _exp_table_info(actor: dict, kind: str) -> tuple[str, str, str]:
    """(테이블명, id 컬럼명, name 컬럼명) 반환. kind ∈ {'stat','skill','material'}."""
    is_npc = _actor_kind(actor) == "npc"
    if kind == "stat":
        return (
            ("npc_stat_exp", "npc_id", "stat_name")
            if is_npc
            else ("character_stat_exp", "character_id", "stat_name")
        )
    if kind == "skill":
        return (
            ("npc_skills", "npc_id", "skill_name")
            if is_npc
            else ("character_skills", "character_id", "skill_name")
        )
    return (
        ("npc_material_proficiency", "npc_id", "material_type")
        if is_npc
        else ("material_proficiency", "character_id", "material_type")
    )


def _current_value_for(actor: dict, kind: str, name: str, skills: dict | None = None) -> int:
    """현재값 조회. stat은 actor row, skill은 skills 캐시(또는 DB), material은 DB."""
    if kind == "stat":
        return int(actor.get(name) or 0)
    if kind == "skill":
        if skills is not None and name in skills:
            return int(skills.get(name) or 0)
        tbl, id_col, name_col = _exp_table_info(actor, "skill")
        rows = db_select(tbl, **{id_col: actor["id"], name_col: name})
        return int(rows[0].get("value") or 0) if rows else 0
    # material
    return _get_actor_mat_proficiency(actor, name)


def _accumulate_exp(actor: dict, kind: str, name: str, skills: dict | None = None) -> None:
    """실패 판정 시 호출. 해당 row exp += 1. 95 컷이면 무시.
    kind ∈ {'stat','skill','material'} / name = 'strength'·'forging'·'raw_iron' 등.
    배치 처리 중에는 _growth_collector에도 누적 (성장 보고 메일용).
    """
    current = _current_value_for(actor, kind, name, skills)
    if current >= 95:
        return
    tbl, id_col, name_col = _exp_table_info(actor, kind)
    actor_id = actor["id"]
    rows = db_select(tbl, **{id_col: actor_id, name_col: name})
    if rows:
        cur_exp = int(rows[0].get("exp") or 0)
        db_update(tbl, {"exp": cur_exp + 1}, **{id_col: actor_id, name_col: name})
    elif kind == "stat":
        # stat row는 마이그레이션 시드로 모두 존재해야 하지만 신규 actor 대비 fallback
        db_insert(tbl, {id_col: actor_id, name_col: name, "exp": 1})
    # skill·material은 row 없으면 0→1 진입 (first_learn_check) 단계라 누적 안 함
    _collect_exp(actor, kind, name)


def _apply_growth_due(actor: dict, skills: dict) -> list:
    """배치 시작 시점 hook. actor의 모든 exp row 순회 → 필요 경험치 도달 row 모두 value +1, exp 0 리셋.
    반환: [{'kind','name','before','after'}, ...] (성장 발생 항목).
    배치 처리 중이면 _growth_collector에도 함께 기록 (성장 보고 메일에서 통합 표시)."""
    actor_id = actor["id"]
    actor_tbl = _actor_table(actor)
    growth_log: list = []

    # 1. stat (actor row의 컬럼이 곧 value)
    stat_tbl, stat_id_col, _ = _exp_table_info(actor, "stat")
    stat_exp_rows = db_select(stat_tbl, **{stat_id_col: actor_id})
    for row in stat_exp_rows:
        stat_name = row["stat_name"]
        current = int(actor.get(stat_name) or 0)
        exp = int(row.get("exp") or 0)
        if dice.is_growth_due(current, exp):
            new_value = current + 1
            db_update(actor_tbl, {stat_name: new_value}, id=actor_id)
            db_update(stat_tbl, {"exp": 0}, **{stat_id_col: actor_id, "stat_name": stat_name})
            actor[stat_name] = new_value
            growth_log.append(
                {"kind": "stat", "name": stat_name, "before": current, "after": new_value}
            )
            _collect_growth(actor, "stat", stat_name, current, new_value)

    # 2. skill
    skill_tbl, skill_id_col, _ = _exp_table_info(actor, "skill")
    skill_rows = db_select(skill_tbl, **{skill_id_col: actor_id})
    for row in skill_rows:
        sk_name = row["skill_name"]
        current = int(row.get("value") or 0)
        exp = int(row.get("exp") or 0)
        if dice.is_growth_due(current, exp):
            new_value = current + 1
            db_update(
                skill_tbl,
                {"value": new_value, "exp": 0},
                **{skill_id_col: actor_id, "skill_name": sk_name},
            )
            skills[sk_name] = new_value
            growth_log.append(
                {"kind": "skill", "name": sk_name, "before": current, "after": new_value}
            )
            _collect_growth(actor, "skill", sk_name, current, new_value)

    # 3. material
    mat_tbl, mat_id_col, _ = _exp_table_info(actor, "material")
    mat_rows = db_select(mat_tbl, **{mat_id_col: actor_id})
    for row in mat_rows:
        mt = row["material_type"]
        current = int(row.get("value") or 0)
        exp = int(row.get("exp") or 0)
        if dice.is_growth_due(current, exp):
            new_value = current + 1
            db_update(
                mat_tbl,
                {"value": new_value, "exp": 0},
                **{mat_id_col: actor_id, "material_type": mt},
            )
            growth_log.append(
                {"kind": "material", "name": mt, "before": current, "after": new_value}
            )
            _collect_growth(actor, "material", mt, current, new_value)

    return growth_log


def _consume_inventory(
    owner_id: str, item_type: str, material: str, quality: int | None = None
) -> bool:
    """창고(warehouse) 자원 1개 차감 — 대장간 명령용. 인벤은 거래 결과만.
    성공 차감하면 True, 재고 0/부재로 차감 못 하면 False.
    - ore: 0이 돼도 row 유지 (UX — 0개 표시). 0이면 차감 불가 → False.
    - ingot/alloy_ingot: quality 지정(>=1)이면 그 등급 row만 차감(재료 품질 보너스, 2026-06-01),
      미지정(None/0)이면 quality 낮은 row부터 차감(하위호환). 0이면 row 삭제 (quality별 row 누적 방지)
    B-1·B-2: 공유 창고 과다발주 방어 — 반환값으로 호출 측이 무료 결과물 생성을 막는다.
    """
    rows = db_select(
        "items", owner_id=owner_id, item_type=item_type, material=material, location="warehouse"
    )
    if not rows:
        return False
    if item_type == "ore":
        row = rows[0]
        if row.get("quantity", 0) <= 0:
            return False
        db_update("items", {"quantity": row["quantity"] - 1}, id=row["id"])
        return True
    # 재료 품질 보너스: 등급 지정 시 그 등급 row만 소비(없으면 False→부족메일), 미지정 시 낮은 등급부터.
    if quality and quality >= 1:
        rows = [r for r in rows if (r.get("quality") or 0) == quality]
    else:
        rows = sorted(rows, key=lambda r: (r.get("quality", 0), r.get("created_at", "")))
    for row in rows:
        if row.get("quantity", 0) > 0:
            new_qty = row["quantity"] - 1
            if new_qty <= 0:
                db_delete("items", id=row["id"])
            else:
                db_update("items", {"quantity": new_qty}, id=row["id"])
            return True
    return False


def _warehouse_quantity(owner_id: str, item_type: str, material: str) -> int:
    """창고 보유 합산 (alloy 제작 전 광석 충분 여부 선확인용)."""
    rows = db_select(
        "items", owner_id=owner_id, item_type=item_type, material=material, location="warehouse"
    )
    return sum(r.get("quantity", 0) for r in rows)


def _claim_command(command_id: str) -> bool:
    """C-1: 부수효과 전 commands.status를 pending→processing으로 조건부 전환.
    PostgREST PATCH는 return=representation이라 매칭+갱신된 row를 반환 — 빈 리스트면
    이미 다른 실행(재실행·동시 배치)이 클레임한 것 → 중복 처리 차단."""
    claimed = db_update("commands", {"status": "processing"}, id=command_id, status="pending")
    return bool(claimed)


def _save_item(
    owner_id: str,
    batch_id: str,
    item_type: str,
    material: str,
    quality: int,
    process_log: list,
    location: str = "warehouse",
    quantity: int = 1,
) -> None:
    """items 테이블 stack 저장. (owner, type, material, quality, location) 동일 시 quantity 합산.
    F-4(2026-05-30): items_unique 제약상 키당 1행만 가능 → 같은 슬롯이면 항상 병합(무제한 누적),
    없으면 새 row. stack_limit은 표시용. location은 'warehouse'(기본) 또는 'inventory'."""
    existing = db_select(
        "items",
        owner_id=owner_id,
        item_type=item_type,
        material=material,
        quality=quality,
        location=location,
    )
    if existing:
        db_update("items", {"quantity": existing[0]["quantity"] + quantity}, id=existing[0]["id"])
    else:
        db_insert(
            "items",
            {
                "owner_id": owner_id,
                "item_type": item_type,
                "material": material,
                "quality": quality,
                "quantity": quantity,
                "batch_id": batch_id,
                "process_log": process_log,
                "location": location,
            },
        )


# ── P4-1 거래 처리 ───────────────────────────────────────
# 성공 레벨 정렬 우선순위 (높을수록 먼저)
_TRADE_LEVEL_RANK = {
    "대성공": 5,
    "극단적_성공": 4,
    "어려운_성공": 3,
    "일반_성공": 2,
    "실패": 1,
    "대실패": 0,
}


def _process_trade_commands(batch_id: str, trade_commands: list, char_cache: dict) -> list:
    """거래 명령 일괄 처리 — buy/sell 분기.

    buy: 같은 (merchant, item_type, material) 그룹으로 묶어 TRPG 체결 (경쟁).
    sell: 경쟁 없음 — 아이템은 제출 시 인벤에서 이미 차감, 배치는 입금·우편함만.
    """
    buy_commands = [c for c in trade_commands if c.get("trade_action") == "buy"]
    sell_commands = [c for c in trade_commands if c.get("trade_action") == "sell"]
    results = _process_buy_commands(batch_id, buy_commands, char_cache)
    results += _process_sell_commands(batch_id, sell_commands, char_cache)
    return results


def _process_buy_commands(batch_id: str, buy_commands: list, char_cache: dict) -> list:
    """구매 명령 일괄 처리 — (merchant, item_type, material) 그룹별 TRPG 체결.
    재고 부족 시 부분 도착 + 차액 환불, 우편함 § 거래 탭 기록.
    """
    results: list = []
    # 그룹핑
    groups: dict[tuple, list] = defaultdict(list)
    for cmd in buy_commands:
        key = (cmd["merchant_id"], cmd.get("input_type"), cmd["target_material"])
        groups[key].append(cmd)

    for (merchant_id, item_type, material), cmds in groups.items():
        # 판정·정렬
        ranked: list[tuple] = []  # (rank, dex, random_key, cmd, char, roll, level)
        for cmd in cmds:
            char = char_cache.get(cmd["character_id"])
            if not char:
                continue
            dex = int(char.get("dexterity") or 0)
            roll = dice.roll_d100()
            level = dice.get_success_level(roll, dex, fumble_safe=False)
            # P6: 거래 buy 경쟁 실패 시 민첩 exp 누적
            if level in ("실패", "대실패"):
                _accumulate_exp(char, "stat", "dexterity")
            rank = _TRADE_LEVEL_RANK.get(level, 0)
            ranked.append((rank, dex, random.random(), cmd, char, roll, level))
        # 정렬: 성공 레벨 우선 (rank desc), 민첩 desc, 동률 random
        ranked.sort(key=lambda t: (-t[0], -t[1], t[2]))

        # 재고 차감 + 우편함
        merchant_rows = db_select("merchants", id=merchant_id)
        merchant_name = merchant_rows[0]["name"] if merchant_rows else "상인"

        inv_rows = db_select(
            "merchant_inventory", merchant_id=merchant_id, item_type=item_type, material=material
        )
        stock = int(inv_rows[0]["stock_current"]) if inv_rows else 0

        total_competitors = len(ranked)

        for idx, (_rank, dex, _rk, cmd, char, roll, level) in enumerate(ranked):
            # C-1: 부수효과 전 조건부 클레임 — 이미 처리된 명령이면 skip (재실행 이중 체결 차단)
            if not _claim_command(cmd["id"]):
                continue
            # D-1·D-2: 결제·환불 모두 제출 시점 동결가로 (없으면 배치 시세 fallback — 옛 row 호환)
            submit_price = cmd.get("unit_price_at_submit")
            unit_price = (
                int(submit_price)
                if submit_price is not None
                else get_current_price(item_type, material, merchant_id)
            )
            requested = int(cmd.get("quantity") or 0)
            received = min(requested, stock)
            stock -= received
            # C-2: merchant 재고를 명령 단위로 즉시 반영 (그룹 끝 일괄 쓰기 제거 — 중간 예외 시 정확)
            if inv_rows and received > 0:
                db_update(
                    "merchant_inventory",
                    {"stock_current": stock},
                    merchant_id=merchant_id,
                    item_type=item_type,
                    material=material,
                )
            refund = (requested - received) * unit_price
            # 환불은 users.gold로 되돌림 (캐릭터=user_id / NPC=owner_id) — A-1 원자 입금
            if refund > 0:
                user_id = _actor_user_id(char)
                if user_id:
                    adjust_gold(user_id, refund)

            # 인벤 도착
            if received > 0:
                _save_item(
                    owner_id=char["id"],
                    batch_id=batch_id,
                    item_type=item_type,
                    material=material,
                    quality=0,
                    process_log=None,
                    location="inventory",
                    quantity=received,
                )

            # 우편함 § 거래 탭
            item_label = _item_label(item_type, material)
            if received == requested:
                title = f"거래 성공 — {merchant_name}에서 {item_label} {received}개 구매"
            elif received > 0:
                title = f"거래 부분 성공 — {merchant_name}에서 {item_label} {received}/{requested}개 구매 (잔여 환불 {refund}량)"
            else:
                title = f"거래 실패 — {merchant_name} {item_label} 재고 소진 (환불 {refund}량)"

            body = {
                "type": "trade",
                "trade_action": "buy",
                "character_name": char.get("name"),
                "merchant_id": merchant_id,
                "merchant_name": merchant_name,
                "item_type": item_type,
                "material": material,
                "quantity_requested": requested,
                "quantity_received": received,
                "amount_paid": received * unit_price,
                "amount_refunded": refund,
                "dexterity_roll": {"roll": roll, "dex": dex, "level": level},
                "competition_rank": f"{idx + 1}/{total_competitors}",
                "unit_price": unit_price,
            }
            db_insert(
                "mailbox",
                {
                    "character_id": char["id"],
                    "command_id": cmd["id"],
                    "batch_id": batch_id,
                    "title": title,
                    "body": body,
                },
            )
            db_update("commands", {"status": "done", "batch_id": batch_id}, id=cmd["id"])
            # P6 S2-C: 거래 buy 명령 풀 정보 누적
            _collect_command(char, cmd, f"거래 buy: {merchant_name} {item_label} ×{requested}")
            results.append(
                {
                    "command_id": cmd["id"],
                    "character": char["name"],
                    "requested": requested,
                    "received": received,
                    "level": level,
                }
            )

    return results


def _process_sell_commands(batch_id: str, sell_commands: list, char_cache: dict) -> list:
    """판매 명령 처리 — 경쟁 없음. 아이템은 제출 시 인벤에서 이미 차감됨.
    배치는 자금 입금 + 우편함 § 거래 탭 기록만 담당.

    가격: 광물·주괴·합금주괴 = 오늘 시세 × 90% (고정상인 매입 마진).
          무기 = calculate_weapon_price (태수 정가 × 일일 변동).
    """
    results: list = []
    for cmd in sell_commands:
        char = char_cache.get(cmd["character_id"])
        if not char:
            continue
        # C-1: 부수효과 전 조건부 클레임
        if not _claim_command(cmd["id"]):
            continue
        item_type = cmd.get("input_type")
        material = cmd.get("target_material")
        quality = int(cmd.get("quality") or 0)
        quantity = int(cmd.get("quantity") or 0)
        merchant_id = cmd.get("merchant_id")

        merchant_rows = db_select("merchants", id=merchant_id) if merchant_id else []
        merchant_name = merchant_rows[0]["name"] if merchant_rows else "상인"

        if item_type in WEAPON_CODES:
            unit_price = calculate_weapon_price(item_type, material, quality)
        else:
            unit_price = int(get_current_price(item_type, material, merchant_id) * 0.9)
        total = unit_price * quantity

        user_id = _actor_user_id(char)
        if user_id and total > 0:
            adjust_gold(user_id, total)  # A-1: 원자 입금

        title = f"거래 성공 — {merchant_name}에 {_item_label(item_type, material, quality)} {quantity}개 판매 ({total}량 입금)"
        body = {
            "type": "trade",
            "trade_action": "sell",
            "character_name": char.get("name"),
            "merchant_id": merchant_id,
            "merchant_name": merchant_name,
            "item_type": item_type,
            "material": material,
            "quality": quality,
            "quantity": quantity,
            "unit_price": unit_price,
            "amount_received": total,
        }
        db_insert(
            "mailbox",
            {
                "character_id": char["id"],
                "command_id": cmd["id"],
                "batch_id": batch_id,
                "title": title,
                "body": body,
            },
        )
        db_update("commands", {"status": "done", "batch_id": batch_id}, id=cmd["id"])
        # P6 S2-C: 거래 sell 명령 풀 정보 누적
        _collect_command(
            char, cmd, f"거래 sell: {merchant_name} {_item_label(item_type, material, quality)}"
        )
        results.append(
            {
                "command_id": cmd["id"],
                "character": char["name"],
                "trade_action": "sell",
                "amount": total,
            }
        )
    return results


def _process_recovery(batch_id: str, cmd_char_ids: set) -> None:
    """배치 시작 시 부상·중상 회복 처리 (캐릭터·NPC 공통 — P5).
    - 부상: 이번 배치에 명령 미제출(cmd_char_ids에 없음) → 자동 회복
    - 중상: serious_injury_remaining 카운트다운, 0이 되면 회복
    """
    for table in ("characters", "npcs"):
        # 일반 부상 회복 (중상 아닌 부상)
        injured = db_select(table, is_injured=True, is_serious_injured=False)
        for actor in injured:
            if actor["id"] in cmd_char_ids:
                continue
            db_update(table, {"is_injured": False}, id=actor["id"])
            db_insert(
                "mailbox",
                {
                    "character_id": actor["id"],
                    "command_id": None,
                    "batch_id": batch_id,
                    "title": "부상 회복",
                    "body": {"type": "injury_recovery", "character_name": actor.get("name")},
                },
            )
        # 중상 카운트다운
        serious = db_select(table, is_serious_injured=True)
        for actor in serious:
            remaining = actor.get("serious_injury_remaining", 0) - 1
            if remaining <= 0:
                db_update(
                    table,
                    {
                        "is_serious_injured": False,
                        "is_injured": False,
                        "serious_injury_remaining": 0,
                    },
                    id=actor["id"],
                )
                db_insert(
                    "mailbox",
                    {
                        "character_id": actor["id"],
                        "command_id": None,
                        "batch_id": batch_id,
                        "title": "중상 회복",
                        "body": {"type": "serious_recovery", "character_name": actor.get("name")},
                    },
                )
            else:
                db_update(table, {"serious_injury_remaining": remaining}, id=actor["id"])


def _process_blacksmith_commands(
    batch_id: str,
    blacksmith_cmds: list,
    char_cache: dict,
    skills_cache: dict,
) -> list:
    pairs = [
        (cmd, char_cache[cmd["character_id"]])
        for cmd in blacksmith_cmds
        if char_cache.get(cmd["character_id"])
    ]
    # 배치 우선순위 = 인재관리 스킬 높은 actor 먼저 (2026-05-31 통솔 stat → 인재관리 skill 전환).
    # 스킬값은 skills_cache[actor_id]['talent_management'] (actor row엔 더는 leadership 컬럼 없음).
    pairs.sort(
        key=lambda x: int((skills_cache.get(x[1]["id"]) or {}).get("talent_management", 0)),
        reverse=True,
    )

    results = []
    for cmd, char in pairs:
        if not _claim_command(cmd["id"]):
            continue
        material = cmd.get("target_material", "raw_iron")
        input_type = cmd.get("input_type", "ore")
        work_type = cmd.get("work_type", "ingot")
        weapon_category = cmd.get("weapon_category")
        quantity = max(1, cmd.get("quantity", 1))

        # 스태미너는 명령 제출 시 이미 차감됨 (routers/command.py). 배치는 풀 회복만 담당.

        # P6 S2-B: 통솔 재굴림·페널티 — 명령서 전체(quantity) 공유. 토큰은 iter 간 이월.
        rerolls_remaining = int(cmd.get("rerolls_remaining") or 0)
        penalty_modifier = int(cmd.get("penalty_modifier") or 0)

        # 재료 품질 보너스(2026-06-01): 선택한 입력 등급 → 완성품 초기 total 보너스.
        # 명령당 고정값이라 루프 밖 1회 계산. ore/alloy 입력은 input_quality=0이라 보너스 0.
        input_quality = int(cmd.get("input_quality") or 0)
        quality_bonus = max(0, input_quality - 1)

        skills = skills_cache[char["id"]]
        iter_completed = 0
        last_quality = None
        # P5: 자원 차감/결과물 저장은 user 공유 창고에서
        actor_user_id = _actor_user_id(char)
        # 결과물 라벨 — iteration 무관 상수라 루프 밖에서 1회 계산 (재료부족 메일에서도 사용)
        material_name = MATERIALS.get(material, {}).get("name", material)
        if work_type == "weapon" and weapon_category:
            result_label = f"{material_name} {WEAPON_LABELS.get(weapon_category, weapon_category)}"
        elif work_type == "alloy":
            result_label = f"{material_name} 합금주괴"
        else:
            result_label = f"{material_name} 주괴"
        for iter_idx in range(quantity):
            # 입력 소재 1개 차감 (user 공유 창고)
            # B-1·B-2: 공유 창고 과다발주 방어 — 부족하면 결과물 생성 없이 안내 후 중단
            if input_type == "alloy":
                components = ALLOY_RECIPES.get(material, ())
                if all(_warehouse_quantity(actor_user_id, "ore", oc) >= 1 for oc in components):
                    for ore_code in components:
                        _consume_inventory(actor_user_id, "ore", ore_code)
                    consumed = True
                else:
                    consumed = False
            else:
                consumed = _consume_inventory(
                    actor_user_id, input_type, material, quality=input_quality
                )
            if not consumed:
                qty_suffix = f" ({iter_idx + 1}/{quantity})" if quantity > 1 else ""
                db_insert(
                    "mailbox",
                    {
                        "character_id": char["id"],
                        "command_id": cmd["id"],
                        "batch_id": batch_id,
                        "title": f"⚠ 대장간 — {result_label} 재료 부족으로 제작 중단{qty_suffix}",
                        "body": {
                            "type": "blacksmith_insufficient",
                            "character_name": char.get("name"),
                            "result_label": result_label,
                            "material": material,
                            "input_type": input_type,
                            "iteration": {"index": iter_idx + 1, "of": quantity},
                            "completed": iter_completed,
                        },
                    },
                )
                break

            # 매 iteration마다 mat_prof 재조회 (이전 iteration의 fumble 차감/성장 반영)
            mat_prof = _get_actor_mat_proficiency(char, material)
            prereq = PREREQUISITES.get(material)
            prereq_prof = _get_actor_mat_proficiency(char, prereq) if prereq else 0
            prereq_bonus = get_prerequisite_bonus(prereq_prof)
            flags = get_milestone_flags(mat_prof)
            # 광석·합금 제작 = 4공정 / 주괴·합금주괴 = 3공정
            steps = STEPS_ORE if input_type in ("ore", "alloy") else STEPS_INGOT

            body = blacksmith.process_blacksmith_command(
                character=char,
                steps=steps,
                skills=skills,
                mat_proficiency=mat_prof,
                prereq_bonus=prereq_bonus,
                is_injured=char.get("is_injured", False),
                mat_bonus_dice=flags["bonus_dice"],
                mat_fumble_safe=flags["fumble_safe"],
                rerolls_remaining=rerolls_remaining,
                penalty_modifier=penalty_modifier,
                quality_bonus=quality_bonus,
            )
            # P6 S2-B: iter에서 사용한 재굴림 반영 → 다음 iter로 이월
            rerolls_remaining = body.get("rerolls_remaining", rerolls_remaining)

            # P6: 소재 숙련도 — 대실패 차감 유지. 일반 실패 시 exp 누적 (다음 배치에 +1).
            # 성장 정보는 별도 "성장 보고" 메일로 통합 표시 (S2-C). body에는 박지 않음.
            mat_fumbles = body.get("mat_fumble_count", 0)
            new_mat_value = max(0, mat_prof - mat_fumbles)
            if new_mat_value != mat_prof:
                _upsert_actor_mat_proficiency(char, material, new_mat_value)
            if body["has_mat_failure"]:
                _accumulate_exp(char, "material", material)

            # P6: 기술 — 공정 일반 실패 skill별 exp 누적 (다음 배치에 +1)
            for skill_name in body["failed_craft_skills"]:
                current = skills.get(skill_name, 0)
                if current <= 0:
                    continue
                _accumulate_exp(char, "skill", skill_name, skills)

            # P6: step별 stat 트리거 / 부상 안전망 결과 → stat exp 누적
            # 단조→무력, 열처리→지략 (실패에서만 누적)
            # 운: 안전망 통과(downgraded) — feedback-growth-failure-only 예외 (대실패 흐름)
            # 건강: 안전망 실패(부상 발생, is_injured)
            for step_r in body["process_results"]:
                st = step_r.get("stat_trigger")
                if st and st["level"] in ("실패", "대실패"):
                    _accumulate_exp(char, "stat", st["stat_name"])
                for layer in ("craft", "material"):
                    safety = (step_r.get(layer) or {}).get("safety")
                    if not safety:
                        continue
                    if safety.get("downgraded"):
                        _accumulate_exp(char, "stat", "luck")
                    if safety.get("is_injured"):
                        _accumulate_exp(char, "stat", "health")

            body["iteration"] = {"index": iter_idx + 1, "of": quantity}
            body["character_name"] = char.get("name")
            body["input_quality"] = input_quality  # 우편함에 투입 재료 품질 등급 표시용

            # 부상 / 중상 DB 저장 (캐릭터·NPC 공통)
            actor_tbl = _actor_table(char)
            if body["cascade"]:
                db_update(
                    actor_tbl,
                    {
                        "is_serious_injured": True,
                        "serious_injury_remaining": 2,
                        "is_injured": True,
                    },
                    id=char["id"],
                )
                char["is_serious_injured"] = True
            elif body["is_injured"]:
                db_update(actor_tbl, {"is_injured": True}, id=char["id"])
                char["is_injured"] = True

            qty_suffix = f" ({iter_idx + 1}/{quantity})" if quantity > 1 else ""

            if body["cascade"]:
                title = f"⚠ 대장간 — {result_label} 제작 중 중상 (2배치 행동 불능){qty_suffix}"
            elif body["is_injured"]:
                title = f"⚠ 대장간 — {result_label} 제작 중 부상{qty_suffix}"
            else:
                title = f"대장간 — {result_label} 품질 {body['quality']}등급{qty_suffix}"
                # 결과 item_type — work_type별
                if work_type == "weapon" and weapon_category:
                    result_item_type = weapon_category
                    result_material = material  # raw_iron 무기 / bronze 무기 등
                elif work_type == "alloy":
                    result_item_type = "alloy_ingot"
                    result_material = material  # bronze 등 합금 코드
                else:
                    result_item_type = "ingot"
                    result_material = material
                # P5: 결과물도 user 공유 창고에 저장
                _save_item(
                    owner_id=actor_user_id,
                    batch_id=batch_id,
                    item_type=result_item_type,
                    material=result_material,
                    quality=body["quality"],
                    process_log=body["process_results"],
                )
            db_insert(
                "mailbox",
                {
                    "character_id": char["id"],
                    "command_id": cmd["id"],
                    "batch_id": batch_id,
                    "title": title,
                    "body": body,
                },
            )
            iter_completed += 1
            last_quality = body["quality"]

            # 부상/중상 발생 시 나머지 quantity 중단
            if body["is_injured"] or body["cascade"]:
                break

        db_update("commands", {"status": "done", "batch_id": batch_id}, id=cmd["id"])
        # P6 S2-C: 성장 보고 메일에 명령 풀 정보 누적 (통솔 토큰·페널티 표시용)
        qty_lbl = f" ×{quantity}" if quantity > 1 else ""
        _collect_command(char, cmd, f"{result_label}{qty_lbl}")
        results.append(
            {
                "command_id": cmd["id"],
                "character": char["name"],
                "quantity": quantity,
                "completed": iter_completed,
                "last_quality": last_quality,
            }
        )
    return results


# 'running' 배치가 이 시간을 넘기면 직전 실행의 하드 크래시 잔류로 보고 회수.
# 정상 예외는 run_batch의 except가 즉시 'failed' 처리하므로, 이 회수는 하드 킬(예외 없이 프로세스
# 종료) 대비용이다. 값은 worst-case 배치 처리 시간보다 충분히 커야 한다 — 진행 중인 정상 배치를
# stale로 오인하면(적대적 리뷰 지적) 부분 unique 가드가 풀려 두 배치가 동시 처리될 수 있다.
# (배치가 이 한도에 근접할 만큼 커지면 start 시각 대신 heartbeat 컬럼 기반 회수로 전환할 것.)
_STALE_RUNNING_MINUTES = 30


def _reclaim_stale_running() -> None:
    """직전 하드 크래시로 'running'이 잔류한 배치를 'failed'로 회수 (부분 unique 인덱스가 영구히
    막지 않도록). _STALE_RUNNING_MINUTES 초과한 것만 회수 — 진행 중인 정상 배치 오인 방지.
    scheduled_at 파싱 실패/누락 시 created_at fallback, 그래도 판단 불가면 stale로 간주."""
    running = db_select("batches", status="running")
    if not running:
        return
    cutoff = datetime.now(UTC) - timedelta(minutes=_STALE_RUNNING_MINUTES)
    for b in running:
        ts = b.get("scheduled_at") or b.get("created_at")
        dt = None
        if ts:
            try:
                dt = datetime.fromisoformat(ts)
            except ValueError:
                dt = None
        # 파싱 불가/누락은 stale로 간주(회수), 정상 파싱이면 5분 초과 시 회수
        if dt is None or dt < cutoff:
            db_update("batches", {"status": "failed"}, id=b["id"])


def run_batch() -> dict:
    global _collector_active
    # C-4/동시실행 가드: stale 'running' 회수 후, 부분 unique 인덱스(status='running')로 단일성 보장.
    # 이미 다른 배치가 running이면 INSERT가 409(unique 위반) → 거부 (멀티워커·중복 트리거 원자 안전).
    _reclaim_stale_running()
    now = datetime.now(UTC).isoformat()
    try:
        batch = db_insert("batches", {"scheduled_at": now, "status": "running"})
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 409:
            return {
                "batch_id": None,
                "skipped": "another batch already running",
                "processed_count": 0,
                "results": [],
            }
        raise
    batch_id = batch["id"]

    # P6 S2-C: 배치 처리 동안 actor별 성장 정보 누적
    _growth_collector.clear()
    _collector_active = True
    try:
        commands = db_select("commands", status="pending")
        cmd_char_ids = {cmd["character_id"] for cmd in commands}
        _process_recovery(batch_id, cmd_char_ids)

        if not commands:
            # P5: 명령 없어도 후보 풀은 갱신 (배치마다 후보 교체 정책)
            from engine.npcs import refresh_all_user_pools

            refresh_all_user_pools(batch_id=batch_id)
            db_update("batches", {"status": "done", "processed_at": now}, id=batch_id)
            return {"batch_id": batch_id, "processed_count": 0, "results": []}

        char_cache: dict = {}
        skills_cache: dict = {}
        for cmd in commands:
            cid = cmd["character_id"]
            if cid not in char_cache:
                actor = _fetch_actor(cid)
                char_cache[cid] = actor
                skills_cache[cid] = _fetch_actor_skills(actor) if actor else {}

        # E-3 안전망: actor 조회 실패(삭제된 캐릭터/NPC)인 pending 명령은 cancelled (영구 누수 차단)
        for cmd in commands:
            if char_cache.get(cmd["character_id"]) is None:
                db_update("commands", {"status": "cancelled"}, id=cmd["id"])

        # P6: 배치 시작 시점 — 이전 배치 누적 exp 도달 row 일괄 +1 적용
        # +1 발생 항목은 collector["growths"]에 자동 기록 (별도 mailbox INSERT 안 함)
        for cid, actor in char_cache.items():
            if not actor:
                continue
            _apply_growth_due(actor, skills_cache.get(cid, {}))

        # P4-1: command_type별 분기. 기본값 'blacksmith' — P3까지 NULL row 호환.
        blacksmith_cmds = [
            c for c in commands if (c.get("command_type") or "blacksmith") == "blacksmith"
        ]
        trade_cmds = [c for c in commands if c.get("command_type") == "trade"]

        results = _process_blacksmith_commands(batch_id, blacksmith_cmds, char_cache, skills_cache)

        # P4-1: 거래 명령 처리 (대장간 다음)
        if trade_cmds:
            trade_results = _process_trade_commands(batch_id, trade_cmds, char_cache)
            results.extend(trade_results)

        # 배치 완료 후처리 — C-3: 단계별 try/except 격리 (한 단계 실패가 나머지·배치 완료를
        # 막지 않게). 명령 자체는 이미 처리·done 상태. 후처리는 best-effort, 실패는 로깅.
        # 명령 제출 actor의 스태미너 풀 회복 (캐릭터·NPC)
        for cid, char in char_cache.items():
            if not char:
                continue
            try:
                db_update(_actor_table(char), {"stamina_current": char["health"] // 5}, id=cid)
            except Exception:
                logger.exception("배치 후처리 스태미너 회복 실패 actor=%s", cid)

        # NPC 수수료 정산 (선불 홀드 소진 또는 fallback 차감)
        try:
            _charge_npc_fees(batch_id, commands, char_cache)
        except Exception:
            logger.exception("배치 후처리 NPC 수수료 정산 실패")

        # 후보 풀 자동 갱신 (모든 유저)
        try:
            from engine.npcs import refresh_all_user_pools

            refresh_all_user_pools(batch_id=batch_id)
        except Exception:
            logger.exception("배치 후처리 후보 풀 갱신 실패")

        # actor별 성장 보고 메일 통합 INSERT
        try:
            _flush_growth_reports(batch_id, char_cache)
        except Exception:
            logger.exception("배치 후처리 성장 보고 실패")

        db_update(
            "batches",
            {"status": "done", "processed_at": datetime.now(UTC).isoformat()},
            id=batch_id,
        )
        return {"batch_id": batch_id, "processed_count": len(results), "results": results}
    except Exception:
        # C-4: 예외 시 'running'이 영구 잔류하지 않도록 'failed' 마킹 후 재전파
        db_update(
            "batches",
            {"status": "failed", "processed_at": datetime.now(UTC).isoformat()},
            id=batch_id,
        )
        raise
    finally:
        _collector_active = False


def _flush_growth_reports(batch_id: str, char_cache: dict) -> None:
    """배치 끝 시점에 actor별 성장 collector → mailbox INSERT (type=growth).
    누적·성장·명령 풀 정보가 모두 비어있으면 skip.
    """
    for actor_id, data in _growth_collector.items():
        has_acc = bool(data["stat_accs"] or data["skill_accs"] or data["material_accs"])
        has_growth = bool(data["growths"])
        has_cmds = bool(data["commands"])
        if not (has_acc or has_growth or has_cmds):
            continue
        actor = char_cache.get(actor_id) or {}
        name = data["name"] or actor.get("name", "")
        growth_count = len(data["growths"])
        if growth_count:
            title = f"{name} — 성장 보고 (+1 발생 {growth_count}건)"
        else:
            title = f"{name} — 성장 보고 (경험치 누적)"
        db_insert(
            "mailbox",
            {
                "character_id": actor_id,
                "command_id": None,
                "batch_id": batch_id,
                "title": title,
                "body": {
                    "type": "growth",
                    "character_name": name,
                    "actor_kind": data["kind"],
                    "stat_accs": data["stat_accs"],
                    "skill_accs": data["skill_accs"],
                    "material_accs": data["material_accs"],
                    "growths": data["growths"],
                    "commands": data["commands"],
                },
            },
        )


def _charge_npc_fees(batch_id: str, commands: list, char_cache: dict) -> None:
    """배치 끝 NPC 수수료 정산 (F-5 선불 홀드 모델).
    - fee_held > 0: 발주 시 이미 선불 차감됨 → 재차감 없이 0으로 리셋(정산, 다음 창 대비).
    - fee_held == 0인데 명령 수행(레거시 pending·홀드 실패 등): 안전망으로 지금 차감
      (adjust_gold — 잔액 부족이면 None이라 무차감. 홀드 모델에선 거의 발생 안 함).
    NPC별 1회 (한 배치 여러 명령이어도 수수료 1회)."""
    npc_ids_in_batch = {
        cmd["character_id"]
        for cmd in commands
        if (a := char_cache.get(cmd["character_id"])) and _actor_kind(a) == "npc"
    }
    for npc_id in npc_ids_in_batch:
        npc = char_cache.get(npc_id)
        if not npc:
            continue
        fee = int(npc.get("fee_per_batch") or 0)
        if fee <= 0:
            continue
        uid = _actor_user_id(npc)
        if uid:
            # 원자 정산: fee_held>0이면 리셋(선불 소진, 무차감), 아니면 fallback 차감 (NPC 행 FOR UPDATE)
            # C-3: NPC별 격리 — 한 NPC 정산 실패가 나머지 정산을 막지 않게
            try:
                settle_npc_fee(npc_id, uid, fee)
            except Exception:
                logger.exception("NPC 수수료 정산 실패 npc=%s", npc_id)
