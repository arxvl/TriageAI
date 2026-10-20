# Knowledge base files

Curated clinical content, kept in the repository and imported into the database
as **drafts**. Nothing in this directory is live: an entry becomes retrievable
only after an account holding `can_approve_kb` approves it, and a red-flag rule
changes the safety floor only after the same approval (FR-51, FR-52, NFR-08,
BR-04). The system never fetches knowledge-base content from anywhere at run
time (FR-55).

All content is **English only** (FR-18).

| File | What it holds | Maintained by |
|---|---|---|
| `entries/<slug>.yaml` | One entry per file: a clinical entry, or a baseline action set | the curator, imported |
| `red_flags.yaml` | Every red-flag rule: code, label, minimum category, species | the curator, imported |
| `red_flag_phrases.yaml` | The phrases each rule matches on | by hand (M1); **not** imported |
| `SOURCES.md` | Provenance an entry file has no field for | by hand; **not** imported |
| `APPROVALS.md` | The source and the second-reader verification for every item | by hand |

The phrases deliberately stay out of the database. The categories live in
`red_flag_rules` so the safety floor has one source of truth; duplicating the
phrase lists into rows would give it two.

## What an entry file may contain

The importer rejects any key it does not declare, by name — a misspelled
`red_flag_code:` would otherwise import an entry citing no rule at all — and the
error lists the fields accepted at that point in the file. These are all of them:

| File | Accepted fields |
|---|---|
| `entries/<slug>.yaml` | `slug`, `kind`, `title`, `complaint_code`, `urgency_category`, `species`, `content`, `source`, `red_flag_codes` |
| `entries/<slug>.yaml`, inside `source:` | `title`, `publisher`, `url`, `access_date` |
| `red_flags.yaml`, per rule | `code`, `label`, `min_category`, `species`, `phrases_ref`, `is_placeholder` |

**Everything else about a source goes in [`SOURCES.md`](SOURCES.md), not in the
entry file.** A caveat about what the cited source does and does not support, a
second reference consulted alongside it, a note on why a category was chosen —
there is no `source_note:` or `supporting_sources:` field and adding one would
mean a database column. `SOURCES.md` keeps one section per entry slug, is read by
whoever verifies the entry before approving it, and is never imported.

## Importing

```bash
docker compose exec backend python -m scripts.import_kb --dry-run   # report only
docker compose exec backend python -m scripts.import_kb             # rules, then entries
docker compose exec backend python -m scripts.import_kb --rules     # rules only
docker compose exec backend python -m scripts.import_kb --entries   # entries only
```

- Rules are imported before entries, because an entry's `red_flag_codes` can
  only be linked to rules that exist.
- `--dry-run` is the same code path, rolled back instead of committed. It writes
  nothing, not even an audit entry.
- `--dir PATH` overrides `KNOWLEDGE_BASE_DIR` (default `/knowledge_base`, the
  container mount), so the importer also runs outside Docker.
- `--author EMAIL` names the administrator the drafts are attributed to;
  otherwise the lowest-email administrator account is used.
- Exit code `1` if any file was rejected, `2` if the run could not start.
- Every error is reported with its file and field, and the run reports **all** of
  them rather than stopping at the first.

## `entries/<slug>.yaml` — a clinical entry

```yaml
slug: urinary-straining-cat
title: Straining or inability to urinate - cats
complaint_code: URINARY_OBSTRUCTION
species: [CAT]
content: |
  Written by the curator in their own words from the cited source, 50-1,500
  words...
source:
  title: Feline Lower Urinary Tract Disease
  publisher: Merck Veterinary Manual
  url: https://www.merckvetmanual.com/...
  access_date: 2026-10-12
red_flag_codes: [MALE_CAT_NO_URINE]
```

| Field | Rules |
|---|---|
| `slug` | Required. Lower-case letters, numbers and hyphens; at most 120 characters. **Must equal the filename** without `.yaml`. |
| `kind` | Optional, defaults to `COMPLAINT`. The other kind is `URGENCY_ACTIONS`, below. |
| `title` | Required, at most 300 characters. |
| `complaint_code` | Required. One of the 21 presenting complaints `scripts/seed.py` writes. |
| `species` | Required, at least one of `DOG`, `CAT`. |
| `content` | Required, **50–1,500 words**, in the curator's own words from the cited source. Do not copy source text. |
| `source` | Required, and all four of `title`, `publisher`, `url`, `access_date` with it (FR-50). An entry nobody can trace to a published source must not be approvable. |
| `red_flag_codes` | Optional. Codes from `red_flags.yaml`; each names the rule this entry explains. An unknown code is an error. |

`urgency_category` is rejected on a clinical entry: it belongs to a baseline
action set, and the two kinds are exclusive.

Unknown keys are rejected by name. That is deliberate: a misspelled
`red_flag_code:` would otherwise import an entry citing no rule at all.

## `entries/<slug>.yaml` — a baseline action set

One per VTL category, holding the **baseline suggested actions** every case in
that category is shown (FR-71, FR-72, ADR-18). They are ordinary knowledge-base
entries, so they carry a citation and are versioned like any other content — but
they are looked up by category and **never similarity-searched**, so they are not
chunked or embedded at all. M5 Part D writes the five real ones.

