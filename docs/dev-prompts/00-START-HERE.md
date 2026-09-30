# TriageAI Development Prompts — Start Here

**Project:** TriageAI: A Transformer-Based NLP System for Canine and Feline Symptom Triage and Clinical Decision Support

This folder splits the build into two kinds of files:

- **Claude Code phases** (P01–P10). You give these to Claude Code, one subphase at a time.
- **Manual guides** (M1–M7). You follow these yourselves for every NLP/AI part:
  - de-identification and red-flag screening
  - LLM setup
  - entity extraction
  - pgvector and embeddings
  - knowledge-base chunking and indexing
  - retrieval and generation
  - real-model evaluation

Claude Code builds the whole application first with **mock AI stages**, so every screen works end to end. The manual guides then replace each mock with the real component through configuration. No application code changes are needed at that point.

## 1. One-time setup

1. Put `CLAUDE.md` in the repository root. Claude Code reads it automatically at the start of every session.
2. Put this folder at `docs/dev-prompts/`.
3. Copy the project documents into `docs/`:
   - `docs/srs/` — the SRS PDF, or a Markdown export of it
   - `docs/diagrams/` — the PD6 and PD7 diagram images and sources
   - `docs/adr/` — ADR-01 to ADR-15, one Markdown file each, copied from PD7 Section 7.2.2
   - `docs/prototype/TriageAI_Prototype.html` — the clickable wireframes
4. Create `develop` from `main` and protect both branches on GitHub.

## 2. Build order

The table lists every step in order and maps it to your PD8 roadmap. "CC" means Claude Code does the work; "You" means the team follows a manual guide.

| # | Step | Who | Depends on | Roadmap phase |
|---|---|---|---|---|
| 1 | P01 Repository scaffold and dev environment | CC | — | 0 |
| 2 | P02 Database schema, migrations, seed data | CC | P01 | 0 |
| 3 | P03 Authentication and RBAC | CC | P02 | 0 |
| 4 | P04 Case intake and Triage Queue | CC | P03 | 1 |
| 5 | P05 Triage pipeline framework (mocks) | CC | P04 | 1 |
| 6 | M1 De-identification and red-flag screening | You | P05 | 2 |
| 7 | M2 LLM provider setup and selection | You | P05 | 1 (spike) |
| 8 | M3 Clinical entity extraction | You | M1, M2 | 2 |
| 9 | P06 Case Review and HITL decisions | CC | P05 (parallel to M1–M3) | 3 |
| 10 | M4 pgvector and embedding model | You | P02 | 2 |
| 11 | P08 Knowledge base management | CC | P06 | 2–3 |
| 12 | M5 KB authoring, chunking, and indexing | You | M4, P08 | 2 |
| 13 | M6 Retrieval and recommendation generation | You | M3, M5 | 2 |
| 14 | P07 Resilience, regeneration, and history | CC | P06 | 3 |
| 15 | P09 Admin: users, evaluation harness, exports | CC | P07 | 3 |
| 16 | M7 Evaluation with the real model | You | M6, P09 | 3–4 |
| 17 | P10 Hardening, deployment, and release | CC + You | all | 4 |

P08 comes before P07 on purpose. The knowledge-base workflow must exist before M5 can index real entries.

The Claude Code lane (P06, P08, P07, P09) and the manual AI lane (M1–M6) can run **in parallel**, because the app runs on mocks until each manual guide switches a stage to real.

## 3. How to run one subphase with Claude Code

For each subphase, for example 4.2:

1. Create the branch: `git switch develop && git pull && git switch -c feat/p04-2-intake-screen`
2. Start Claude Code in the repository root: `claude`
3. Switch to **plan mode** (Shift+Tab) and paste:

   ```
   Read CLAUDE.md and docs/dev-prompts/P04-case-intake-and-queue.md.
   Implement ONLY subphase 4.2. First show me your plan: the files you will
   create or change and the tests you will write. Wait for my approval.
   ```

4. Review the plan. Correct anything that touches the AI boundary (CLAUDE.md §8) or a future phase.
5. Approve. Let Claude Code implement it and run the tests.
6. Run the **Verification** commands from the phase file yourself. Do not skip this step.
7. Review the diff (`git diff develop`). Commit, push, open a PR into `develop`, and have another member review it.
8. Run `/clear` in Claude Code before the next subphase. This keeps its context small and focused.

If Claude Code drifts into later phases, stop it and reply:

```
Stop. That belongs to a later phase. Revert those changes and finish only
subphase X.Y.
```

## 4. How to follow a manual guide

1. Create the branch named in the guide.
2. Work through the steps in order. Each ends with a **Check** you must pass before moving on.
3. You may ask Claude Code *questions* about your own code, for example "explain this error" or "review my test". Do not ask it to write the AI logic itself.
4. When the guide's final verification passes, switch the stage from `mock` to real in `.env` and commit.

## 5. Files in this folder

| File | Contents |
|---|---|
| `P01-repo-scaffold.md` | Folder structure, tooling, Docker Compose, health endpoint, CI |
| `P02-database.md` | Enums, SQLAlchemy models, migrations, audit trigger, seed |
| `P03-auth-rbac.md` | Login, sessions, lockout, `require_role`, login screen, app shell |
| `P04-case-intake-and-queue.md` | Case API, W-03 intake, W-02 queue with polling |
| `P05-pipeline-framework.md` | Contracts, job queue worker, orchestrator, mocks, safety validator |
| `P06-case-review-and-decisions.md` | W-04, W-05, W-06, decisions, audit timeline |
| `P07-resilience-regeneration-history.md` | Failure handling, retry, correction and regenerate, W-07 search |
| `P08-knowledge-base-management.md` | KB API and workflow, versions, YAML importer, W-08 |
| `P09-admin-evaluation-exports.md` | W-09 users, evaluation harness and W-10, exports |
| `P10-hardening-and-release.md` | End-to-end tests, security review, production deployment, README, release tag |
| `M1-deidentification-redflags.md` | Manual: rule-based de-identifier and red-flag screener |
| `M2-llm-provider-setup.md` | Manual: LLM accounts, adapters, Ollama fallback, selection spike |
| `M3-entity-extraction.md` | Manual: extraction prompt, schema validation, retry, mapping |
| `M4-pgvector-embeddings.md` | Manual: pgvector column and index, embedding model, embedder |
| `M5-kb-chunking-indexing.md` | Manual: writing KB entries, chunker, indexer, versions |
| `M6-retrieval-generation.md` | Manual: retriever, generation prompt, switching the pipeline to real |
| `M7-evaluation-real-model.md` | Manual: vignette set, evaluation runs, interpreting metrics |
