"""P4-1 자금 표시 헬퍼.

DB는 량(兩) 단위 정수로만 저장. UI 표시할 때 정(錠)/관(貫)/량(兩) 3단계로 자동 환산.
- 1 관 = 1,000 량 / 1 정 = 1,000 관 = 1,000,000 량
- 정·관·량 3단위를 항상 모두 표시 (앞자리 0 단위도 생략하지 않음).
"""

from __future__ import annotations

LIANG_PER_GUAN = 1_000
LIANG_PER_JEONG = 1_000_000


def format_gold(amount: int | None) -> str:
    """자금(량) 정수를 '정·관·량' 3단위 문자열로. 항상 세 단위 모두 표시."""
    n = int(amount or 0)
    sign = "-" if n < 0 else ""
    n = abs(n)

    jeong, rem = divmod(n, LIANG_PER_JEONG)
    guan, liang = divmod(rem, LIANG_PER_GUAN)

    return f"{sign}{jeong}정 {guan}관 {liang}량"
