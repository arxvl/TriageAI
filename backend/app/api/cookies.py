"""The two session cookies and how they are set (P03 tasks 2 and 3, ADR-11).

`triageai_session` carries the signed token and is `HttpOnly`, so injected
JavaScript cannot read it. `triageai_csrf` is deliberately *readable*: the SPA
copies it into the `X-CSRF-Token` header on every state-changing request, and
the server compares the two (double-submit). An attacker's page can make the
browser send the cookie but cannot read it to build the header.
"""

import secrets

from starlette.responses import Response

from app.core.config import AppEnv, Settings

SESSION_COOKIE_NAME = "triageai_session"  # noqa: S105 - a cookie name, not a secret
CSRF_COOKIE_NAME = "triageai_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"  # noqa: S105 - a header name, not a secret

COOKIE_PATH = "/"
COOKIE_SAMESITE = "lax"


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def use_secure_cookies(settings: Settings) -> bool:
    """`Secure` everywhere except local development, which has no TLS (SR-04, SR-06)."""
    return settings.app_env is not AppEnv.DEV


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=settings.session_idle_minutes * 60,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        path=COOKIE_PATH,
        secure=use_secure_cookies(settings),
    )


def set_csrf_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        max_age=settings.session_idle_minutes * 60,
        httponly=False,
        samesite=COOKIE_SAMESITE,
        path=COOKIE_PATH,
        secure=use_secure_cookies(settings),
    )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    """Expire both cookies, which is what ends the session (FR-62)."""
    for name in (SESSION_COOKIE_NAME, CSRF_COOKIE_NAME):
        response.delete_cookie(
            name,
            path=COOKIE_PATH,
            samesite=COOKIE_SAMESITE,
            secure=use_secure_cookies(settings),
        )
