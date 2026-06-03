"""P4-1 시장 시스템 — 시세·재고·일일 리셋·시드.

세션 3-b 정정 (2026-05-23) 모델:
- 가격: random walk (어제 가격 기준) + 재고 압박(stock pressure). 상인별 σ·clip·k 차등
  · 관시: σ=0.025, clip=±5%, k=2%, 캡 70~130%
  · 유랑: σ=0.05,  clip=±10%, k=3%, 캡 50~150%
  · 태수: σ=0.025, clip=±5%, k=0% (재고 없음), 캡 70~130%
- 재고: 관시는 누적(어제분 + stock_max×10~25% 보충, stock_max 캡),
        유랑은 매일 신규 30~70% (라인업이 매일 바뀜).
- 라인업: 관시 ★1 자원만(4종), 유랑 10종 가중 무작위(RARITY_WEIGHTS).

매일 reset_daily_market(): 어제 가격·재고 조회 → 재고 갱신 → 가격 갱신 (재고 압박 반영) 순서.
ensure_market_seeded()는 main.py startup에서 호출, 멱등.
"""

from __future__ import annotations

import logging
import random
from datetime import date, timedelta

from database import db_delete, db_insert_many, db_select, db_upsert
from engine.materials import (
    ALLOY_TIER_MULTIPLIERS,
    MATERIAL_TIER_MULTIPLIERS,
    MATERIALS,
    QUALITY_MULTIPLIERS,
    WEAPON_CATEGORY_BASE_PRICES,
    WEAPON_RECIPES,
    calculate_weapon_base_price,
    get_base_price,
)

logger = logging.getLogger(__name__)


# ── 재고 상한 ─────────────────────────────────────────────
_STOCK_MAX_ORE_BY_RARITY = {1: 100, 2: 50, 3: 30, 4: 10, 5: 5}
_STOCK_MAX_INGOT_BY_RARITY = {1: 50, 2: 25, 3: 15, 4: 5, 5: 3}
_STOCK_MAX_ALLOY = {
    "bronze_ingot": 10,
    "steel_ingot": 10,
    "white_copper_ingot": 10,
    "heaven_iron_ingot": 3,
}


# ── 상인별 가격 파라미터 ──────────────────────────────────
MERCHANT_PRICE_PARAMS = {
    "fixed_official": {
        "sigma": 0.025,
        "clip": 0.05,
        "pressure_k": 0.015,
        "floor_ratio": 0.70,
        "ceil_ratio": 1.30,
    },
    "random_caravan": {
        "sigma": 0.05,
        "clip": 0.10,
        "pressure_k": 0.03,
        "floor_ratio": 0.50,
        "ceil_ratio": 1.50,
    },
    "officer_buyer": {
        "sigma": 0.025,
        "clip": 0.05,
        "pressure_k": 0.0,  # 재고 없음
        "floor_ratio": 0.70,
        "ceil_ratio": 1.30,
    },
}


# ── 유랑상단 라인업 가중치 (희귀도별) ──────────────────────
# ★5 자원당 등장 빈도 ~10% 목표. 합금주괴는 추가 -1.5 패널티.
RARITY_WEIGHTS = {1: 6.0, 2: 5.0, 3: 3.0, 4: 1.5, 5: 0.8}
RANDOM_CARAVAN_SIZE = 10


# ── 재고 보충률 ──────────────────────────────────────────
FIXED_REFILL_MIN = 0.10  # 관시 누적 보충 = stock_max × Uniform(0.10, 0.25)
FIXED_REFILL_MAX = 0.25
CARAVAN_REFILL_MIN = 0.30  # 유랑 매일 신규 = stock_max × Uniform(0.30, 0.70)
CARAVAN_REFILL_MAX = 0.70
FIRST_DAY_FILL_MIN = 0.30  # 첫날(어제 데이터 없음) 관시 — Uniform(0.30, 0.70)
FIRST_DAY_FILL_MAX = 0.70


