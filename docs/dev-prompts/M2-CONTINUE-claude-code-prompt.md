# M2 Continuation — Claude Code Prompt (audit Steps 0–8, then complete Steps 9–12)

**Give this file to Claude Code.** Paste the "Prompt to paste" block below; everything after it is the
specification Claude Code reads from this file.

---

## Prompt to paste into Claude Code (plan mode first)

```
Read CLAUDE.md, docs/dev-prompts/M2-llm-provider-setup.md, and
docs/dev-prompts/M2-CONTINUE-claude-code-prompt.md.

Context: P01-P05 and M1 are complete and merged. M2 Steps 0-8 are claimed done but
UNVERIFIED. Step 9 currently fails: scripts.llm_determinism returns ValidationError on
all 8 runs with last_error_kind = None.

Follow M2-CONTINUE-claude-code-prompt.md exactly, starting with PHASE A (read-only audit).
Do not change any file during PHASE A. End PHASE A with the audit report and WAIT for my
approval before touching anything.
```

---

## 0. Scope and the AI-boundary exception

`CLAUDE.md` §8 forbids Claude Code from writing provider-specific LLM code. **For M2 only, that rule is
suspended by the project owner**, with these limits. Claude Code MAY:

- create or repair `app/adapters/llm/hosted.py`, `ollama.py`, `ratelimit.py` and their tests;
- create or repair `scripts/_llm.py`, `llm_ping.py`, `llm_schema_check.py`, `llm_determinism.py`, `llm_spike.py`;
- edit `app/core/config.py`, `.env.example`, `docker-compose.yml`, `app/pipeline/registry.py` (LLM branches only);
- edit `docs/adr/ADR-06-llm-provider-adapter.md`.

Claude Code MUST NOT, in this task:

- write or tune `backend/prompts/extraction/*` or `generation/*` or `actions/*` — those are M3, M6 and M6b;
- modify `app/pipeline/safety.py`, `action_validator.py`, `deidentify_rules.py`, `redflags_keywords.py`,
  or any file under `app/services/` or `app/models/`;
- change `PIPELINE_EXTRACTOR`, `PIPELINE_RETRIEVER`, `PIPELINE_GENERATOR`, `PIPELINE_ACTIONS` or
  `KB_INDEXER` away from their current values — M2 does not switch pipeline stages on;
- weaken or remove the startup safety guard (real LLM + mock de-identifier must refuse to start);
- commit anything, or run `git push`.

Record the exception in the PR description when you reach Phase F.

## 1. Environment notes (this machine)

- The project runs under **podman-compose via the docker-compose CLI shim**. The `Emulate Docker CLI using
  podman` banner is normal and is not an error.
- **Always use `docker compose exec -T backend ...`** when piping stdin (heredocs). Without `-T` the
  command may hang or mangle input.
- The `.env` file contains **real API credentials**. Never print its values, never echo a key, never
  include one in a report, a commit, or a file. When you must show a setting, print the variable name and
  whether it is set, e.g. `LLM_API_KEY: set (length 39)`.

## 2. Rules of engagement

1. **Preserve working code.** If a file already exists and its tests pass, do not rewrite it. Repair the
   smallest thing that is wrong. Never "regenerate from the guide" a file that already works.
2. **Verify, do not assume.** Steps 0–8 are claimed complete. Treat every claim as unverified until a
   command proves it.
3. **One phase at a time.** End each phase with its report and wait for approval before the next.
4. **Stop at every manual gate** (Section 8). Print the exact instructions, then wait. Do not guess a
   credential, invent a model ID, or fabricate a measurement.
5. **Never fabricate results.** If a command fails, show the real output. If a model call cannot run,
   say so — do not write plausible-looking numbers into ADR-06.
6. **Quota is finite.** The provider is on a free tier. Do not run bulk calls "to be safe". Each phase
   states its call budget; do not exceed it without asking.
7. **No new dependencies** beyond what `pyproject.toml` already has. `httpx` and `pyyaml` are present.

---

## PHASE A — Read-only audit of Steps 0–8

**Change nothing. Run only read commands.** Budget: **at most 2 live LLM calls** (A7 only).

### A1. Baseline and prerequisites

