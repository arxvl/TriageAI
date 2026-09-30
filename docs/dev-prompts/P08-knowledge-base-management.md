# P08 — Knowledge Base Management (Workflow, Versions, Importer, W-08)

**Branch prefix:** `feat/p08-<n>-<name>`
**Requirements:** FR-49–FR-56, NFR-08, BR-04, DR-05 · UC-13, UC-14 · ADR-12, ADR-14 · wireframe W-08

## Goal

Knowledge-base entries and red-flag rules move through Draft → Pending Review → Active → Retired. Only a licensed-veterinarian approver can activate them. Every approval or retirement publishes a new **immutable KB version**. Entries can be imported from YAML files in `knowledge_base/`.

Indexing is called through the `KBIndexer` interface. Its real implementation (chunking, embedding, pgvector) is built **manually in M5**. In this phase it is the mock.

## ⚠️ AI boundary

Do not write chunking, embedding, or vector code. `KBIndexer.index_entry` and `remove_entry` are called; `MockKBIndexer` does nothing. Leave a `TODO(manual:M5)` wherever real indexing will plug in.

## Out of scope

- Real indexing and retrieval (M4–M6)
- Evaluation and user screens (P09)

---

## Subphase 8.1 — KB workflow API and versioning

**Tasks**

1. Migration `p08_kb_slugs`:
   - Add `slug` (unique) to `kb_entries` for idempotent import.
   - Add `phrases_ref` (text, nullable) to `red_flag_rules`. It points to the YAML key holding the phrases used by M1.
2. `services/kb_service.py`, which enforces the state machine:

   | Action | From state | Role | Effect |
   |---|---|---|---|
   | create / edit draft | — / `DRAFT` | ADMINISTRATOR | Validate required fields: title, complaint, species, content of 50–1,500 words, full source citation (FR-50) |
   | submit | `DRAFT` | ADMINISTRATOR | → `PENDING_REVIEW` |
   | approve | `PENDING_REVIEW` | reviewer with `can_approve_kb` | Enqueue a `KB_INDEX` job, then → `ACTIVE`, publish a new version |
   | reject (comments required) | `PENDING_REVIEW` | approver | → `DRAFT` with `review_comments` |
   | retire | `ACTIVE` | ADMINISTRATOR | `remove_entry`, → `RETIRED`, publish a new version |

   Invalid transitions return 409. Every action writes an audit entry.
3. **Version publishing** (FR-54, DR-05). The `KB_INDEX` job runs these steps in one transaction after indexing succeeds:
   1. Call `KBIndexer.index_entry(entry_id)`.
   2. Set the entry to `ACTIVE` with `approved_by` and `approved_at`.
   3. Insert a `KBVersion` with `version_no = max + 1`.
   4. Insert `kb_version_entries` for **all** currently `ACTIVE` entries.

   If indexing fails, the entry stays `PENDING_REVIEW` with the error shown, and no version is published. Published versions are never modified (trigger from P02).
4. **Red-flag rules**:
   - Endpoints to list, create, edit (only while unapproved), approve, and retire rules. Approval requires `can_approve_kb`.
   - Approving or retiring a rule also publishes a new KB version, so rule changes are versioned.
   - Add the function `get_active_rules(app_env)`: approved, non-retired rules; placeholder rules are included only when `APP_ENV=dev`. The manual screener (M1) and the safety floor use it.
   - Add a `retired_at` column to `red_flag_rules`.
5. Endpoints under `/kb`, all with the roles above:
   - `GET /kb/entries?status=`, `POST /kb/entries`, `GET/PATCH /kb/entries/{id}`
   - `POST /kb/entries/{id}/submit|approve|reject|retire`
   - `GET /kb/versions`, `GET /kb/versions/{id}`
   - `GET/POST /kb/red-flag-rules`, `PATCH /kb/red-flag-rules/{id}`, `POST /kb/red-flag-rules/{id}/approve|retire`
