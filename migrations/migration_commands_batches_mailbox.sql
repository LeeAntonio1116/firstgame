-- ============================================================
-- 마이그레이션: commands / batches / mailbox 테이블 생성
-- 실행 위치: Supabase 대시보드 > SQL Editor
-- ============================================================

-- 1. batches — 배치 처리 실행 기록 (commands가 참조하므로 먼저 생성)
CREATE TABLE IF NOT EXISTS batches (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  scheduled_at  timestamptz NOT NULL,
  processed_at  timestamptz,
  status        text        NOT NULL DEFAULT 'pending',  -- pending / running / done
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- 2. commands — 플레이어가 제출한 명령서
CREATE TABLE IF NOT EXISTS commands (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  character_id    uuid        NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  command_type    text        NOT NULL DEFAULT 'blacksmith',
  target_material text        NOT NULL DEFAULT 'iron',   -- iron / copper / steel
  status          text        NOT NULL DEFAULT 'pending', -- pending / done / cancelled
  batch_id        uuid        REFERENCES batches(id),
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- 3. mailbox — 배치 처리 후 결과 메시지
CREATE TABLE IF NOT EXISTS mailbox (
  id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  character_id uuid        NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  command_id   uuid        REFERENCES commands(id),
  batch_id     uuid        REFERENCES batches(id),
  title        text        NOT NULL,
  body         jsonb       NOT NULL DEFAULT '{}',
  is_read      boolean     NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now()
);