```yaml
slug: actions-orange
kind: URGENCY_ACTIONS
urgency_category: ORANGE
title: Suggested staff actions - Orange (very urgent, within 15 minutes)
species: [DOG, CAT]
content: |
  Alert the veterinarian now and move the patient to the treatment area.
  Recheck breathing effort and alertness every few minutes.
  Keep handling to a minimum.
source:
  title: ...
  publisher: ...
  url: ...
  access_date: 2026-10-12
```

| Field | Rules |
|---|---|
| `kind` | Required, `URGENCY_ACTIONS`. |
| `urgency_category` | Required. One of `RED`, `ORANGE`, `YELLOW`, `GREEN`, `BLUE`. |
| `content` | Required. **One action per line, 3 to 6 lines**, each at most 25 words. Imperative, written for clinic staff. |
| `complaint_code` | Rejected. A baseline set belongs to a category, not to a complaint. |
| `red_flag_codes` | Rejected. A baseline set explains no red flag; it is never retrieved or cited. |
| `slug`, `title`, `species`, `source` | As for a clinical entry. The citation is required here too (FR-50). |

**Triage-level handling only** (FR-28, ADR-18 §1): escalate, prepare, monitor,
what to ask the owner, transport precautions. The importer refuses a line that
names a medication, a dose or a diagnosis, using the same block list that screens
the AI-tailored actions — baseline text is shown to staff verbatim and never
passes the action validator, so it is checked here instead. The error names the
line number.

### Replacing a seeded baseline set

`scripts/seed.py` writes five placeholder sets, marked `SAMPLE`, straight to
`ACTIVE` so the pipeline has something to show before any content exists. Only
**one ACTIVE set may hold a category**, so replacing one is three steps:

1. Import the file. It is reported as **revised**: a new `DRAFT` with
   `revises_entry_id` pointing at the live set, which is not touched.
2. Retire the live set in W-08. The response warns that the category will show
   **no** baseline actions until a replacement is approved — a real gap, so do
   step 3 straight away.
3. Submit and approve the draft. Approving it while the category is still taken
   answers 409 and names the set that holds it.

## `red_flags.yaml`

```yaml
rules:
  - code: MALE_CAT_NO_URINE
    label: Male cat producing no urine
    min_category: ORANGE
    species: [CAT]
    phrases_ref: MALE_CAT_NO_URINE   # phrases are maintained manually (M1)
```

| Field | Rules |
|---|---|
| `code` | Required. Capitals, digits and `_` only. The key the phrase file and every stored alert reference, so it is never changed — a replacement gets a new code. |
| `label` | Required, at most 300 characters. What the rule detects, in one line. |
| `min_category` | Required. The **lowest** VTL category the safety floor may assign when this rule fires. The floor can only raise a recommendation, never lower it (FR-23). |
| `species` | Required, at least one of `DOG`, `CAT`. |
| `phrases_ref` | Optional. The key in `red_flag_phrases.yaml` holding this rule's phrases. |
| `is_placeholder` | Optional, **defaults to `true`**. A rule that arrived from a file has not been through the approval workflow, and this flag is what keeps it out of `get_active_rules` outside development. |

Codes must be unique within the file.

## What a re-import does

Re-importing an unchanged file does nothing at all — no row write and no audit
entry — so the command is safe to run repeatedly.

| Stored state | File differs | Result |
|---|---|---|
| No row yet | — | **created** as `DRAFT` (entry) or unapproved (rule) |
| `DRAFT` | no | **unchanged** |
| `DRAFT` | yes | **updated** in place |
| `PENDING_REVIEW` | either | **skipped** — ask the approver to send it back first |
| `ACTIVE` or `RETIRED` | no | **unchanged** |
| `ACTIVE` or `RETIRED` | yes | **revised** — a new `DRAFT` with `revises_entry_id` set and the slug `<slug>-rev2`; the live entry is untouched |
| `ACTIVE`/`RETIRED` with a draft revision already open | yes | **updated** — that revision, in place (so no `-rev3` piles up) |
| baseline set, matched by category, base slug free | yes | **revised** — the new draft takes the file's own slug (the seeded sets have none) |
| stored entry is of the other `kind` | either | **error** — an entry cannot change kind; rename the file or correct `kind` |
| rule, unapproved | yes | **updated** in place, still unapproved |
| rule, approved | yes | **skipped** — retire it in W-08 and import a replacement code |
| rule, retired | yes | **skipped** |

**An ACTIVE entry is never modified.** Retrieval cites entries by id, and a
recommendation made last week has to still mean what it said; a change to live
content goes through approval again as a new revision (ADR-14, DR-05). A
`RETIRED` entry is treated the same way, because a published version still lists
it.

## Before approving anything

1. The content is written in the curator's own words from a **published,
   veterinarian-authored source**, and `source` names that source exactly.
2. A second team member has verified that the content matches the source.
3. Both are recorded as a row in [`APPROVALS.md`](APPROVALS.md).

The two **SAMPLE** placeholders subphase 8.2 shipped — invented wording with a
deliberately fake citation, there so the approval workflow could be walked end to
end — have been replaced by the sourced entries M5 Parts A and D wrote, and the
files are gone. Nothing in `entries/` may begin `SAMPLE - not source-verified`
again; `scripts/seed.py` still writes marked placeholders straight to the
database, and those are what a replacement imported from a file supersedes.
