# Clinical Content Approval Log

**Scope note.** For this academic project, external veterinary sign-off has been
waived. The `can_approve_kb` approval workflow remains a
system feature (BR-04, FR-52), and the team holds the approving account. Content
is accepted on the basis of **source traceability**: every entry, rule and
phrase must come from a published, veterinarian-authored source, and a second
team member must verify that the content matches that source.

**This system has not been clinically validated.**

If a licensed veterinarian does review any item later, add a new row with
Decision = `Veterinarian approved` and their name and licence number. That row
supersedes the team verification for that item.

## Red-flag rules and phrases (M1)

| Date | Item | Source (title, publisher, URL, access date) | Written by | Verified by | Decision | Comment |
|---|---|---|---|---|---|---|
| 2026-__-__ | NOT_BREATHING — category RED + phrases | Thomovsky & Ilie 2024, Can Vet J 65(2):162–172, Fig. 1 | | | Accepted / Changed / Rejected | |
| 2026-__-__ | UNRESPONSIVE — RED | | | | | |
| 2026-__-__ | ACTIVE_SEIZURE — RED | | | | | |
| 2026-__-__ | UNCONTROLLED_BLEEDING — RED | | | | | |
| 2026-__-__ | BLUE_GUMS_CYANOSIS — RED | | | | | |
| 2026-__-__ | PALE_GUMS — ORANGE | | | | | |
| 2026-__-__ | MALE_CAT_NO_URINE — ORANGE | | | | | |
| 2026-__-__ | TOXIN_INGESTION — ORANGE | | | | | |
| 2026-10-17 | BLUE_GUMS_CYANOSIS: phrases v1 → v2. Added 11 alternate wordings ("gums look bluish", "gums are bluish", "gums turned blue", "gums turning blue", "gums have turned blue", "bluish tongue", "tongue looks bluish", "tongue is blue", "lips look blue", "lips are blue", "bluish lips"). Minimum category unchanged (RED). | Thomovsky E, Ilie L. Basic triage in dogs and cats: Part I. Can Vet J 2024;65(2):162–172. https://pmc.ncbi.nlm.nih.gov/articles/PMC10783570/ (cyanosis as a sign of respiratory distress, Red category, Fig. 1). Accessed 2026-10-__ | <your name> | <a different team member> | Accepted | Wording variants of the same finding, not a new clinical claim. The source names cyanosis in general; gums, tongue and lips are the sites where owners describe it. Found because the DEMO_2 text ("His gums look bluish") matched no rule. Tested: DEMO_2 now fires this rule; "no bluish gums" and unrelated texts do not. Screener `prompt_version` is now `redflag-phrases-v2`. |
| 2026-10-17 | Considered and NOT added: open-mouth breathing, and "won't get up when I call him" | Thomovsky & Ilie 2024, Practice tip 1: dogs and cats pant or breathe open-mouthed when overheated, which mimics respiratory distress | <your name> | <a different team member> | Not added | Too non-specific on their own and would over-trigger. DEMO_2 is already floored at RED by the cyanosis phrase. Revisit if M7 shows critical cases being missed. |

## Knowledge base entries (M5 Parts A–C)

| Date | Entry slug | Source | Written by | Verified by | Decision | Comment |
|---|---|---|---|---|---|---|
| 2026-__-__ | urinary-straining-cat | | | | | |

## Urgency-action entries (M5 Part D, ADR-18)

Baseline suggested actions, one entry per VTL category. Each must contain **no
medication, dose, route or diagnosis** — run the action validator over the lines
as a check before approving.

| Date | Category | Entry slug | Source | Written by | Verified by | Validator clean? | Decision |
|---|---|---|---|---|---|---|---|
| 2026-__-__ | RED | actions-red | | | | Yes / No | |
| 2026-__-__ | ORANGE | actions-orange | | | | | |
| 2026-__-__ | YELLOW | actions-yellow | | | | | |
| 2026-__-__ | GREEN | actions-green | | | | | |
| 2026-__-__ | BLUE | actions-blue | | | | | |

## Evaluation labelling (M7)

| Date | Vignette set | Rubric version | Labeller 1 | Labeller 2 | Cohen's kappa | Comment |
|---|---|---|---|---|---|---|
| 2026-__-__ | | | | | | |
