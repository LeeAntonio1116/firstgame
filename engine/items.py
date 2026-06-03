"""아이템 인벤토리 — stack 시스템 + 카테고리.

(owner_id, item_type, material, quality) 동일 시 한 row의 quantity++,
상한 초과 시 새 row 생성 (MMO 표준 패턴).

ore의 stack 상한은 희귀도(MATERIALS[material]['rarity']) 1~5에 따라 차등:
  ★ 999 / ★★ 500 / ★★★ 100 / ★★★★ 50 / ★★★★★ 20.
"""

from engine.materials import MATERIALS, WEAPON_CODES, WEAPON_LABELS

ITEM_TYPE_LABELS = {
    "ore": "광석",
    "ingot": "주괴",
    "alloy_ingot": "합금주괴",
    "armor": "방어구",  # P4+
}
# 무기 item_type은 dagger/greatsword 등 개별 코드로 저장 — 한글 라벨 합류
ITEM_TYPE_LABELS.update(WEAPON_LABELS)

# 창고 카테고리 분류 (P3-4 창고 UI에서 사용)
CATEGORY_BY_TYPE = {
    "ore": "material",
    "ingot": "ingot",
    "alloy_ingot": "alloy_ingot",
    "armor": "armor",
}
# 무기 7종 모두 'weapon' 카테고리로 합류
for _wc in WEAPON_CODES:
    CATEGORY_BY_TYPE[_wc] = "weapon"

CATEGORY_LABELS = {
    "material": "소재",
    "ingot": "주괴",
    "alloy_ingot": "합금주괴",
    "weapon": "무기",
}

CATEGORY_ORDER = ["material", "ingot", "alloy_ingot", "weapon"]

# 희귀도별 광석 stack 상한 (1~5)
_ORE_STACK_BY_RARITY = {1: 999, 2: 500, 3: 100, 4: 50, 5: 20}
DEFAULT_STACK_LIMIT = 99


def get_stack_limit(item_type: str, material: str) -> int:
    """item_type + material 조합의 stack 상한 산출.
    - ore: 희귀도별 차등
    - ingot: 일괄 100
    - alloy_ingot: 50
    - weapon: 99 (창고 기준 — P4 캐릭터 인벤은 별도)
    - armor / 미정: DEFAULT_STACK_LIMIT
    """
    if item_type == "ore":
        rarity = MATERIALS.get(material, {}).get("rarity", 3)
        return _ORE_STACK_BY_RARITY.get(rarity, DEFAULT_STACK_LIMIT)
    if item_type == "ingot":
        return 100
    if item_type == "alloy_ingot":
        return 50
    if item_type in WEAPON_CODES:
        return 99  # 창고 기준. 캐릭터 인벤토리 크기별 차등은 P4+
    return DEFAULT_STACK_LIMIT


