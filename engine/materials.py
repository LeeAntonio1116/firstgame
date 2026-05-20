MATERIALS = {
    "raw_iron":       {"name": "생철광", "rarity": 1, "initial": 30, "ingot": "raw_iron_ingot"},
    "magnetite":      {"name": "자철석", "rarity": 3, "initial": 0,  "ingot": "magnetite_ingot"},
    "chalcopyrite":   {"name": "황동광", "rarity": 1, "initial": 20, "ingot": "copper_ingot"},
    "malachite":      {"name": "공작석", "rarity": 2, "initial": 5,  "ingot": "malachite_ingot"},
    "cassiterite":    {"name": "석석",   "rarity": 3, "initial": 0,  "ingot": "tin_ingot"},
    "galena":         {"name": "방연석", "rarity": 2, "initial": 5,  "ingot": "lead_ingot"},
    "placer_gold":    {"name": "사금",   "rarity": 4, "initial": 0,  "ingot": "gold_ingot"},
    "silver_ore":     {"name": "은광석", "rarity": 3, "initial": 0,  "ingot": "silver_ingot"},
    "meteorite_iron": {"name": "운석철", "rarity": 5, "initial": 0,  "ingot": "meteorite_ingot"},
    "cinnabar":       {"name": "단사",   "rarity": 4, "initial": 0,  "ingot": None},
    "bronze":         {"name": "청동",   "rarity": 2, "initial": 0,  "ingot": "bronze_ingot"},
    "steel":          {"name": "강철",   "rarity": 3, "initial": 0,  "ingot": "steel_ingot"},
    "white_copper":   {"name": "백동",   "rarity": 3, "initial": 0,  "ingot": "white_copper_ingot"},
    "heaven_iron":    {"name": "천철",   "rarity": 5, "initial": 0,  "ingot": "heaven_iron_ingot"},
}

# 선행 소재: 해당 소재 작업 시 선행 소재 숙련도의 10%를 보너스로 받음
PREREQUISITES = {
    "magnetite":      "raw_iron",
    "galena":         "magnetite",
    "cinnabar":       "galena",
    "meteorite_iron": "magnetite",
    "steel":          "magnetite",
    "heaven_iron":    "steel",
    "malachite":      "chalcopyrite",
    "cassiterite":    "chalcopyrite",
    "silver_ore":     "malachite",
    "placer_gold":    "silver_ore",
    "bronze":         "cassiterite",
    "white_copper":   "silver_ore",
}

ALLOY_RECIPES = {
    "bronze":       ("chalcopyrite", "cassiterite"),
    "steel":        ("raw_iron",     "magnetite"),
    "white_copper": ("chalcopyrite", "silver_ore"),
    "heaven_iron":  ("magnetite",    "meteorite_iron"),
}

# 기술치 초기값 — 캐릭터 생성 시 character_skills에 INSERT
SKILL_DEFINITIONS = {
    "smelting":   15,  # 제련
    "forging":    20,  # 단조
    "heat_treat": 15,  # 열처리
    "finishing":  10,  # 마감
    "appraisal":   0,  # 감정 (추후 활성)
}

# 광석 시작: 제련 → 단조 → 열처리 → 마감
STEPS_ORE = [
    {"name": "제련",   "skill_name": "smelting"},
    {"name": "단조",   "skill_name": "forging"},
    {"name": "열처리", "skill_name": "heat_treat"},
    {"name": "마감",   "skill_name": "finishing"},
]

# 주괴 시작: 단조 → 열처리 → 마감
STEPS_INGOT = [
    {"name": "단조",   "skill_name": "forging"},
    {"name": "열처리", "skill_name": "heat_treat"},
    {"name": "마감",   "skill_name": "finishing"},
]


def get_prerequisite_bonus(prereq_value: int) -> int:
    return prereq_value // 10


def get_milestone_flags(proficiency: int) -> dict:
    return {
        "bonus_dice": 1 if proficiency >= 75 else 0,
        "fumble_safe": proficiency >= 85,
        "auto_unlock": proficiency >= 95,
    }
