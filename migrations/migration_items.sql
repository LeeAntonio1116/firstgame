-- 제작 결과물 인벤토리 (stack 시스템)
CREATE TABLE items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL,
    material TEXT NOT NULL,
    quality INTEGER NOT NULL CHECK (quality BETWEEN 1 AND 5),
    quantity INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    batch_id UUID REFERENCES batches(id),
    process_log JSONB,
    UNIQUE (owner_id, item_type, material, quality)
);

-- RLS 비활성화 (REST API 접근을 위해 필수)
ALTER TABLE items DISABLE ROW LEVEL SECURITY;
