import httpx
from config import SUPABASE_URL, SUPABASE_KEY

_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}
_BASE = f"{SUPABASE_URL}/rest/v1"


def db_select(table: str, **filters) -> list:
    params = {k: f"eq.{v}" for k, v in filters.items()}
    with httpx.Client() as c:
        r = c.get(f"{_BASE}/{table}", headers=_HEADERS, params=params)
        r.raise_for_status()
        return r.json()


def db_insert(table: str, data: dict) -> dict:
    with httpx.Client() as c:
        r = c.post(f"{_BASE}/{table}", headers=_HEADERS, json=data)
        r.raise_for_status()
        result = r.json()
        return result[0] if result else {}


def db_update(table: str, data: dict, **filters) -> list:
    params = {k: f"eq.{v}" for k, v in filters.items()}
    with httpx.Client() as c:
        r = c.patch(f"{_BASE}/{table}", headers=_HEADERS, json=data, params=params)
        r.raise_for_status()
        return r.json()


def db_delete(table: str, **filters) -> None:
    params = {k: f"eq.{v}" for k, v in filters.items()}
    with httpx.Client() as c:
        r = c.delete(f"{_BASE}/{table}", headers=_HEADERS, params=params)
        r.raise_for_status()
