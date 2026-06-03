MATERIALS = {
    "raw_iron": {"name": "생철광", "rarity": 1, "initial": 30, "ingot": "raw_iron_ingot"},
    "magnetite": {"name": "자철석", "rarity": 3, "initial": 0, "ingot": "magnetite_ingot"},
    "chalcopyrite": {"name": "황동광", "rarity": 1, "initial": 20, "ingot": "copper_ingot"},
    "malachite": {"name": "공작석", "rarity": 2, "initial": 5, "ingot": "malachite_ingot"},
    "cassiterite": {"name": "석석", "rarity": 3, "initial": 0, "ingot": "tin_ingot"},
    "galena": {"name": "방연석", "rarity": 2, "initial": 5, "ingot": "lead_ingot"},
    "placer_gold": {"name": "사금", "rarity": 4, "initial": 0, "ingot": "gold_ingot"},
    "silver_ore": {"name": "은광석", "rarity": 3, "initial": 0, "ingot": "silver_ingot"},
    "meteorite_iron": {"name": "운석철", "rarity": 5, "initial": 0, "ingot": "meteorite_ingot"},
    "cinnabar": {"name": "단사", "rarity": 4, "initial": 0, "ingot": None},
    "bronze": {"name": "청동", "rarity": 2, "initial": 0, "ingot": "bronze_ingot"},
    "steel": {"name": "강철", "rarity": 3, "initial": 0, "ingot": "steel_ingot"},
    "white_copper": {"name": "백동", "rarity": 3, "initial": 0, "ingot": "white_copper_ingot"},
    "heaven_iron": {"name": "천철", "rarity": 5, "initial": 0, "ingot": "heaven_iron_ingot"},
}

# 선행 소재: 해당 소재 작업 시 선행 소재 숙련도의 10%를 보너스로 받음
PREREQUISITES = {
    "magnetite": "raw_iron",
    "galena": "magnetite",
    "cinnabar": "galena",
    "meteorite_iron": "magnetite",
    "steel": "magnetite",
    "heaven_iron": "steel",
    "malachite": "chalcopyrite",
    "cassiterite": "chalcopyrite",
    "silver_ore": "malachite",
    "placer_gold": "silver_ore",
    "bronze": "cassiterite",
    "white_copper": "silver_ore",
}

ALLOY_RECIPES = {
    "bronze": ("chalcopyrite", "cassiterite"),
    "steel": ("raw_iron", "magnetite"),
    "white_copper": ("chalcopyrite", "silver_ore"),
    "heaven_iron": ("magnetite", "meteorite_iron"),
}

# 기술치 초기값 — 캐릭터 생성 시 character_skills에 INSERT
SKILL_DEFINITIONS = {
    "smelting": 15,  # 제련
    "forging": 20,  # 단조
    "heat_treat": 15,  # 열처리
    "finishing": 10,  # 마감
    "appraisal": 0,  # 감정 (추후 활성)
    # 인재관리 — 대장간 기술과 별개의 사업 무관 공용 스킬. NPC 명령 발주 재굴림·배치 우선순위·성장 트리거.
    # 통솔 스탯에서 이관 (2026-05-31). NPC 초기값은 engine/npcs.py 에서 10 고정.
    "talent_management": 20,  # 인재관리
}

# 광석 시작: 제련 → 단조 → 열처리 → 마감
STEPS_ORE = [
    {"name": "제련", "skill_name": "smelting"},
    {"name": "단조", "skill_name": "forging"},
    {"name": "열처리", "skill_name": "heat_treat"},
    {"name": "마감", "skill_name": "finishing"},
]

# 주괴 시작: 단조 → 열처리 → 마감
STEPS_INGOT = [
    {"name": "단조", "skill_name": "forging"},
    {"name": "열처리", "skill_name": "heat_treat"},
    {"name": "마감", "skill_name": "finishing"},
]


def get_prerequisite_bonus(prereq_value: int) -> int:
    return prereq_value // 10


def get_milestone_flags(proficiency: int) -> dict:
    return {
        "bonus_dice": 1 if proficiency >= 75 else 0,
        "fumble_safe": proficiency >= 85,
        "auto_unlock": proficiency >= 95,
    }


# ── P2-6: 스태미너 소모량 ───────────────────────────────
# alloy: 합금주괴 제작 = 광석 4공정 1번 (광석 2종 차감) → ORE와 동일 비용
# trade: P4-1 거래 명령 (제출 시 즉시 1 차감)
STAMINA_COST = {"ore": 4, "ingot": 3, "alloy_ingot": 3, "alloy": 4, "trade": 1}


def get_stamina_cost(input_type: str) -> int:
    return STAMINA_COST.get(input_type, 0)


def get_trade_stamina_cost(quantity: int) -> int:
    """거래(구매·판매) 스태미너 — 명령 1건당 고정 1 (수량 무관, 2026-06-01).
    대량 판매가 '1개당 1'이라 비현실적이던 문제 해소. 모델 재조정은 이 한 곳만 수정.
    진짜 물류 throttle은 P7 운송수단(가방·수레) stack 게이팅으로 별도 도입."""
    return 1 if quantity > 0 else 0


# ── P2-5: 소재 분류 (드롭다운용) ────────────────────────
ORE_CODES = [code for code in MATERIALS if code not in ALLOY_RECIPES]
ALLOY_CODES = list(ALLOY_RECIPES.keys())


# ── P3-2: 무기 카테고리 ─────────────────────────────────
WEAPON_CODES = ["dagger", "greatsword", "longsword", "shortspear", "longspear", "axe", "greataxe"]

