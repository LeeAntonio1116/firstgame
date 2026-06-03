"""[S8] CSRF 보호 — double-submit 쿠키 방식 (서버 상태/마이그 불필요).

- 발급: main.py `csrf_cookie` 미들웨어가 `csrf_token` 쿠키를 발급(없을 때만)하고
  `request.state.csrf_token`에 노출. 템플릿의 모든 상태변경 폼은 hidden 필드로 같은 값을 echo한다
  (`<input type="hidden" name="csrf_token" value="{{ request.state.csrf_token }}">`).
- 검증: `csrf_protect` 전역 의존성이 비안전 메서드(POST/PUT/PATCH/DELETE)에서 폼의 csrf_token과
  쿠키를 상수시간 비교. 불일치/누락 시 403. 앱의 모든 상태변경이 표준 HTML 폼 POST라는 전제.
- 쿠키는 서버에서만 비교하므로 httponly 유지(JS 노출 불필요). 동일 출처 공격자는 쿠키 값을 읽거나
  폼 필드를 맞출 수 없으므로 교차 사이트 위조 POST가 차단된다.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request

CSRF_COOKIE = "csrf_token"
CSRF_FIELD = "csrf_token"
CSRF_MAX_AGE = 7 * 86400  # 7일 (token 쿠키와 동일 수명)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def issue_csrf_token() -> str:
    return secrets.token_urlsafe(32)


async def csrf_protect(request: Request) -> None:
    """비안전 메서드에서 폼 csrf_token ↔ 쿠키 일치 검증. 불일치 시 403."""
    if request.method in _SAFE_METHODS:
        return
    if request.url.path.startswith("/internal/"):
        return  # [S10] Cloud Scheduler 호출 — 폼 CSRF 대신 X-Cron-Secret 헤더로 보호
    cookie = request.cookies.get(CSRF_COOKIE)
    form = await request.form()
    sent = form.get(CSRF_FIELD)
    if not cookie or not sent or not secrets.compare_digest(str(cookie), str(sent)):
        raise HTTPException(
            status_code=403,
            detail="보안 토큰 검증 실패 — 페이지를 새로고침한 뒤 다시 시도하세요.",
        )