# ── 시세 조회·계산 ──────────────────────────────────────
def get_current_price(
    item_type: str, material: str, merchant_id: str, today: date | None = None
) -> int:
    """오늘 시세 조회 — 상인별 독립.
    없으면 정가 fallback (광물/주괴/합금주괴) 또는 0 (무기는 calculate_weapon_price 사용)."""
    today = today or date.today()
    rows = db_select(
        "market_prices",
        date=today.isoformat(),
        merchant_id=merchant_id,
        item_type=item_type,
        material=material,
    )
    if rows:
        return int(rows[0]["current_price"])
    if item_type in {"ore", "ingot", "alloy_ingot"}:
        return get_base_price(item_type, material)
    return 0


def calculate_weapon_price(
    weapon_category: str, material: str, quality: int, today: date | None = None
) -> int:
    """무기 가격 = 태수 시세 × 품질 배율. 시세 없으면 정가 fallback."""
    today = today or date.today()
    quality_mult = QUALITY_MULTIPLIERS.get(quality, 0)
    officer = _merchant_by_code("officer_buyer")
    if officer:
        rows = db_select(
            "market_prices",
            date=today.isoformat(),
            merchant_id=officer["id"],
            item_type=weapon_category,
            material=material,
        )
        if rows:
            return int(int(rows[0]["current_price"]) * quality_mult)
    return calculate_weapon_base_price(weapon_category, material, quality)


# ── 가격 모델 (random walk + stock pressure) ──────────────
def _walk_step(sigma: float, clip: float) -> float:
    """random walk 단일 step — N(0, σ) clipped to ±clip."""
    delta = random.gauss(0, sigma)
    return max(-clip, min(clip, delta))


def _stock_pressure(stock: int, stock_max: int, k: float) -> float:
    """재고 압박 항. 재고 가득(100%): -k, 빈약(0%): +k, 중앙(50%): 0."""
    if stock_max <= 0 or k <= 0:
        return 0.0
    fill = stock / stock_max
    return -k * (fill - 0.5) * 2


def _next_price(
    prev_price: int,
    base_price: int,
    stock: int,
    stock_max: int,
    sigma: float,
    clip: float,
    pressure_k: float,
    floor_ratio: float,
    ceil_ratio: float,
) -> int:
    """다음날 가격 = 어제 가격 × (1 + random walk + 재고 압박), 정가 대비 캡."""
    walk = _walk_step(sigma, clip)
    pressure = _stock_pressure(stock, stock_max, pressure_k)
    raw = prev_price * (1 + walk + pressure)
    return max(int(base_price * floor_ratio), min(int(base_price * ceil_ratio), int(raw)))


# ── 재고 정책 ────────────────────────────────────────────
def _stock_max_for(item_type: str, material: str) -> int:
    info = MATERIALS.get(material)
    if not info:
        return 0
    if item_type == "ore":
        return _STOCK_MAX_ORE_BY_RARITY.get(info["rarity"], 0)
    if item_type == "ingot":
        return _STOCK_MAX_INGOT_BY_RARITY.get(info["rarity"], 0)
    if item_type == "alloy_ingot":
        return _STOCK_MAX_ALLOY.get(info.get("ingot"), 0)
    return 0


def _restock_fixed(prev_stock: int | None, stock_max: int) -> int:
    """관시 재고 — 어제분 + 보충, stock_max 캡. 첫날(prev=None)은 30~70% 무작위."""
    if stock_max <= 0:
        return 0
    if prev_stock is None:
        return int(stock_max * random.uniform(FIRST_DAY_FILL_MIN, FIRST_DAY_FILL_MAX))
    refill = int(stock_max * random.uniform(FIXED_REFILL_MIN, FIXED_REFILL_MAX))
    return min(stock_max, prev_stock + refill)


def _restock_caravan(stock_max: int) -> int:
    """유랑 재고 — 매일 30~70% 신규 (라인업 매일 바뀌므로 누적 안 함)."""
    if stock_max <= 0:
        return 0
    return int(stock_max * random.uniform(CARAVAN_REFILL_MIN, CARAVAN_REFILL_MAX))


