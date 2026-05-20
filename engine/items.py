"""아이템 인벤토리 — stack 시스템 상수.

(owner_id, item_type, material, quality) 동일 시 한 row의 quantity++,
상한 초과 시 새 row 생성 (MMO 표준 패턴).
"""

STACK_LIMITS = {
    "ore":         999,  # 원료/광석
    "ingot":        99,  # 주괴
    "alloy_ingot":  50,  # 합금주괴
    "weapon":       99,  # 무기 (P2)
    "armor":        99,  # 방어구 (P2)
}

ITEM_TYPE_LABELS = {
    "ore":         "광석",
    "ingot":       "주괴",
    "alloy_ingot": "합금주괴",
    "weapon":      "무기",
    "armor":       "방어구",
}

DEFAULT_STACK_LIMIT = 99
