-- P4-1 시장 시스템
-- (1) 7번째 스탯 민첩(dexterity) + 개인장비칸 컬럼
-- (2) items.location (warehouse / inventory) — 소형 인벤 5칸
-- (3) commands에 거래 명령 필드 추가
-- (4) merchants / merchant_inventory / market_prices 3 테이블 + 상인 3종 시드
--
-- 시세·재고 시드: main.py startup의 ensure_market_seeded()가 자동 채움 (멱등).

-- ── 1. characters · npcs 민첩 + equipped_bag ──────────────
ALTER TABLE characters
    ADD COLUMN IF NOT EXISTS dexterity INT NOT NULL DEFAULT 50,
    ADD COLUMN IF NOT EXISTS equipped_bag UUID NULL;
ALTER TABLE npcs
    ADD COLUMN IF NOT EXISTS dexterity INT NOT NULL DEFAULT 50,
    ADD COLUMN IF NOT EXISTS equipped_bag UUID NULL;

-- 기존 행에 3d6×5 랜덤 부여 (신규 캐릭터와 동일 분포)
-- DEFAULT 50으로 INSERT된 행만 대상 — UPDATE 한 번 적용 후 신규 캐릭터는 character.py에서 직접 부여
UPDATE characters SET dexterity = LEAST(75,
    (FLOOR(RANDOM()*6)+1+FLOOR(RANDOM()*6)+1+FLOOR(RANDOM()*6)+1)::INT * 5
) WHERE dexterity = 50;
UPDATE npcs SET dexterity = LEAST(75,
    (FLOOR(RANDOM()*6)+1+FLOOR(RANDOM()*6)+1+FLOOR(RANDOM()*6)+1)::INT * 5
) WHERE dexterity = 50;

-- ── 2. items.location (warehouse / inventory) ────────────
ALTER TABLE items
    ADD COLUMN IF NOT EXISTS location TEXT NOT NULL DEFAULT 'warehouse'
        CHECK (location IN ('warehouse', 'inventory'));

-- UNIQUE 제약 location 포함으로 교체
ALTER TABLE items DROP CONSTRAINT IF EXISTS items_owner_id_item_type_material_quality_key;
ALTER TABLE items DROP CONSTRAINT IF EXISTS items_unique_with_location;
ALTER TABLE items ADD CONSTRAINT items_unique_with_location
    UNIQUE (owner_id, item_type, material, quality, location);

-- ── 3. commands 거래 컬럼 ────────────────────────────────
ALTER TABLE commands
    ADD COLUMN IF NOT EXISTS trade_action TEXT,
    ADD COLUMN IF NOT EXISTS merchant_id UUID,
    ADD COLUMN IF NOT EXISTS quality INT;

-- ── 4. merchants 3 테이블 ────────────────────────────────
CREATE TABLE IF NOT EXISTS merchants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    merchant_type TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS merchant_inventory (
    merchant_id UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL,
    material TEXT NOT NULL,
    stock_current INT NOT NULL DEFAULT 0,
    stock_max INT NOT NULL DEFAULT 0,
    last_restocked_at TIMESTAMPTZ,
    PRIMARY KEY (merchant_id, item_type, material)
);

CREATE TABLE IF NOT EXISTS market_prices (
    date DATE NOT NULL,
    item_type TEXT NOT NULL,
    material TEXT NOT NULL,
    current_price INT NOT NULL,
    base_price INT NOT NULL,
    PRIMARY KEY (date, item_type, material)
);

ALTER TABLE merchants DISABLE ROW LEVEL SECURITY;
ALTER TABLE merchant_inventory DISABLE ROW LEVEL SECURITY;
ALTER TABLE market_prices DISABLE ROW LEVEL SECURITY;

-- ── 5. 상인 3종 시드 (멱등) ──────────────────────────────
INSERT INTO merchants (code, name, merchant_type, description) VALUES
    ('fixed_official', '관시 행상', 'fixed',
     '관아 주변에 늘 자리잡은 행상. 광석·주괴·합금주괴를 두루 다루며, 광물도 시세 90%로 매입한다.'),
    ('random_caravan', '유랑상단', 'random',
     '매일 다른 자원을 들고 떠도는 상단. 7종 무작위 라인업이 매일 갱신된다.'),
    ('officer_buyer', '성주 직속 군수관', 'officer_buyer',
     '성주의 군수 담당. 무기만 매입하며, 정가 기준 일일 변동가로 거래한다.')
ON CONFLICT (code) DO NOTHING;