# ── P4-3 아이템 한 줄 설명 ────────────────────────────────
# 단일 출처: wiki 아이템_설명_콘텐츠.md (34종). 키 = (item_type, material).
# - 광석/주괴/합금주괴: material은 코드. ingot/alloy_ingot의 material은 광석·합금 코드.
# - 무기: 카테고리 단위 설명 → material=None.
ITEM_DESCRIPTIONS = {
    # 광물 14종
    ("ore", "raw_iron"): "가장 흔한 철광석. 대장간 입문자가 처음 두드리는 광물.",
    (
        "ore",
        "magnetite",
    ): "자성을 띠는 검은 광석. 옛 도공들은 이것으로 만든 칼날이 영기(靈氣)를 머금는다 했다.",
    ("ore", "chalcopyrite"): "노란빛이 도는 구리광. 입문자의 동반자.",
    ("ore", "malachite"): "푸른빛 띠 무늬가 공작의 깃털을 닮았다 하여 이름 붙은 구리광.",
    ("ore", "cassiterite"): "주석의 원광. 청동을 빚는 데 빠질 수 없다.",
    ("ore", "galena"): "무거운 납빛 광석. 단단하나 다루기 까다롭다.",
    ("ore", "placer_gold"): "강바닥에서 흘러나온 금가루. 부유한 의장용 단검의 재료.",
    ("ore", "silver_ore"): "빛바랜 달처럼 차가운 광택. 부유한 가문의 장식용으로 쓰인다.",
    ("ore", "meteorite_iron"): "하늘에서 떨어진 검은 돌. 한 자루의 칼이면 가문의 보배가 된다.",
    ("ore", "cinnabar"): "붉은 주사. 주괴 없이 정련해 수은으로 만들고 열처리 보조제로 쓴다.",
    ("ore", "bronze"): "구리와 주석을 섞어 빚는 황금빛 합금. 군용 무기의 표준.",
    ("ore", "steel"): "자철석을 거듭 두드려 얻는 단단한 합금. 장수의 칼에 어울린다.",
    ("ore", "white_copper"): "은의 빛을 더한 구리 합금. 가벼우면서 광택이 빼어나다.",
    ("ore", "heaven_iron"): "운석의 정수를 머금은 신비한 합금. 한 자루로 천 명의 적을 베었다 한다.",
    # 주괴 9종 (material은 광석 코드)
    ("ingot", "raw_iron"): "거칠게 정련된 생철 덩어리. 군영의 무기를 책임지는 가장 흔한 재료.",
    ("ingot", "magnetite"): "무겁고 차가운 검은 주괴. 두드릴수록 깊은 소리가 울린다.",
    ("ingot", "chalcopyrite"): "황동광에서 뽑아낸 구리 덩어리. 시장 어디서나 거래된다.",
    ("ingot", "malachite"): "푸른 빛의 흔적이 남은 구리 주괴. 공작석의 정수가 깃들었다.",
    ("ingot", "cassiterite"): "청동의 짝. 청동주괴를 빚을 때 빼놓을 수 없다.",
    (
        "ingot",
        "galena",
    ): "묵직한 회색 덩어리. 다루기는 까다로우나 그 무게가 한 자루의 무기를 든든하게 한다.",
    ("ingot", "placer_gold"): "황금빛으로 빛나는 부의 상징. 왕가의 의장용 무기로 빚어진다.",
    ("ingot", "silver_ore"): "차고 맑은 광택의 은 덩어리. 귀공자의 검집에 박힌다.",
    (
        "ingot",
        "meteorite_iron",
    ): "별의 정수를 응축한 검은 주괴. 한 덩어리로 한 자루의 명검을 만든다.",
    # 합금주괴 4종 (material은 합금 코드)
    ("alloy_ingot", "bronze"): "구리와 주석이 어우러진 황금빛 합금주괴. 군용 무기의 정통.",
    ("alloy_ingot", "steel"): "생철과 자철의 단단한 결합. 장수의 칼이 여기서 태어난다.",
    ("alloy_ingot", "white_copper"): "은빛이 도는 구리 합금주괴. 가벼우면서도 우아하다.",
    ("alloy_ingot", "heaven_iron"): "자철과 운석철이 빚어낸 천상의 합금주괴. 가문 보검의 시작점.",
    # 무기 7종 (카테고리 단위, material 무관)
    ("dagger", None): "자객과 정탐의 무기. 품 안에 숨겨 한 호흡에 적의 목을 노린다.",
    ("greatsword", None): "장수의 양손 무기. 한 번 휘두름에 적진을 가른다.",
    ("longsword", None): "병사의 표준. 길이와 무게의 균형이 잡힌 정통 검.",
    ("shortspear", None): "가볍고 짧은 보병의 창. 던져서 멀리 닿게 할 수도 있다.",
    ("longspear", None): "군진을 이루는 창병의 무기. 길고 무겁다.",
    ("axe", None): "벌목과 전투를 가리지 않는 보병의 동반자.",
    ("greataxe", None): "한 손으로는 들 수 없는 거대한 도끼. 장수의 위세를 더한다.",
}


def get_item_description(item_type: str, material: str | None) -> str:
    """아이템 한 줄 설명 조회. 무기는 카테고리 단위(material 무시)."""
    if item_type in WEAPON_CODES:
        return ITEM_DESCRIPTIONS.get((item_type, None), "")
    return ITEM_DESCRIPTIONS.get((item_type, material), "")


def item_descriptions_for_js() -> dict:
    """JS/Jinja 전달용 — tuple 키를 'item_type|material' 문자열 키로 변환.
    무기는 'dagger|' 처럼 material 부분 빈 문자열."""
    return {
        f"{item_type}|{material or ''}": desc
        for (item_type, material), desc in ITEM_DESCRIPTIONS.items()
    }
