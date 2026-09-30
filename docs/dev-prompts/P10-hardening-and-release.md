# P10 — Hardening, End-to-End Tests, Deployment, and Release

**Branch prefix:** `test/`, `chore/`, `docs/` + `p10-<n>-<name>`
**Requirements:** NFR-01–NFR-06, NFR-21, NFR-22, NFR-25, NFR-26, SR-04–SR-11, SR-15, SR-16, IR-07, IR-16 · ADR-13 · PD8 submission requirements

## Goal

The prototype is tested end to end, reviewed for security and accessibility, and deployed on the evaluation server behind HTTPS. It is documented well enough for the professors to install and access it, and tagged `v0.1.0-pd8`.

**Feature freeze:** no new features in this phase. Only fixes for defects that break a Must item or the demo.

## Who does what

- **Claude Code:** 10.1–10.4 (code and configuration)
- **You:** the server purchase, DNS, TLS certificate issue, and the final demo rehearsal (marked **[Manual]** below)

---

## Subphase 10.1 — Test coverage and end-to-end demo tests

**Tasks**

1. Raise backend coverage to at least 60% on `app/services`, `app/pipeline` (excluding manual real-stage modules), and `app/api` (NFR-25).
   - Add `pytest --cov` with `--cov-fail-under=60` for these packages in CI.
   - Manual modules (M1–M6) keep their own tests, written by the team.
2. Set up Playwright in `e2e/`:
   - a global setup that runs `scripts.seed --reset` against a dedicated e2e stack (`docker compose -f docker-compose.yml -f e2e/compose.e2e.yml`)
   - pipeline settings: mocks, unless `E2E_REAL=1`
3. Write the four demo scenario tests, following the PD8 roadmap demo script:
   1. `DEMO_1` intake → red-flag banner appears in ≤ 5 s → reviewer sees ORANGE with the safety-floor notice → adjusts to RED with a reason → the audit timeline shows the steps.
   2. `DEMO_2` → RED at the top of the queue.
   3. `DEMO_3` → BLUE → reviewer confirms.
   4. Forced failure phrase → MANUAL → manual triage saved.
4. Add these tests:
   - RBAC: Intake Staff cannot see decision buttons; a direct POST returns 403.
   - Accessibility: `@axe-core/playwright` on W-01, W-02, W-03, W-04, and W-05, failing on serious and critical violations (NFR-21). You may add `@axe-core/playwright` as a dependency.
5. Latency report script `scripts/latency_report.py`:
   - reads `recommendations.params.stage_ms` for the last N cases
   - prints p50 and p95 per stage and in total, against NFR-01

---

## Subphase 10.2 — Security and privacy review

Go through this checklist, fix each gap, and write `docs/security-review.md` with pass or fix notes for every item.

- [ ] Every router has `require_role`, except health and login. Add a test that inspects all routes automatically.
- [ ] CSRF is enforced on all mutating routes. Cookies are `Secure` in prod, `HttpOnly`, and `SameSite=Lax`.
- [ ] Idle timeout is 30 min, and lockout is 5 failures for 15 min.
- [ ] No free text in logs or audit entries. A log-capture test runs the demo flow.
- [ ] `owner_references` is never selected by any pipeline or export query. Grep plus a test.
- [ ] Security headers in Nginx: HSTS, `X-Content-Type-Options`, `Referrer-Policy`, a basic `Content-Security-Policy` for the SPA, and `X-Frame-Options: DENY`.
- [ ] Rate-limit `/auth/login` in Nginx: 10 requests per minute per IP.
- [ ] Dependency audit: run `pip-audit` and `npm audit --omit=dev`, fix high and critical findings, and add both to CI as non-blocking reports.
- [ ] Secrets only come from the environment. `.env.example` has no real values, and the startup check refuses the default `SECRET_KEY` in prod.
- [ ] The safety guard from CLAUDE.md §8.3 is active in prod.

---

## Subphase 10.3 — Production deployment configuration

**Tasks**

1. `deploy/docker-compose.prod.yml`:
   - Services: `proxy` (Nginx), `backend`, `db`, `backup`.
   - The frontend is built in a multi-stage Dockerfile and served as static files by Nginx.
   - Only the proxy publishes ports 80 and 443.
   - The backend and database run on an internal network. The database has no published port.
   - `restart: unless-stopped` and healthchecks.
2. `deploy/nginx/nginx.conf`:
   - redirect HTTP to HTTPS
   - TLS 1.2 and 1.3 only
   - `/api/` proxied to the backend, `/` serving the SPA with a history fallback
   - the security headers and rate limit from 10.2
   - certificate paths under `/etc/letsencrypt/live/<domain>/`
3. `deploy/backup/backup.sh` and its container:
   - a daily `pg_dump -Fc`, encrypted with `age` or `gpg` using a public key from the environment
   - keeps the last 7 dumps (SR-15, DR-07)
   - `deploy/backup/restore.md` with the restore steps
4. `deploy/README-deploy.md`: the step-by-step server guide.
   1. Install Docker on Ubuntu.
   2. Configure the UFW firewall: allow 22, 80, and 443.
   3. Clone the repository and create `.env`.
   4. Issue the certificate with Certbot standalone.
   5. `docker compose -f deploy/docker-compose.prod.yml up -d --build`
   6. Run migrations and seed. Seed demo accounts with **unique passwords** for the professors.
   7. Run the smoke test.
   8. Set up automatic certificate renewal.
   9. Update by pulling a tag and rebuilding.
5. `scripts/smoke_test.sh <base-url>`: checks health, login, submitting a demo case, and polling to `AWAITING_REVIEW`.

**[Manual] You:**

1. Provision the VM: Ubuntu 22.04 or 24.04, 2 vCPU, 8 GB RAM if the embedding model runs on it.
2. Point a domain or free subdomain at it.
3. Follow `deploy/README-deploy.md`.
4. Run the smoke test from a phone on mobile data.

---

## Subphase 10.4 — Documentation and release

**Tasks**

1. Update the root `README.md` with these sections:
   - overview (with the project title)
   - features by SRS system feature
   - architecture diagram link
   - requirements (Docker, Node 24, Python 3.11 for local non-Docker development)
   - quick start
   - environment variables table
   - seeding
   - running tests (unit, e2e)
   - pipeline modes (mock vs real, with links to M1–M7)
   - the demo failure toggle
   - deployed URL and demo-account instructions (credentials shared privately, not in the repository)
   - known limitations
   - license and academic-use notice
   - the clinical disclaimer
2. Write `CHANGELOG.md` with the entries from `v0.0.1` to `v0.1.0-pd8`, matching the roadmap tags.
3. Write `docs/traceability.md`: a table mapping each Must FR to its implementation (module or endpoint) and the tests that prove it. Generate it from test markers: add `@pytest.mark.req("FR-23")` markers to the key tests and write a small script that collects them.

**[Manual] You:**

1. Merge `develop` into `main` and tag `v0.1.0-pd8`.
2. Deploy the tag.
3. Run the dry run with the acceptance checklist from the PD8 roadmap.
4. Record the backup demo video.
5. Capture screenshots for the PD8 PDF.

---

## Verification

```bash
docker compose exec backend pytest --cov=app --cov-report=term-missing
cd e2e && npx playwright test
./scripts/smoke_test.sh https://<your-domain>
docker compose exec backend python -m scripts.latency_report --last 20
```

All four demo scenarios pass locally **and** on the deployed server. `docs/security-review.md` shows every item as pass.

Final report as in CLAUDE.md §12, plus the list of remaining known issues for the final presentation.