6. The pipeline (P05) must use the **latest published version**. Show its `version_no` in W-04's configuration footnote.

**Tests**

- Every allowed and forbidden transition.
- An approver without `can_approve_kb` gets 403.
- A version contains exactly the active entries.
- A published version cannot be updated.
- Indexing failure → no version published.
- `get_active_rules` behaves differently in dev and prod.

---

## Subphase 8.2 — YAML importer

**File formats.** Document both in `knowledge_base/README.md`.

`knowledge_base/entries/<slug>.yaml`:

```yaml
slug: urinary-straining-cat
title: Straining or inability to urinate – cats
complaint_code: URINARY_OBSTRUCTION
species: [CAT]
content: |
  Written by the curator in their own words from the cited source...
source:
  title: Feline Lower Urinary Tract Disease
  publisher: Merck Veterinary Manual
  url: https://www.merckvetmanual.com/...
  access_date: 2026-10-12
red_flag_codes: [MALE_CAT_NO_URINE]
```

`knowledge_base/red_flags.yaml`:

```yaml
rules:
  - code: MALE_CAT_NO_URINE
    label: Male cat producing no urine
    min_category: ORANGE
    species: [CAT]
    phrases_ref: MALE_CAT_NO_URINE   # phrases are maintained manually (M1)
```

**Tasks**

1. `python -m scripts.import_kb [--entries] [--rules] [--dry-run]`:
   - Validate each file against a Pydantic schema. Report every error with its file and field.
   - Upsert by `slug` / `code`. New or changed content becomes `DRAFT` (entries) or unapproved (rules).
   - **Never modify an ACTIVE entry in place.** A changed file for an active entry creates a new draft revision with slug `<slug>` and the column `revises_entry_id` set (add it in the same migration as 8.1).
   - Print a summary table: created, updated, unchanged, errors.
2. Include two **sample** entries and the placeholder rules, each clearly marked `SAMPLE – not vet-approved` in its content, so the workflow can be tested. The team replaces them with real content in M5.

**Tests:** schema validation errors; idempotent re-import; an active entry is never overwritten; dry-run writes nothing.

---

## Subphase 8.3 — Knowledge Base screen (W-08)

Build `pages/KnowledgeBase` to match W-08.

1. **Header:** "Published version: vN · M active entries".
2. **Tabs:** Draft, Pending review, Active, Retired, with counts. The entry list sits on the left and the detail/editor panel on the right.
3. **Editor** (administrator):
   - title
   - complaint (select from the fixed list)
   - species
   - content, with a word counter and the helper "Write in your own words from the cited source; do not copy text"
   - a red-flag rule picker
   - source citation fields, all required
   - buttons: Save draft, Submit for review
4. **Approver view:** read-only content with the actions Approve and publish (vN+1) and Reject with comments (comments required). Show indexing progress and errors.
5. **Red-flag rules tab:** a table of rules with minimum category, species, status, and approval. Placeholder rules get a "Placeholder" badge.
6. **Version history drawer:** each version's number, date, publisher, and entry count.
7. **Navigation:** administrators see "Knowledge Base"; approvers see "KB Approvals" (from P03).

**Tests:** the approve buttons are visible only to approvers; the reject comment is required; the citation fields are validated.

---

## Verification

```bash
docker compose exec backend python -m scripts.import_kb --dry-run
docker compose exec backend python -m scripts.import_kb
```

1. As admin, submit a sample entry.
2. As approver, approve it: KB version 1 is published.
3. Submit a new case. W-04 shows "KB version 1".
4. Retire the entry: version 2 is published, and version 1 is still listed and unchanged.
5. Approve a red-flag rule, then submit `DEMO_1`. The alert still appears; the mock screener is fixture-based.

```bash
docker compose exec backend pytest -q
```

Final report as in CLAUDE.md §12. List where `TODO(manual:M5)` markers were placed.