WEAPON_LABELS = {
    "dagger": "단검",
    "greatsword": "대검",
    "longsword": "장검",
    "shortspear": "단창",
    "longspear": "장창",
    "axe": "도끼",
    "greataxe": "대부",
}

# 무기↔소재 매핑 (wiki 완성품_무기.md 큐레이션 그대로 — 무기당 6종: 광석/주괴 4 + 합금 2)
WEAPON_RECIPES = {
    "dagger": ["raw_iron", "chalcopyrite", "silver_ore", "placer_gold", "bronze", "white_copper"],
    "greatsword": ["raw_iron", "magnetite", "meteorite_iron", "galena", "steel", "heaven_iron"],
    "longsword": ["raw_iron", "magnetite", "silver_ore", "malachite", "steel", "white_copper"],
    "shortspear": ["raw_iron", "chalcopyrite", "cassiterite", "galena", "bronze", "white_copper"],
    "longspear": ["raw_iron", "magnetite", "cassiterite", "malachite", "steel", "bronze"],
    "axe": ["raw_iron", "magnetite", "galena", "malachite", "steel", "heaven_iron"],
    "greataxe": ["magnetite", "meteorite_iron", "galena", "raw_iron", "steel", "heaven_iron"],
}

# 무기 체력 가산: 가벼움 +0 / 보통 +1 / 대형 +2
WEAPON_STAMINA_BONUS = {
    "dagger": 0,
    "shortspear": 0,
    "longsword": 1,
    "axe": 1,
    "greatsword": 2,
    "longspear": 2,
    "greataxe": 2,
}


def get_weapon_stamina_cost(weapon_code: str, input_type: str) -> int:
    """무기 제작 스태미너: 기본(input_type) + 무기 가산."""
    return get_stamina_cost(input_type) + WEAPON_STAMINA_BONUS.get(weapon_code, 0)


def get_material_status(material: str, mat_proficiency: dict) -> str:
    """소재 잠금 상태 판정.
    - "unlocked": 직접 숙련도 > 0
    - "temp":     직접 숙련도 0 + 선행 보너스 ≥ 1 (임시 해금)
    - "locked":   둘 다 0
    """
    if mat_proficiency.get(material, 0) > 0:
        return "unlocked"
    prereq = PREREQUISITES.get(material)
    if prereq and get_prerequisite_bonus(mat_proficiency.get(prereq, 0)) >= 1:
        return "temp"
    return "locked"


# ── P4-1: 시장 가격 매트릭스 (wiki 잠정 — 게임 플레이 후 조정) ──────────
# 광물 정가 (희귀도별, 량 단위)
ORE_BASE_PRICES = {1: 100, 2: 250, 3: 600, 4: 1500, 5: 5000}

# 주괴 정가 = 광물 × 3 (희귀도별)
INGOT_BASE_PRICES = {r: p * 3 for r, p in ORE_BASE_PRICES.items()}

# 합금주괴 정가 (단일 매핑)
ALLOY_INGOT_BASE_PRICES = {
    "bronze_ingot": 4200,
    "steel_ingot": 4200,
    "white_copper_ingot": 4200,
    "heaven_iron_ingot": 33600,
}

# 무기 base 가격 (카테고리별)
WEAPON_CATEGORY_BASE_PRICES = {
    "dagger": 200,
    "shortspear": 250,
    "longsword": 350,
    "axe": 350,
    "longspear": 450,
    "greatsword": 500,
    "greataxe": 600,
}

# 소재 등급 배율 (무기 가격 계산용)
# 광석/주괴 소재: 희귀도 1~5 → ×1 / ×1.5 / ×3 / ×6 / ×10
# 합금주괴 소재: bronze/steel/white_copper ×6, heaven_iron ×20
MATERIAL_TIER_MULTIPLIERS = {1: 1.0, 2: 1.5, 3: 3.0, 4: 6.0, 5: 10.0}
ALLOY_TIER_MULTIPLIERS = {
    "bronze": 6.0,
    "steel": 6.0,
    "white_copper": 6.0,
    "heaven_iron": 20.0,
}

# 품질 배율 (무기 가격)
QUALITY_MULTIPLIERS = {1: 0.5, 2: 0.8, 3: 1.0, 4: 1.5, 5: 2.5}


def get_base_price(item_type: str, material: str) -> int:
    """광석/주괴/합금주괴의 정가(량). 무기는 calculate_weapon_base_price() 사용."""
    info = MATERIALS.get(material)
    if not info:
        return 0
    if item_type == "ore":
        return ORE_BASE_PRICES.get(info["rarity"], 0)
    if item_type == "ingot":
        return INGOT_BASE_PRICES.get(info["rarity"], 0)
    if item_type == "alloy_ingot":
        ingot_code = info.get("ingot")
        return ALLOY_INGOT_BASE_PRICES.get(ingot_code, 0)
    return 0


def calculate_weapon_base_price(weapon_category: str, material: str, quality: int) -> int:
    """무기 정가 = base × 소재 등급 × 품질 (정수 내림)."""
    base = WEAPON_CATEGORY_BASE_PRICES.get(weapon_category, 0)
    if material in ALLOY_TIER_MULTIPLIERS:
        tier = ALLOY_TIER_MULTIPLIERS[material]
    else:
        info = MATERIALS.get(material)
        tier = MATERIAL_TIER_MULTIPLIERS.get(info["rarity"], 0) if info else 0
    quality_mult = QUALITY_MULTIPLIERS.get(quality, 0)
    return int(base * tier * quality_mult)
