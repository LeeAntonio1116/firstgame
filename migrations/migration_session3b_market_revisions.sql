-- 세션 3-b 정책 정정 (2026-05-23)
-- (1) market_prices를 상인별로 분리 — PK에 merchant_id 추가
-- (2) 관시 행상 라인업 축소 (★1만)·유랑상단 품목 수 10개로 확장은 코드(engine/market.py)에서.
--     이 마이그레이션은 데이터 정리만 담당 — 다음 startup의 ensure_market_seeded가 새 정책으로 시드.

-- ── 1. market_prices: merchant_id 추가 + PK 교체 ───────────
-- 기존 PK (date, item_type, material) 삭제
ALTER TABLE market_prices DROP CONSTRAINT IF EXISTS market_prices_pkey;

-- merchant_id 컬럼 추가 (NULL 허용으로 일단 — 기존 row가 있으면 채울 수 없으니 비움)
ALTER TABLE market_prices ADD COLUMN IF NOT EXISTS merchant_id UUID;

-- 기존 시세 데이터 전부 삭제 (매일 재시드되는 데이터라 손실 X)
DELETE FROM market_prices;

-- merchant_id NOT NULL + 새 PK
ALTER TABLE market_prices ALTER COLUMN merchant_id SET NOT NULL;
ALTER TABLE market_prices ADD CONSTRAINT market_prices_pkey
    PRIMARY KEY (date, merchant_id, item_type, material);

-- FK (상인 삭제 시 가격 자동 정리)
ALTER TABLE market_prices DROP CONSTRAINT IF EXISTS market_prices_merchant_fk;
ALTER TABLE market_prices ADD CONSTRAINT market_prices_merchant_fk
    FOREIGN KEY (merchant_id) REFERENCES merchants(id) ON DELETE CASCADE;

-- ── 2. 관시 행상 재고 정리 — 라인업 축소(★1만)를 새로 시드 받기 ──
-- 유랑상단은 매일 라인업 갱신이라 별도 정리 불필요 (다음 reset에서 갱신)
DELETE FROM merchant_inventory
    WHERE merchant_id = (SELECT id FROM merchants WHERE code = 'fixed_official');

-- 신규 환경(서울 리전) 통합 schema에도 동일 정책 반영해야 함 — _initial_full_schema.sql 별도 수정
