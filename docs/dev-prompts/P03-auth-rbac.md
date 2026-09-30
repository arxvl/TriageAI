# P03 — Authentication, Sessions, and Role-Based Access

**Branch prefix:** `feat/p03-<n>-<name>`
**Requirements:** FR-57–FR-62, SR-01–SR-05, SR-09, SR-12, IR-02, IR-05 · ADR-11 · UC-01 · wireframe W-01

## Goal

Users log in with email and password and get a secure cookie session. The server enforces roles on every endpoint. The frontend has a login screen and a role-aware application shell with a header.

## Out of scope

- User-management screens (P09). Accounts come from the seed script.
- Any case, KB, or evaluation endpoints.

---

## Subphase 3.1 — Backend authentication and RBAC

**Tasks**

1. Implement `app/core/security.py`:
   - `hash_password` and `verify_password` with Argon2id (argon2-cffi defaults)
   - `create_session_token(user_id, role)`: a JWT signed with HS256 and `SECRET_KEY`, with claims `sub`, `role`, `iat`, `exp = now + SESSION_IDLE_MINUTES`, and `jti`
   - `decode_session_token`
   - a password policy of at least 12 characters with at least one letter and one digit (SR-02)
2. Session cookie:
   - Name it `triageai_session`, with `HttpOnly`, `SameSite=Lax`, `Path=/`, and `Secure` whenever `APP_ENV != dev`.
   - Use a **sliding expiry**: on every authenticated request, re-issue the cookie with a fresh `exp` (SR-04, 30-minute idle timeout).
3. CSRF protection, double-submit style:
   - On login, set a readable cookie `triageai_csrf` with a random token.
   - All state-changing requests (POST, PATCH, PUT, DELETE) must send an `X-CSRF-Token` header equal to that cookie. Otherwise return 403.
   - Exempt `/auth/login` only.
4. Implement `app/api/deps.py`:
   - `get_current_user`: returns 401 if the cookie is missing, invalid, or expired, and when the user is inactive
   - `require_role(*roles, kb_approver: bool = False)`: returns 403 when not permitted
5. Endpoints in `app/api/v1/auth.py`:
   - **`POST /auth/login` `{email, password}`**
     - Returns a generic 401 message, `"Incorrect username or password."`, whatever the cause.
     - Increments `failed_login_count` on each failure.
     - On the 5th consecutive failure, sets `locked_until = now + 15 min` (SR-03).
     - While locked, returns 423 with a message that includes the unlock time.
     - On success, resets the counter and sets `last_login_at`.
     - Returns `{user: {id, full_name, email, role, can_approve_kb, must_change_password}}`.
   - **`POST /auth/logout`:** clears both cookies.
   - **`GET /auth/me`:** returns the current user.
   - **`POST /auth/change-password` `{current_password, new_password}`:** enforces the policy and clears `must_change_password`.
   - While `must_change_password` is true, every other endpoint except `/auth/*` returns 403 with code `PASSWORD_CHANGE_REQUIRED`.
6. Audit (SR-12): write `AuditEntry` rows for `LOGIN_SUCCESS`, `LOGIN_FAILURE`, `ACCOUNT_LOCKED`, `LOGOUT`, and `PASSWORD_CHANGED`. Put this in a minimal `AuditService.record(...)` in `app/services/audit_service.py`; later phases extend it.
7. Add a demo-only test router: `GET /api/v1/_rbac-test/reviewer`, protected by `require_role(VETERINARY_REVIEWER)` and mounted only when `APP_ENV=dev`. Tests use it to prove the 403 behavior.
8. Error format: `{"error": {"code": "...", "message": "..."}}` for every 4xx and 5xx response. Register the handlers in `core/errors.py`.

**Tests**

- Successful login sets both cookies.
- Wrong password returns 401 with the generic message.
- The 5th failure locks the account (423). The account unlocks after the time passes; use a frozen clock or an injectable `now()`.
- An expired token returns 401. A valid request re-issues the cookie.
- A missing or wrong CSRF header on POST returns 403.
- An Intake Staff user calling the reviewer test route gets 403.
- `must_change_password` blocks other endpoints until the password is changed.
- Audit rows are written for each security event.

---

## Subphase 3.2 — Frontend login and application shell

**Tasks**

1. `src/api/client.ts`: read the `triageai_csrf` cookie and add the `X-CSRF-Token` header on mutating requests. On 401, redirect to `/login`. Map the error JSON to a typed `ApiError`.
2. `src/hooks/useAuth.ts`: an `AuthProvider` backed by `GET /auth/me`, plus `login` and `logout`.
3. `pages/Login` (**W-01**). Match the prototype:
   - title and subtitle
   - username/e-mail and password fields
   - the generic error line
   - the lockout notice "After 5 failed attempts your account is locked for 15 minutes."
   - the RA 10173 privacy notice
   - For a 423 response, show the unlock time from the message.
4. `pages/ChangePassword`: shown automatically when `must_change_password` is true. Display the password policy hint.
5. `components/AppHeader.tsx` (IR-02):
   - system name
   - role-based navigation:
     - Staff and Reviewer: Triage Queue, New Case, Case History; plus KB Approvals when `can_approve_kb`
     - Administrator: Users, Knowledge Base, Evaluation, Exports
   - user name and role, Help, and Log out
   - For now the links go to placeholder pages that say "Coming in a later phase".
6. `components/ProtectedRoute.tsx` with an `allowedRoles` prop. Routes:
   - `/login`
   - `/` redirects by role: staff and reviewers to `/queue`, administrators to `/admin/users`
   - placeholder routes for the other pages
7. Accessibility (IR-07): labelled inputs, visible focus outline, and keyboard submit with Enter.

**Tests (Vitest)**

- The login form shows the generic error on 401.
- The header shows the correct navigation items for each role.
- `ProtectedRoute` redirects an unauthenticated user to `/login`.

---

## Verification

```bash
docker compose exec backend pytest -q tests -k auth
```

In the browser, log in as each seeded user and check that:

- you are forced to change the password first;
- you see only your role's navigation;
- five wrong passwords lock the account;
- logging out returns you to the login screen.

In DevTools → Application → Cookies, check that `triageai_session` is HttpOnly.

Final report: endpoints, cookie and CSRF design, tests, and any deviations.
