"""Cross-cutting HTTP behaviour: CSRF defence and the sliding session cookie.

Both are middleware rather than dependencies on purpose. CSRF has to cover
*every* state-changing request (SR-09), and a re-issued cookie has to be the
only `Set-Cookie` for its name on the response — a dependency that set it would
collide with `/auth/logout`, which clears the same cookie.
"""

import secrets
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.cookies import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    set_session_cookie,
)
from app.core.config import get_settings
from app.core.errors import CSRFFailed
from app.core.security import create_session_token

Dispatch = Callable[[Request], Awaitable[Response]]

UNSAFE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})

# Login is the one exemption: the browser has no CSRF cookie yet (P03 task 3).
CSRF_EXEMPT_PATHS = frozenset({"/api/v1/auth/login"})

# Set by `get_current_user` once a request is authenticated, and by
# `/auth/logout` to say the session is over. Kept here so both ends agree.
SESSION_STATE_ATTR = "session"
SESSION_CLEARED_STATE_ATTR = "session_cleared"


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF check on state-changing requests (SR-09, ADR-11)."""

    async def dispatch(self, request: Request, call_next: Dispatch) -> Response:
        if self._needs_check(request) and not self._token_matches(request):
            error = CSRFFailed()
            return JSONResponse(status_code=error.status_code, content=error.body())
        return await call_next(request)

    @staticmethod
    def _needs_check(request: Request) -> bool:
        return request.method in UNSAFE_METHODS and request.url.path not in CSRF_EXEMPT_PATHS

    @staticmethod
    def _token_matches(request: Request) -> bool:
        cookie = request.cookies.get(CSRF_COOKIE_NAME)
        header = request.headers.get(CSRF_HEADER_NAME)
        if not cookie or not header:
            return False
        return secrets.compare_digest(cookie, header)


class SessionCookieMiddleware(BaseHTTPMiddleware):
    """Re-issue the session cookie with a fresh `exp` on authenticated requests.

    This is what makes the 30-minute timeout an *idle* one (SR-04): a user who
    keeps working never gets logged out, while an abandoned workstation does.
    The refresh is skipped when the handler ended the session, so logout emits
    exactly one `Set-Cookie` per cookie.
    """

    async def dispatch(self, request: Request, call_next: Dispatch) -> Response:
        response = await call_next(request)
        session = getattr(request.state, SESSION_STATE_ATTR, None)
        cleared = getattr(request.state, SESSION_CLEARED_STATE_ATTR, False)
        if session is not None and not cleared:
            settings = get_settings()
            set_session_cookie(
                response, create_session_token(session.user_id, session.role), settings
            )
        return response