# ── 라인업 ────────────────────────────────────────────────
def _fixed_official_lineup() -> list[tuple[str, str]]:
    """관시 행상: ★1 자원만 (광석·주괴) — 입문용 고정 상점.
    ★1 = raw_iron, chalcopyrite. 합금주괴는 ★1이 없어 자동 제외."""
    lineup: list[tuple[str, str]] = []
    for code, info in MATERIALS.items():
        if info["rarity"] != 1:
            continue
        lineup.append(("ore", code))
        if info.get("ingot"):
            lineup.append(("ingot", code))
    return lineup


def _random_caravan_lineup() -> list[tuple[str, str]]:
    """유랑상단: 광석/주괴/합금주괴 풀에서 10종 가중 무작위.
    RARITY_WEIGHTS로 희귀도별 차등 (★5는 ~10% 등장 목표). 합금주괴는 추가 -1.5 패널티."""
    pool: list[tuple[tuple[str, str], float]] = []
    for code, info in MATERIALS.items():
        weight = RARITY_WEIGHTS.get(info["rarity"], 1.0)
        pool.append((("ore", code), weight))
        if info.get("ingot"):
            if code in ALLOY_TIER_MULTIPLIERS:
                pool.append((("alloy_ingot", code), max(0.1, weight - 1.5)))
            else:
                pool.append((("ingot", code), max(0.1, weight - 0.5)))
    chosen: list[tuple[str, str]] = []
    while len(chosen) < RANDOM_CARAVAN_SIZE and pool:
        keys = [k for k, _ in pool]
        weights = [w for _, w in pool]
        pick = random.choices(keys, weights=weights, k=1)[0]
        chosen.append(pick)
        pool = [(k, w) for k, w in pool if k != pick]
    return chosen


def _merchant_by_code(code: str) -> dict | None:
    rows = db_select("merchants", code=code)
    return rows[0] if rows else None


# ── 가격 시드 대상 (상인별 라인업의 base) ─────────────────
def _items_for_merchant(merchant_row: dict) -> list[tuple[str, str, int]]:
    """상인이 가격을 매겨야 하는 (item_type, material, base_price) 목록.

    - fixed (관시): _fixed_official_lineup() — ★1 광석+주괴
    - random (유랑): 오늘 merchant_inventory에 깔린 라인업 (restock 완료 후 조회)
    - officer_buyer (태수): 모든 무기 (weapon_category, material) 조합
    """
    code = merchant_row.get("code")
    items: list[tuple[str, str, int]] = []

    if code == "fixed_official":
        for item_type, material in _fixed_official_lineup():
            base = get_base_price(item_type, material)
            if base:
                items.append((item_type, material, base))
    elif code == "random_caravan":
        rows = db_select("merchant_inventory", merchant_id=merchant_row["id"])
        for r in rows:
            base = get_base_price(r["item_type"], r["material"])
            if base:
                items.append((r["item_type"], r["material"], base))
    elif code == "officer_buyer":
        for wc, mats in WEAPON_RECIPES.items():
            base_wc = WEAPON_CATEGORY_BASE_PRICES.get(wc, 0)
            for m in mats:
                if m in ALLOY_TIER_MULTIPLIERS:
                    tier = ALLOY_TIER_MULTIPLIERS[m]
                else:
                    info = MATERIALS.get(m, {})
                    tier = MATERIAL_TIER_MULTIPLIERS.get(info.get("rarity", 0), 0)
                if base_wc and tier:
                    items.append((wc, m, int(base_wc * tier)))
    return items


