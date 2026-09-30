# Contributing to TriageAI

## Branch model

- `main` — always deployable; only receives completed, verified phases via a
  merge from `develop`.
- `develop` — integration branch. All feature work merges here first.
- Everything else branches off `develop` and is prefixed by its purpose:
  - `feat/` — new functionality
  - `fix/` — bug fixes
  - `chore/` — tooling, scaffolding, non-functional maintenance
  - `docs/` — documentation only
  - `test/` — test-only changes
  - `spike/` — throwaway investigation, not intended to merge as-is
  - `hotfix/` — urgent fixes branched from `main`

Never commit directly to `main` or `develop`. Every change lands through a
pull request.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/), and include
the requirement ID(s) the commit addresses when applicable:

```
feat(cases): validate description length (FR-04)
fix(auth): reject expired session cookies (SR-05)
chore(repo): scaffold folder layout and tooling (NFR-24, NFR-26)
```

Keep commits small and focused on one change.

## Pull requests

- Open a PR from your branch into `develop` (never directly into `main`).
- Fill in the PR template: linked issue, requirement IDs covered, how to
  test, screenshots for UI changes, and the checklist.
- PRs are squash-merged into `develop`, so the PR title and description
  become the final commit message — write them accordingly.
- Delete your branch after it merges.

## Database migrations

At most one Alembic migration per PR, named after the subphase it belongs to.
This keeps migration history easy to bisect and review.

## Releases

`develop` merges into `main` only at a completed, verified phase milestone —
not after every individual PR.