```bash
git status --short && git branch --show-current
docker compose ps
docker compose exec -T backend pytest -q 2>&1 | tail -5
grep -E "^PIPELINE_(DEIDENTIFIER|REDFLAGS)=" .env
```

Record: current branch, whether the tree is dirty, whether the suite is green, and whether M1 is live
(`rules` / `keywords`). A dirty tree is fine; note which files.

### A2. Files that should exist

```bash
ls -l backend/app/adapters/llm/ backend/scripts/ backend/tests/unit/adapters/ 2>&1
ls -l evaluation/spike/descriptions.yaml 2>&1
```

Build a table: each of the 11 files from M2 Section 1 — present or missing.

### A3. Settings completeness

```bash
docker compose exec -T backend python -c "
from app.core.config import get_settings
s = get_settings()
names = ['LLM_PROVIDER','LLM_BASE_URL','LLM_API_KEY','LLM_MODEL','LLM_TEMPERATURE','LLM_SEED',
         'LLM_JSON_MODE','LLM_SCHEMA_IN_PROMPT','LLM_SCHEMA_SIMPLIFY','LLM_REASONING_EFFORT',
         'LLM_MAX_RPM','LLM_HTTP_RETRIES','LLM_RATE_LIMIT_WAIT_S','OLLAMA_BASE_URL','OLLAMA_MODEL',
         'OLLAMA_JSON_MODE','GEMINI_API_KEY','GEMINI_MODEL','GEMINI_RPM','GEMINI_REASONING_EFFORT',
         'GROQ_API_KEY','GROQ_MODEL','GROQ_RPM','GROQ_JSON_MODE']
for n in names:
    if not hasattr(s, n):
        print(f'{n}: MISSING FROM Settings'); continue
    v = getattr(s, n)
    if 'KEY' in n:
        print(f'{n}: ' + (f'set (length {len(str(v))})' if v else 'EMPTY'))
    else:
        print(f'{n}: {v!r}')
"
```

Flag: any field missing from `Settings`; any secret-bearing field that is empty; `LLM_TEMPERATURE` that is
a non-empty value while the provider is a Gemini 3-family model (the M2 guide requires blank there).

Also confirm `.env.example` lists every one of these with placeholder values, and that `.env` is in
`.gitignore`:

```bash
git check-ignore -v .env || echo "WARNING: .env is NOT git-ignored"
git grep -n -E "AIza[0-9A-Za-z_-]{20,}|gsk_[0-9A-Za-z]{20,}" || echo "no keys committed"
```

### A4. Adapter correctness

Read `backend/app/adapters/llm/hosted.py` and check it against the M2 guide's version. Confirm each of
these is true, and report any that are not:

- [ ] maps timeout → `LLMTimeout`, transport error → `LLMUnavailable`, bad JSON → `LLMInvalidOutput`
- [ ] retries only 408/429/5xx; honours `Retry-After`; fails fast past `LLM_RATE_LIMIT_WAIT_S`
- [ ] 4xx other than 408/429 is **not** retried
- [ ] never logs prompt, response content, or provider error text (`log.` calls carry no message body)
- [ ] `last_error_detail` exists and is documented as dev-script-only
- [ ] `opt_float("")` returns `None` so a blank temperature sends nothing
- [ ] `simplify_schema` inlines `$ref`/`$defs` and strips `title`
- [ ] `_system_with_hint` embeds the schema when `LLM_SCHEMA_IN_PROMPT` or non-`json_schema` mode
- [ ] `RateLimiter` is wired from `LLM_MAX_RPM`

### A5. Registry wiring and the safety guard

```bash
grep -n -A6 -E "hosted|ollama" backend/app/pipeline/registry.py | head -40
```

Confirm the `hosted`/`ollama` branches lazily import the real classes and call `from_settings`, and that
the guard refusing (real LLM + mock de-identifier) is intact. **Do not edit yet.**

### A6. Tests

```bash
docker compose exec -T backend pytest -q tests/unit/adapters 2>&1 | tail -20
```

Expected: 29 passing. Report the actual number and any failures.

### A7. Live connectivity (max 2 calls)

```bash
docker compose exec -T backend python -m scripts.llm_ping
docker compose exec -T backend python -m scripts.llm_schema_check
```

