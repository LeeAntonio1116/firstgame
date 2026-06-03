"""[S8] 인메모리 슬라이딩 윈도우 rate limit (단일 워커 베타용).

로그인·가입 무차별 대입 완화. **멀티 워커/분산 배포(S10)에서는 카운터가 워커별로 분리되어
무력화**되므로 DB·공유 저장소 기반으로 교체 필요. admin_otp.py도 자체 인메모리 한도기를 가지며
추후 본 모듈로 통합 가능. x-forwarded-for 신뢰는 배포 시 프록시 검증(PROXY_TRUSTED_HOSTS)으로 보강.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request

_buckets: dict[str, deque[float]] = defaultdict(deque)


def client_ip(request: Request) -> str:
    """클라이언트 IP — rate limit 버킷 키.

    Cloud Run 등 신뢰 프록시 뒤에서는 X-Forwarded-For의 **마지막 값**(프록시가
    덧붙인 실제 피어 IP)을 사용한다. 클라이언트가 임의로 주입한 앞쪽 XFF 값은
    신뢰하지 않으므로 IP 스푸핑으로 rate limit을 우회할 수 없다. XFF가 없으면
    (로컬·직접 연결) request.client.host로 폴백.
    (Cloud Run은 1홉이라 마지막 값이 실제 IP. 앞단에 CDN/LB를 더 두면 인덱스 조정 필요.)
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        parts = [p.strip() for p in fwd.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


def allow(key: str, max_attempts: int, window_sec: int) -> bool:
    """key의 window_sec 내 시도가 max_attempts 미만이면 기록 후 True, 초과면 False(미기록)."""
    now = time.time()
    dq = _buckets[key]
    while dq and (now - dq[0]) > window_sec:
        dq.popleft()
    if len(dq) >= max_attempts:
        return False
    dq.append(now)
    return True
