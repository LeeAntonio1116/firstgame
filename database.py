"""Supabase REST API (PostgREST) 래퍼.

R-2 (속도개선): httpx.Client를 모듈 전역에서 1회 생성·재사용.
호출당 TLS 핸드셰이크 50~150ms 절감 (특히 Mumbai region).

R-5 (속도개선): async 클라이언트도 함께 제공. FastAPI 라우트에서 await 가능.
sync 함수(`db_select` 등)는 기존 호출처(배치 처리·동기 흐름)와 호환 유지.
"""

import logging

import httpx

from config import SUPABASE_KEY, SUPABASE_URL

logger = logging.getLogger("firstgame.database")

_HEADERS = {
    "apikey": SUPABASE_KEY or "",
    "Authorization": f"Bearer {SUPABASE_KEY or ''}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}
_BASE = f"{SUPABASE_URL}/rest/v1"

# 모듈 전역 — 프로세스 lifetime 동안 단일 connection pool 유지
_client = httpx.Client(headers=_HEADERS, base_url=_BASE, timeout=10.0)
_async_client = httpx.AsyncClient(headers=_HEADERS, base_url=_BASE, timeout=10.0)


# ── sync API ─────────────────────────────────────────────
def db_select(table: str, **filters) -> list:
    params = {k: f"eq.{v}" for k, v in filters.items()}
    r = _client.get(f"/{table}", params=params)
    r.raise_for_status()
    return r.json()


def db_insert(table: str, data: dict) -> dict:
    r = _client.post(f"/{table}", json=data)
    r.raise_for_status()
    result = r.json()
    return result[0] if result else {}


def db_update(table: str, data: dict, **filters) -> list:
    params = {k: f"eq.{v}" for k, v in filters.items()}
    r = _client.patch(f"/{table}", json=data, params=params)
    r.raise_for_status()
    return r.json()


def db_delete(table: str, **filters) -> None:
    params = {k: f"eq.{v}" for k, v in filters.items()}
    r = _client.delete(f"/{table}", params=params)
    r.raise_for_status()


# ── batch (P4-1 시장 specific 최적화) ──────────────────────
def db_insert_many(table: str, rows: list[dict]) -> list:
    """여러 row를 단일 POST 호출로 INSERT. 빈 리스트면 no-op."""
    if not rows:
        return []
    r = _client.post(f"/{table}", json=rows)
    r.raise_for_status()
    return r.json()


def db_upsert(table: str, rows: list[dict], on_conflict: str) -> list:
    """단일 호출 UPSERT. `on_conflict`는 콤마 구분 PK·UNIQUE 컬럼 (예: 'date,item_type,material').
    PostgREST 패턴: POST + `Prefer: resolution=merge-duplicates`.
    """
    if not rows:
        return []
    headers = {"Prefer": "return=representation,resolution=merge-duplicates"}
    r = _client.post(f"/{table}", json=rows, headers=headers, params={"on_conflict": on_conflict})
    r.raise_for_status()
    return r.json()


# ── RPC (PostgreSQL 함수 — 원자 조건부 연산) ──────────────
# 안정성 fix 2단계: 트랜잭션 없는 RMW를 DB측 원자 연산으로 대체. 함수는 migrations/
# migration_stability_stage2.sql 에 정의 (미적용 시 404 — 마이그레이션 선행 필수).
class RpcUnavailable(RuntimeError):
    """PostgREST RPC가 404(함수 미존재 — 마이그/GRANT 미적용)이거나 도달 불가일 때.
    SQL이 NULL을 반환하는 비즈니스 결과(200 + body null → None)와 명확히 구분한다.
    main.py 전역 핸들러가 이 예외를 잡아 사용자에게 500 대신 친절 안내로 전환한다."""


def db_rpc(fn: str, params: dict):
    """PostgREST /rpc/<fn> 호출. 스칼라/JSON 반환.

    성공(200)이면 응답 JSON 그대로 반환 — RPC가 SQL NULL을 반환하면 None(= '부족/없음'
    비즈니스 결과, 호출처가 기존대로 해석). 함수 미존재(404)·네트워크 오류는 RpcUnavailable로
    승격해 ERROR 로그를 남긴다(마이그/GRANT 미적용 실사고 — 2026-06-01 release_npc_fee 404
    → 500 재발 방어). 404 외 HTTP 오류는 그대로 재전파.
    """
    try:
        r = _client.post(f"/rpc/{fn}", json=params)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.error("RPC '%s' 404 — 함수 미존재(마이그/GRANT 미적용 의심)", fn)
            raise RpcUnavailable(fn) from e
        raise
    except httpx.RequestError as e:
        logger.error("RPC '%s' 호출 실패: %s", fn, type(e).__name__)
        raise RpcUnavailable(fn) from e
    return r.json()


def adjust_gold(user_id: str, delta: int) -> int | None:
    """users.gold 원자 증감 (A-1). 차감(delta<0)은 잔액 충분 시만, 입금(delta>=0)은 항상.
    반환: 새 잔액. None = 잔액 부족(차감 거부) 또는 유저 없음."""
    return db_rpc("adjust_user_gold", {"p_user_id": user_id, "p_delta": delta})


def adjust_stamina(table: str, actor_id: str, delta: int) -> int | None:
    """characters/npcs.stamina_current 원자 증감 (A-2). 차감은 잔량 충분 시만,
    충전은 health/5로 클램프. 반환: 새 값. None = 스태미너 부족 또는 actor 없음."""
    return db_rpc(
        "adjust_actor_stamina", {"p_table": table, "p_actor_id": actor_id, "p_delta": delta}
    )


def hold_npc_fee(npc_id: str, user_id: str, fee: int) -> int | None:
    """F-5 원자 홀드 — fee_held=0(이번 창 첫 명령)일 때만 gold 차감+홀드 (NPC 행 FOR UPDATE).
    반환: 홀드액 / 0(이미 홀드됨·NPC 없음) / None(자금 부족)."""
    return db_rpc("hold_npc_fee", {"p_npc_id": npc_id, "p_user_id": user_id, "p_fee": fee})


def release_npc_fee(npc_id: str, user_id: str) -> int:
    """F-5 원자 환불 — fee_held>0이면 gold 환불+리셋 (단일 승자, 동시 취소/해고에도 1회만).
    반환: 환불액 (0 = 홀드 없음)."""
    return db_rpc("release_npc_fee", {"p_npc_id": npc_id, "p_user_id": user_id})


def settle_npc_fee(npc_id: str, user_id: str, fee: int) -> int:
    """F-5 배치 정산 — 홀드됐으면 리셋(차감 X), 아니면 fallback 차감(잔액 충분 시).
    반환: fallback 차감액 (0 = 선불 정산됨)."""
    return db_rpc("settle_npc_fee", {"p_npc_id": npc_id, "p_user_id": user_id, "p_fee": fee})


# ── async API (R-5) ──────────────────────────────────────
async def db_select_async(table: str, **filters) -> list:
    params = {k: f"eq.{v}" for k, v in filters.items()}
    r = await _async_client.get(f"/{table}", params=params)
    r.raise_for_status()
    return r.json()


async def close_async_client() -> None:
    """FastAPI lifespan 종료 시 호출."""
    await _async_client.aclose()