Report both verbatim. These two results decide Phase C.

### A8. Spike inputs

```bash
docker compose exec -T backend python -c "
import yaml, pathlib
p = pathlib.Path('/evaluation/spike/descriptions.yaml')
if not p.exists(): print('MISSING'); raise SystemExit
d = yaml.safe_load(p.read_text())
todo = [c['id'] for c in d if str(c.get('text','')).strip().upper().startswith('TODO')]
print('entries:', len(d), '| TODO still present:', todo)
print('species:', sorted({c.get('species') for c in d}))
print('ids:', [c['id'] for c in d])
"
docker compose exec -T db psql -U triageai -d triageai -c "select code from presenting_complaints order by sort_order;"
```

Cross-check that every `expected_primary` is a real complaint code. Report mismatches.

### Phase A deliverable — the audit report

Produce exactly this, then **stop**:

1. **Step-by-step verdict table:** Steps 0,1,2,3,4,5,6,7,8 → `PASS` / `PARTIAL` / `FAIL` / `NOT APPLICABLE`,
   with one line of evidence each (the command output that proves it).
2. **Defect list**, each with: file, what is wrong, severity (blocker / should-fix / cosmetic), and the
   smallest proposed fix.
3. **Manual gates reached** (Section 8), if any.
4. **Proposed plan for Phase B** — the exact edits you intend, nothing more.

Do not proceed to Phase B without approval.

---

## PHASE B — Repair only what the audit found

Apply **only** the approved fixes. After each fix:

```bash
docker compose exec -T backend pytest -q tests/unit/adapters 2>&1 | tail -5
```

Rules:

- If a file is missing, create it from the M2 guide's version verbatim.
- If a file exists but deviates, change only the deviating part. Explain why each change is needed.
- If `Settings` is missing fields, add them inside the existing class; do not reorder or rename existing ones.
- If `.env` lacks a variable the code needs, **stop** — that is a manual gate (Section 8, G1).
- Re-run the full suite at the end: `docker compose exec -T backend pytest -q`.

**Phase B deliverable:** diff summary, test results before and after, and confirmation that Steps 0–8 now
all read `PASS`. Then stop for approval.

---

## PHASE C — Step 9: determinism, starting from the current failure

**Known state:** all 8 runs fail with `ValidationError` and `last_error_kind = None`. That means the HTTP
call succeeded and returned parseable JSON, but it did not satisfy `ExtractionOutput`. This is a
**schema-conformance problem, not a transport problem.**

### C1. Diagnose before changing anything (1 call)

```bash
docker compose exec -T backend python - <<'PY'
import json
from app.core.config import get_settings
from app.pipeline.types import ExtractionOutput
from scripts._llm import provider_from_settings
from scripts.llm_schema_check import TEXT

llm = provider_from_settings(get_settings())
raw = llm.complete_json(
    system="You extract clinical facts from a pet owner's description. JSON only.",
    user=f"Species: CAT\n\n<owner_description>\n{TEXT}\n</owner_description>",
    json_schema=ExtractionOutput.model_json_schema(), timeout_s=90)
print("RAW RESPONSE:"); print(json.dumps(raw, indent=2))
try:
    ExtractionOutput.model_validate(raw); print("\nVALID")
except Exception as e:
    print("\nINVALID:"); print(e)
PY
```

Report the raw JSON and the exact Pydantic error.

### C2. Classify the cause and apply the matching fix

| Pydantic error | Cause | Fix (in this order) |
|---|---|---|
| `species` enum mismatch (`'cat'`, `'Cat'`) | Model returns lowercase | Tighten the **determinism script's** system message: add `Use exactly "DOG" or "CAT" for species, uppercase.` |
| `Field required` on a list field | Provider does not enforce `required` on nested objects | 1) add to the script's system message: `Include every field. Use [] for empty lists and null for unknown strings.` 2) if still failing, set `LLM_JSON_MODE=json_object` in `.env`, restart backend, retry |
| `evidence_spans` item shape wrong | Model returns strings or different keys | Add to the script's system message an explicit example: `evidence_spans entries look like {"field": "onset_duration", "text": "since this morning"}` |
| `Input should be a valid list` | Model returned a string where a list belongs | Same as the `Field required` ladder |
| Something else | — | **Stop and report.** Do not invent a fix. |

