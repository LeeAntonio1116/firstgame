-- ============================================================
-- 통합 schema (서울 region 새 프로젝트용 — 한 번만 실행)
-- 기존 마이그레이션 13개 + P0(users·characters)를 단일 파일로 정리.
-- 적용 후 추가 마이그레이션은 일반적인 incremental 방식으로.
-- 실행 위치: 새 Supabase 프로젝트 SQL Editor
-- ============================================================

-- ── 1. users (P0 + P4-2) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    username      VARCHAR     NOT NULL UNIQUE,
    password_hash TEXT        NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now(),
    is_active     BOOLEAN     DEFAULT true,
    is_admin      BOOLEAN     NOT NULL DEFAULT false,
    email         TEXT,
    gold          INTEGER     NOT NULL DEFAULT 0
);
ALTER TABLE users DISABLE ROW LEVEL SECURITY;

-- ── 2. characters (P0 + 누적 마이그레이션) ────────────────
CREATE TABLE IF NOT EXISTS characters (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          TEXT        NOT NULL,
    strength      INTEGER     NOT NULL,
    intelligence  INTEGER     NOT NULL,
    charisma      INTEGER     NOT NULL,
    leadership    INTEGER     NOT NULL,
    health        INTEGER     NOT NULL,
    luck          INTEGER     NOT NULL,
    dexterity     INTEGER     NOT NULL DEFAULT 50,
    created_at    TIMESTAMPTZ DEFAULT now(),
    -- 부상·중상 (migration_injury_recovery + add_skills_proficiency)
    is_injured                BOOLEAN NOT NULL DEFAULT false,
    is_serious_injured        BOOLEAN NOT NULL DEFAULT false,
    serious_injury_remaining  INTEGER NOT NULL DEFAULT 0,
    -- 옛 스킬 컬럼 (character_skills 테이블로 옮긴 후에도 schema에 잔존 — 호환성)
    skill_appraisal  INTEGER NOT NULL DEFAULT 20,
    skill_smelting   INTEGER NOT NULL DEFAULT 15,
    skill_forging    INTEGER NOT NULL DEFAULT 20,
    skill_heat_treat INTEGER NOT NULL DEFAULT 15,
    skill_finishing  INTEGER NOT NULL DEFAULT 10,
    -- 운영
    has_blacksmith   BOOLEAN NOT NULL DEFAULT false,
    stamina_current  INTEGER NOT NULL DEFAULT 0,
    equipped_bag     UUID    NULL
);
ALTER TABLE characters DISABLE ROW LEVEL SECURITY;

-- ── 3. npcs (migration_add_skills_proficiency + P4-1) ────
CREATE TABLE IF NOT EXISTS npcs (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id            UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                TEXT        NOT NULL,
    npc_type            TEXT        NOT NULL DEFAULT '장인',
    strength            INTEGER     NOT NULL DEFAULT 30,
    intelligence        INTEGER     NOT NULL DEFAULT 30,
    charisma            INTEGER     NOT NULL DEFAULT 30,
    leadership          INTEGER     NOT NULL DEFAULT 30,
    health              INTEGER     NOT NULL DEFAULT 30,
    luck                INTEGER     NOT NULL DEFAULT 30,
    dexterity           INTEGER     NOT NULL DEFAULT 50,
    is_injured          BOOLEAN     NOT NULL DEFAULT false,
    is_dead             BOOLEAN     NOT NULL DEFAULT false,
    skill_appraisal     INTEGER     NOT NULL DEFAULT 10,
    skill_smelting      INTEGER     NOT NULL DEFAULT 8,
    skill_forging       INTEGER     NOT NULL DEFAULT 10,
    skill_heat_treat    INTEGER     NOT NULL DEFAULT 8,
    skill_finishing     INTEGER     NOT NULL DEFAULT 5,
    -- 옛 proficiency 컬럼 (material_proficiency 테이블로 옮긴 후에도 schema에 잔존)
    proficiency_iron    INTEGER     NOT NULL DEFAULT 20,
    proficiency_copper  INTEGER     NOT NULL DEFAULT 10,
    proficiency_steel   INTEGER     NOT NULL DEFAULT 0,
    proficiency_jade    INTEGER     NOT NULL DEFAULT 0,
    proficiency_special INTEGER     NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    equipped_bag        UUID        NULL
);
ALTER TABLE npcs DISABLE ROW LEVEL SECURITY;

