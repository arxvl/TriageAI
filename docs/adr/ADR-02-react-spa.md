# ADR-02: React single-page application for the front end

- **Status:** Accepted
- **Requirements:** IR-01 to IR-08, IR-22, NFR-20, NFR-21, NFR-22
- **Related:** ADR-01, ADR-08, ADR-15

## Context

The triage queue (W-02) must reflect new cases and finished AI recommendations
without the user reloading the page (IR-22). The Case Review screen (W-04) is a
dense three-panel view with inline evidence highlighting and modal dialogs. The
system is used on clinic desktops and on tablets (W-11).

The team already knows JavaScript. Server-rendered templates would mean either
full page reloads on every queue refresh or a second, ad-hoc JavaScript layer
for partial updates.

## Decision

Build the front end as a **React 18 single-page application** in **TypeScript
(strict)**, built with **Vite**, communicating with the backend only through the
JSON REST API at `/api/v1`.

Fixed choices:

| Concern | Choice |
|---|---|
| Routing | React Router v6, with a `ProtectedRoute` that takes `allowedRoles` |
| Server state | TanStack Query, `refetchInterval: 15000` for the queue (IR-22) |
| Styling | CSS Modules plus design tokens in `src/styles/tokens.css` |
| API types | Generated from the OpenAPI schema into `src/api/generated` |
| Tests | Vitest + React Testing Library; Playwright for end-to-end |

Page folders mirror the wireframes: `pages/TriageQueue` is W-02,
`pages/CaseReview` is W-04, and so on. The clickable prototype in
`docs/prototype/TriageAI_Prototype.html` is the visual reference.

## Consequences

**Positive**

- Polling and optimistic UI are handled by one library instead of hand-written
  fetch logic.
- TypeScript types generated from OpenAPI catch backend/frontend drift at build
  time, which matters because three people change both sides.
- The same build output is served as static files by Nginx in production
  (ADR-13).

**Negative**

- Authorization cannot be trusted in the client. Every rule is enforced again on
  the server (ADR-11). The UI only hides what the user may not do.
- An SPA needs deliberate accessibility work: focus traps in dialogs, labelled
  inputs, keyboard paths (NFR-21).
- A build step exists between source and running UI, so the professors need
  Docker or Node to run it.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Server-rendered Jinja templates | Queue auto-refresh and the three-panel review screen would need custom JavaScript anyway |
| Next.js (SSR) | No SEO or first-paint requirement; adds a Node server to operate next to the Python one |
| HTMX over templates | Viable and simpler, but the team has more React experience and PD7 wireframes assume rich client state |

## Implementation notes

- Never call `fetch` directly in a component; use `src/api/client.ts`, which
  attaches the CSRF header and handles 401 redirects.
- Do not store the session token in `localStorage`; it lives in an HttpOnly
  cookie (ADR-11).
- Every VTL colour is rendered together with its category name and target time
  (ADR-15, IR-03).