**Constraint:** the fix goes in `scripts/llm_determinism.py`'s inline `system=` string, or in `.env`
settings — **never** in `app/pipeline/types.py`. The contract is fixed by `CLAUDE.md` §8.1 and P05;
loosening it to make a test pass would corrupt M3, M6 and the evaluation.

If `LLM_JSON_MODE` must change, note it: M3 and M6 inherit this setting, and the change belongs in ADR-06.

### C3. Run the real test (8 calls)

```bash
docker compose exec -T backend python -m scripts.llm_determinism --runs 8
```

### C4. Interpret and record

| Outcome | Action |
|---|---|
| `distinct KEY-FIELD results: 1` | Stable. Record the figure. |
| `> 1` on a Gemini 3-family model with blank `LLM_TEMPERATURE` | Expected. Try `LLM_SEED=42`, restart, rerun **once**. If still unstable, record the measured agreement (e.g. `6/8`) as the honest NFR-23 baseline. Do **not** keep retrying. |
| `> 1` on Groq/Ollama at temperature 0 | Verify the temperature actually reached the provider, set `LLM_SEED`, rerun once. |
| `successful runs: 0/8` after C2 | **Stop and report.** |

**Never** add caching to make a rerun look reproducible.

**Phase C deliverable:** the diagnosis, the fix applied and why, the final script output verbatim, and a
one-line NFR-23 statement, e.g. `Gemini <model>, temperature default, seed unset: key fields identical in
8/8 runs.` Then stop.

---

## PHASE D — Step 10: the comparison spike

### D1. Manual gate check

Before running anything, verify all of these. If any fails, **stop** and print the Section 8 instructions:

- `evaluation/spike/descriptions.yaml` has ≥ 10 entries, no `TODO`, every `expected_primary` a real code (gate **G2**)
- at least a second candidate is configured: `GEMINI_*` and/or `GROQ_*` populated, or Ollama reachable (gate **G3**)

Ollama reachability:

```bash
docker compose exec -T backend python -c "import httpx; print(httpx.get('http://host.docker.internal:11434/api/tags', timeout=5).status_code)"
```

### D2. Run each configured candidate

Budget: **30 calls per candidate** (10 descriptions × 3 runs). Run them one at a time, and report after each.

```bash
docker compose exec -T backend python -m scripts.llm_spike --candidate gemini
docker compose exec -T backend python -m scripts.llm_spike --candidate groq
docker compose exec -T backend python -m scripts.llm_spike --candidate ollama
```

Skip any candidate that is not configured, and say so. If a run dies on `rate_limited`, report how far it
got and **stop** — do not retry into a daily quota.

### D3. Also measure determinism per candidate

For each candidate that completed D2, switch `.env` to it, restart the backend, and run
`scripts.llm_determinism --runs 8` (8 calls each). This supplies the stability tie-break.

### D4. Apply the selection rule

In order, stopping at the first rule that separates candidates:

1. **Gates:** JSON valid ≥ 90%, schema check passed, p50 ≤ 5 s per call.
2. **Stability:** prefer the candidate stable in D3.
3. **Accuracy:** complaint accuracy, then red-flag accuracy.
4. **Headroom:** fewer 429s, larger daily limit.
5. **Data terms:** prefer the one that does not train on free-tier data.

**Phase D deliverable:** the Markdown table rows printed by each spike run, the CSV paths, the per-candidate
determinism results, and a **recommendation with the rule number that decided it**. The final choice is the
owner's (gate **G4**) — present the recommendation and stop.

---

## PHASE E — Step 11: record the decision in ADR-06

After the owner confirms the winner:

1. Fill the selection table in `docs/adr/ADR-06-llm-provider-adapter.md` with real measured numbers only.
2. Add the chosen model ID, the date, and the `LLM_TEMPERATURE` actually used.
3. Add the Step 9 stability result.
4. Confirm the amendment section (temperature and free-tier terms) is present; it ships with the v1.3
   package. If your measurements contradict it, note the contradiction — do not delete it.
