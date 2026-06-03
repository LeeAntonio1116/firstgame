-- P2 명령서 UI 확장: 수량 컬럼 추가
-- quantity = 한 명령서에 묶인 반복 작업 수 (batch에서 N번 process 반복)
ALTER TABLE commands
    ADD COLUMN IF NOT EXISTS quantity INTEGER NOT NULL DEFAULT 1;