# ── 일일 리셋 — 재고 → 가격 (어제 가격·재고 기반) ──────────
def reset_daily_market(today: date | None = None) -> dict:
    """매일 10시 배치 직후 호출. 흐름:
    1. 어제 가격·재고 일괄 조회 (랜덤워크·재고 누적 기반)
    2. 라인업·재고 갱신: 관시 누적(prev + 보충, cap), 유랑 매일 신규
    3. 가격 갱신: 어제 가격 + walk + 새 재고 압박, 정가 대비 캡
    """
    today = today or date.today()
    today_str = today.isoformat()
    yesterday_str = (today - timedelta(days=1)).isoformat()

    # 어제 가격·재고
    prev_price_rows = db_select("market_prices", date=yesterday_str)
    prev_prices = {
        (r["merchant_id"], r["item_type"], r["material"]): int(r["current_price"])
        for r in prev_price_rows
    }
    prev_stock_rows = db_select("merchant_inventory")
    prev_stocks = {
        (r["merchant_id"], r["item_type"], r["material"]): int(r["stock_current"])
        for r in prev_stock_rows
    }

    merchants = db_select("merchants")
    summary = {"prices": 0, "fixed": 0, "random": 0, "lineup_replaced": False}
    new_stocks: dict[tuple, int] = {}

    # 1. 재고 갱신
    fixed_rows = []
    for m in merchants:
        code = m["code"]
        if code == "fixed_official":
            for it, mat in _fixed_official_lineup():
                smax = _stock_max_for(it, mat)
                prev = prev_stocks.get((m["id"], it, mat))
                stock = _restock_fixed(prev, smax)
                new_stocks[(m["id"], it, mat)] = stock
                fixed_rows.append(
                    {
                        "merchant_id": m["id"],
                        "item_type": it,
                        "material": mat,
                        "stock_current": stock,
                        "stock_max": smax,
                        "last_restocked_at": today_str,
                    }
                )
            summary["fixed"] = len(fixed_rows)
        elif code == "random_caravan":
            db_delete("merchant_inventory", merchant_id=m["id"])
            caravan_rows = []
            for it, mat in _random_caravan_lineup():
                smax = _stock_max_for(it, mat)
                stock = _restock_caravan(smax)
                new_stocks[(m["id"], it, mat)] = stock
                caravan_rows.append(
                    {
                        "merchant_id": m["id"],
                        "item_type": it,
                        "material": mat,
                        "stock_current": stock,
                        "stock_max": smax,
                        "last_restocked_at": today_str,
                    }
                )
            if caravan_rows:
                db_insert_many("merchant_inventory", caravan_rows)
            summary["random"] = len(caravan_rows)
            summary["lineup_replaced"] = True
        # officer_buyer: 재고 없음 (무기 매입 무한)

    if fixed_rows:
        db_upsert("merchant_inventory", fixed_rows, on_conflict="merchant_id,item_type,material")

    # 2. 가격 갱신 — 어제 가격 + walk + 새 재고 압박
    price_rows = []
    for m in merchants:
        params = MERCHANT_PRICE_PARAMS.get(m["code"])
        if not params:
            continue
        for it, mat, base in _items_for_merchant(m):
            prev = prev_prices.get((m["id"], it, mat), base)  # 첫날 fallback
            stock = new_stocks.get((m["id"], it, mat), 0)
            smax = _stock_max_for(it, mat)
            new_price = _next_price(
                prev,
                base,
                stock,
                smax,
                sigma=params["sigma"],
                clip=params["clip"],
                pressure_k=params["pressure_k"],
                floor_ratio=params["floor_ratio"],
                ceil_ratio=params["ceil_ratio"],
            )
            price_rows.append(
                {
                    "date": today_str,
                    "merchant_id": m["id"],
                    "item_type": it,
                    "material": mat,
                    "current_price": new_price,
                    "base_price": base,
                }
            )

    if price_rows:
        db_upsert("market_prices", price_rows, on_conflict="date,merchant_id,item_type,material")
    summary["prices"] = len(price_rows)

    logger.info(
        "reset_daily_market: %d 시세 갱신 / 고정 %d, 유랑 %d",
        summary["prices"],
        summary["fixed"],
        summary["random"],
    )
    return summary


def ensure_market_seeded(today: date | None = None) -> dict:
    """startup 시점에 1회 호출. 오늘 시세 없으면 자동 시드. 멱등."""
    today = today or date.today()
    today_str = today.isoformat()
    existing_prices = db_select("market_prices", date=today_str)
    if existing_prices:
        # 이미 시드됨 — 재고만 점검
        fixed = _merchant_by_code("fixed_official")
        if fixed:
            fixed_stock = db_select("merchant_inventory", merchant_id=fixed["id"])
            if not fixed_stock:
                logger.info("market 재고 비어있음 — reset 호출")
                return reset_daily_market(today)
        return {"action": "skip", "reason": "already seeded today"}

    logger.info("오늘 시세 없음 — reset_daily_market 자동 시드")
    return reset_daily_market(today)