5. If `LLM_JSON_MODE` changed in Phase C, record that and why.
6. Note in the ADR that **TBD-1 is closed**, and remind the owner that the SRS TBD list is theirs to edit
   (gate **G5**).

**Phase E deliverable:** the ADR-06 diff.

---

## PHASE F — Step 12: final verification, then hand back

### F1. Settings sanity

Set `.env` to the winner (or back to `mock` to conserve quota — ask the owner which), then:

```bash
docker compose up -d --force-recreate backend
docker compose exec -T backend python -m scripts.llm_ping
docker compose exec -T backend pytest -q
```

### F2. Prove the safety guard still holds

```bash
# temporarily: PIPELINE_DEIDENTIFIER=mock with a real LLM_PROVIDER
docker compose up -d --force-recreate backend
docker compose logs --tail 30 backend     # MUST show the startup refusal
# then restore PIPELINE_DEIDENTIFIER=rules and recreate
```

Report the refusal message verbatim. If the backend starts instead, that is a **blocker** — stop and report.

### F3. Confirm nothing leaked

```bash
git status --short
git check-ignore -v .env
git grep -n -E "AIza[0-9A-Za-z_-]{20,}|gsk_[0-9A-Za-z]{20,}" || echo "clean"
ls evaluation/results/ 2>/dev/null
```

`.env` must not be staged. `evaluation/results/*.csv` must be git-ignored.

### F4. Stage, but do not commit

```bash
git add backend/ docs/adr/ docs/dev-prompts/ .env.example docker-compose.yml evaluation/spike/
git status --short
```

Then print, for the owner to run:

```
git commit -m "feat(llm): provider adapter, rate limiting and model selection (IR-12, NFR-23)"
git push -u origin feat/m2-llm-provider
```

**Phase F deliverable — final report:**

- Steps 0–12: final status each
- Files created / modified / left untouched
- Test counts before and after
- Total live LLM calls consumed, per provider
- The NFR-23 figure, and the chosen model
- Anything deferred, with the reason
- The PR description, including a line recording the §8 exception:
  *"M2 adapter code written by Claude Code under a scoped exception to CLAUDE.md §8, granted by the project
  owner. Prompt templates, the safety validator and the de-identification stage remain manual."*

---

## 8. Manual gates — stop, instruct, wait, verify

At each gate: print what is needed, why, and the exact command or click-path. Then **wait**. When the owner
says done, re-run the verification command before continuing.

| ID | Trigger | What the owner must do | How Claude Code verifies |
|---|---|---|---|
| **G1** | A required `.env` variable is missing or empty | Add the variable locally. Claude Code must name the variable only, never a value. | Re-run the A3 settings dump; field reports `set` |
| **G2** | `descriptions.yaml` incomplete | Write S04–S10: fictitious English owner descriptions, with `expected_primary` from the complaint list and `expected_red_flag`. Claude Code **may draft candidates for review** but the owner must approve the clinical labels. | Re-run the A8 check: ≥ 10 entries, no TODO, codes valid |
| **G3** | A second candidate is not configured | Create a Groq key at `console.groq.com/keys`, or install Ollama (M2 Step 8) and set `OLLAMA_HOST=0.0.0.0:11434` | Re-run the D1 reachability check |
| **G4** | The spike is complete | Choose the model. Claude Code recommends; the owner decides. | Owner states the choice |
| **G5** | ADR-06 updated | Edit the SRS TBD list to close TBD-1 (document work, outside the repo) | Owner confirms |
| **G6** | Ollama needed but not installed | M2 Step 8 install steps | `/api/tags` returns 200 |

## 9. Hard stop conditions

Stop immediately and report, without attempting a workaround, if any of these occur:

- the startup safety guard fails to refuse (real LLM + mock de-identifier starts)
- a fix would require editing `app/pipeline/types.py`, `safety.py`, `action_validator.py`, or anything under
  `app/services/` or `app/models/`
- an API key appears in a diff, a log, or a file other than `.env`
- a provider returns `auth` errors after a credential was confirmed set
- the full test suite goes from green to red and the cause is not an M2 file
- daily quota is exhausted mid-phase
- anything in `CLAUDE.md` contradicts this document — `CLAUDE.md` wins, and you ask
