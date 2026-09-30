# Requirements — TriageAI

**Project:** TriageAI: A Transformer-Based NLP System for Canine and Feline Symptom Triage and Clinical Decision Support
**Source of truth:** SRS v1.1 (PD2). These files restate its requirements as tables for implementation use. If a file here and the SRS PDF ever disagree, the SRS wins and the file must be corrected.

| File | Category | Range | Count |
|---|---|---|---|
| [functional-requirements.md](functional-requirements.md) | Functional | FR-01 – FR-70 | 70 |
| [non-functional-requirements.md](non-functional-requirements.md) | Non-functional (performance, safety, quality) | NFR-01 – NFR-28 | 28 |
| [interface-requirements.md](interface-requirements.md) | Interface (UI, hardware, software, communications) | IR-01 – IR-22 | 22 |
| [business-rules.md](business-rules.md) | Business rules | BR-01 – BR-09 | 9 |
| [database-requirements.md](database-requirements.md) | Database | DR-01 – DR-08 | 8 |
| [security-requirements.md](security-requirements.md) | Security | SR-01 – SR-16 | 16 |

**Total:** 153 requirements.

## Rules for changing these files

1. **Never renumber or reuse an ID.** A new requirement gets the next free number in its category; a withdrawn one is marked withdrawn, not deleted.
2. **Never reword the Description column.** It is the SRS text. Change it only when the SRS itself is revised, and record the change in the SRS revision history.
3. The other columns (Requirement, Priority, scope, acceptance criteria, Related) are working aids and may be refined, as long as they do not contradict the Description.
4. Keep cross-references valid in both directions: if FR-23 cites NFR-08, NFR-08 should cite FR-23.

## Related project documentation

- `docs/adr/` — architecture decision records ADR-01 to ADR-17, with an index and a decision map.
- `docs/prototype/TriageAI_Prototype.html` — the clickable wireframes W-01 to W-11 referenced throughout.
- `docs/dev-prompts/` — phase prompts for Claude Code (P01–P10) and manual AI guides (M1–M7).
- `CLAUDE.md` — project context read at the start of every Claude Code session.

## Where each category bites hardest

| Working on | Read first |
|---|---|
| Intake, queue, review screens | FR-01–FR-40, IR-01–IR-08, BR-01–BR-03 |
| The AI pipeline | FR-09–FR-28, NFR-07–NFR-14, IR-12–IR-20, SR-08, SR-10 |
| Persistence and audit | FR-41–FR-48, DR-01–DR-08, SR-12 |
| Knowledge base | FR-49–FR-56, BR-04, DR-05 |
| Auth and roles | FR-57–FR-63, SR-01–SR-05, BR-02, BR-05 |
| Evaluation | FR-64–FR-70, NFR-16–NFR-23, DR-06, BR-08 |