-- ── 4. batches (migration_commands_batches_mailbox) ──────
CREATE TABLE IF NOT EXISTS batches (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    scheduled_at TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ,
    status       TEXT        NOT NULL DEFAULT 'pending',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE batches DISABLE ROW LEVEL SECURITY;

-- ── 5. commands (+ P2 quantity + P3 weapon + P4-1 trade) ─
CREATE TABLE IF NOT EXISTS commands (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    character_id    UUID        NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    command_type    TEXT        NOT NULL DEFAULT 'blacksmith',
    target_material TEXT        NOT NULL DEFAULT 'iron',
    status          TEXT        NOT NULL DEFAULT 'pending',
    batch_id        UUID        REFERENCES batches(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    input_type      TEXT        NOT NULL DEFAULT 'ore',
    quantity        INTEGER     NOT NULL DEFAULT 1,
    work_type       TEXT        NOT NULL DEFAULT 'ingot',
    weapon_category TEXT,
    -- P4-1 거래
    trade_action    TEXT,
    merchant_id     UUID,
    quality         INTEGER
);
ALTER TABLE commands DISABLE ROW LEVEL SECURITY;

-- ── 6. mailbox (migration_commands_batches_mailbox) ──────
CREATE TABLE IF NOT EXISTS mailbox (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    character_id UUID        NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    command_id   UUID        REFERENCES commands(id),
    batch_id     UUID        REFERENCES batches(id),
    title        TEXT        NOT NULL,
    body         JSONB       NOT NULL DEFAULT '{}',
    is_read      BOOLEAN     NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE mailbox DISABLE ROW LEVEL SECURITY;

-- ── 7. material_proficiency (migration_material_proficiency) ──
CREATE TABLE IF NOT EXISTS material_proficiency (
    character_id  UUID    REFERENCES characters(id) ON DELETE CASCADE,
    material_type TEXT    NOT NULL,
    value         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (character_id, material_type)
);
ALTER TABLE material_proficiency DISABLE ROW LEVEL SECURITY;

-- ── 8. character_skills (migration_character_skills) ─────
CREATE TABLE IF NOT EXISTS character_skills (
    character_id UUID    NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    skill_name   TEXT    NOT NULL,
    value        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (character_id, skill_name)
);
ALTER TABLE character_skills DISABLE ROW LEVEL SECURITY;

-- ── 9. items (migration_items + P3-1 quality + P4-1 location) ──
CREATE TABLE IF NOT EXISTS items (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id    UUID        NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    item_type   TEXT        NOT NULL,
    material    TEXT        NOT NULL,
    quality     INTEGER     NOT NULL CHECK (quality BETWEEN 0 AND 5),
    quantity    INTEGER     NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    batch_id    UUID        REFERENCES batches(id),
    process_log JSONB,
    location    TEXT        NOT NULL DEFAULT 'warehouse'
                CHECK (location IN ('warehouse', 'inventory')),
    CONSTRAINT items_unique_with_location
        UNIQUE (owner_id, item_type, material, quality, location)
);
ALTER TABLE items DISABLE ROW LEVEL SECURITY;

-- ── 10. admin_otp (P4-2) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS admin_otp (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    otp_code    TEXT        NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_admin_otp_user_id ON admin_otp(user_id);
CREATE INDEX IF NOT EXISTS idx_admin_otp_expires_at ON admin_otp(expires_at);
ALTER TABLE admin_otp DISABLE ROW LEVEL SECURITY;

-- ── 11. admin_audit_log (P4-2) ───────────────────────────
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id UUID        REFERENCES users(id) ON DELETE SET NULL,
    endpoint      TEXT        NOT NULL,
    payload       JSONB,
    result        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_admin_audit_created_at ON admin_audit_log(created_at);
ALTER TABLE admin_audit_log DISABLE ROW LEVEL SECURITY;

-- ── 12. merchants 3 테이블 (P4-1) ────────────────────────
CREATE TABLE IF NOT EXISTS merchants (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    code          TEXT        UNIQUE NOT NULL,
    name          TEXT        NOT NULL,
    merchant_type TEXT        NOT NULL,
    description   TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS merchant_inventory (
    merchant_id       UUID        NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    item_type         TEXT        NOT NULL,
    material          TEXT        NOT NULL,
    stock_current     INT         NOT NULL DEFAULT 0,
    stock_max         INT         NOT NULL DEFAULT 0,
    last_restocked_at TIMESTAMPTZ,
    PRIMARY KEY (merchant_id, item_type, material)
);

CREATE TABLE IF NOT EXISTS market_prices (
    date          DATE NOT NULL,
    item_type     TEXT NOT NULL,
    material      TEXT NOT NULL,
    current_price INT  NOT NULL,
    base_price    INT  NOT NULL,
    PRIMARY KEY (date, item_type, material)
);

ALTER TABLE merchants          DISABLE ROW LEVEL SECURITY;
ALTER TABLE merchant_inventory DISABLE ROW LEVEL SECURITY;
ALTER TABLE market_prices      DISABLE ROW LEVEL SECURITY;

-- ── 13. 상인 3종 시드 (P4-1) ─────────────────────────────
INSERT INTO merchants (code, name, merchant_type, description) VALUES
    ('fixed_official', '관시 행상', 'fixed',
     '관아 주변에 늘 자리잡은 행상. 광석·주괴·합금주괴를 두루 다루며, 광물도 시세 90%로 매입한다.'),
    ('random_caravan', '유랑상단', 'random',
     '매일 다른 자원을 들고 떠도는 상단. 7종 무작위 라인업이 매일 갱신된다.'),
    ('officer_buyer', '성주 직속 군수관', 'officer_buyer',
     '성주의 군수 담당. 무기만 매입하며, 정가 기준 일일 변동가로 거래한다.')
ON CONFLICT (code) DO NOTHING;
