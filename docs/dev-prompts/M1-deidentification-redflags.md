# M1 — De-identification and Red-Flag Screening (Manual)

**Owner:** Lane B · **Branch:** `feat/m1-deidentify-redflags`
**Do after:** P05 (P08 recommended for approved rules)
**Requirements:** FR-12, NFR-05, IR-20, SR-08, ADR-09, ADR-10

You will build the two rule-based text stages that run **before** any AI:

- `RuleBasedDeidentifier` removes owner identifiers. It fails closed.
- `KeywordRedFlagScreener` raises alerts from approved red-flag phrases in about a second.

Both plug into the existing pipeline through `.env`. No other code changes are needed.

## Prerequisites

- [ ] P05 merged. The pipeline runs on mocks and `DEMO_1` shows an alert.
- [ ] P06 merged before Part C step 3. It adds `extraction_results.input_text`, which the database check reads.
- [ ] You have read CLAUDE.md §8.1–§8.3 (contracts, class names, `from_settings`).
- [ ] You have a draft red-flag list to send to the veterinary reviewer. The P02 seed placeholders are a starting point.

---

## Part A — Rule-based de-identifier

### Step A1. Decide what counts as an identifier

| Identifier | Replace with | Detection |
|---|---|---|
| Owner name typed in the text | `[OWNER]` | Exact match of the stored `owner_name` (full name, case-insensitive), plus each name part of 3 or more letters, case-sensitive and capitalized |
| Owner contact number | `[PHONE]` | Digits of the stored `contact_number`, with any separators |
| Philippine mobile numbers | `[PHONE]` | `09xx xxx xxxx`, `+63 9xx …`, `639xx…` |
| Landline numbers | `[PHONE]` | 7–10 digits with an optional area code |
| E-mail addresses | `[EMAIL]` | Standard pattern |
| Street addresses | `[ADDRESS]` | Only with Philippine address markers: Blk/Block + number, Lot + number, Purok/Zone + number, Brgy./Barangay/Sitio + name, `<number> <Name> St./Street/Ave./Road` |

Name parts are matched **case-sensitive and capitalized** so common words survive. Example: an owner named "Grace" must not erase "the owner said the cat seemed to recover with grace" — the capitalized `Grace` is removed, the lowercase `grace` is not. This matters because several common English words double as given names (May, Grace, Bill, Hope, Faith) or as parts of clinical phrasing.

### Step A2. Create `backend/app/pipeline/deidentify_rules.py`

```python
"""Rule-based de-identifier (M1). Fails closed: any error stops the pipeline."""
from __future__ import annotations

import re

from app.pipeline.errors import PipelineError


class DeidentificationFailed(PipelineError):
    pass


PH_MOBILE = re.compile(r"(?<!\d)(?:\+?63|0)\s?9\d{2}[\s-]?\d{3}[\s-]?\d{4}(?!\d)")
LANDLINE = re.compile(r"(?<!\d)(?:\(0\d{1,2}\)|0\d{1,2})?[\s-]?\d{3,4}[\s-]\d{4}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ADDRESS = re.compile(
    r"\b(?:(?:blk|block|lot|purok|zone)\.?\s*\d+[A-Za-z]?"
    r"|(?:brgy|barangay|sitio)\.?\s+[A-Z][\w-]*(?:\s[A-Z][\w-]*)?"
    r"|\d+\s+[A-Z][\w.-]*(?:\s[A-Z][\w.-]*)*\s(?:St|Street|Ave|Avenue|Road|Rd)\b\.?)",
    re.IGNORECASE,
)


def _digits_pattern(number: str) -> re.Pattern[str] | None:
    digits = re.sub(r"\D", "", number or "")
    if len(digits) < 7:
        return None
    return re.compile(r"[\s-]?".join(re.escape(d) for d in digits))


class RuleBasedDeidentifier:
    model_id = "rules"            # stage attributes required by CLAUDE.md §8.2
    prompt_version = "deidentify-rules-v1"
    last_latency_ms = 0

    @classmethod
    def from_settings(cls, settings, deps) -> "RuleBasedDeidentifier":
        return cls()

    def deidentify(self, text: str, owner_name: str | None, owner_contact: str | None) -> str:
        try:
            out = text
            if owner_name and owner_name.strip():
                full = owner_name.strip()
                out = re.sub(re.escape(full), "[OWNER]", out, flags=re.IGNORECASE)
                for part in re.split(r"\s+", full):
                    if len(part) >= 3 and part[0].isalpha():
                        cap = part[0].upper() + part[1:]
                        out = re.sub(rf"\b{re.escape(cap)}\b", "[OWNER]", out)
            if owner_contact:
                pat = _digits_pattern(owner_contact)
                if pat:
                    out = pat.sub("[PHONE]", out)
            out = EMAIL.sub("[EMAIL]", out)
            out = PH_MOBILE.sub("[PHONE]", out)
            out = LANDLINE.sub("[PHONE]", out)
            out = ADDRESS.sub("[ADDRESS]", out)
        except Exception as exc:  # fail closed (ADR-10)
            raise DeidentificationFailed("de-identification error") from exc

        # Final safety check: nothing that still looks like a phone or e-mail may pass.
        if EMAIL.search(out) or PH_MOBILE.search(out):
            raise DeidentificationFailed("identifier remained after de-identification")
        return out
```

**Check A2.** Run it on these strings in a Python shell:

```bash
docker compose exec backend python -c "from app.pipeline.deidentify_rules import RuleBasedDeidentifier as D; print(D().deidentify('This is Grace Cruz, 0917 123 4567. Grace says the cat vomited twice; it seems to be recovering with grace since yesterday.','Grace Cruz','09171234567'))"
```

Expected: `This is [OWNER], [PHONE]. [OWNER] says the cat vomited twice; it seems to be recovering with grace since yesterday.`

The full name and the phone number are redacted, and so is the standalone, capitalized second mention of "Grace". The lowercase "grace" later in the sentence — an ordinary English word, not the owner's name — survives, because name-part matching is case-sensitive.

### Step A3. Tests — `backend/tests/unit/pipeline/test_deidentify_rules.py`

Write at least **12** cases:

- the full owner name
- a name part inside a sentence
- a lower-case common word that equals a name part (kept)
- mobile numbers in 4 formats (`09171234567`, `0917-123-4567`, `+63 917 123 4567`, `639171234567`)
- a landline with an area code
- an e-mail address
- `Blk 5 Lot 12`
- `Brgy. San Felipe`
- `12 Magsaysay Ave.`
- clinical text with numbers that must stay: `vomited 5 times`, `4.2 kg`, `3 years`, `since 9 am`
- an empty owner reference

Add one test that monkeypatches `re.sub` to raise, and asserts that `DeidentificationFailed` is raised.

**Check A3.** `docker compose exec backend pytest -q tests/unit/pipeline/test_deidentify_rules.py` passes. **Also review every false positive by eye:** clinical content must never be removed.

---

## Part B — Keyword red-flag screener

### Step B1. Write the phrase file `knowledge_base/red_flag_phrases.yaml`

One key per rule code, matching `red_flags.yaml` (P08).

```yaml
# Phrases are matched on normalized text: lower-case, accents removed, punctuation → space.
# negatable: true  → skip the match if a negation word appears within 3 words before it.
# requires: optional species / sex conditions. Unknown sex still triggers (fail safe).
NOT_BREATHING:
  negatable: false
  phrases: ["not breathing", "stopped breathing", "no breathing", "cannot breathe", "can't breathe"]
UNRESPONSIVE:
  negatable: false
  phrases: ["unresponsive", "not responding", "won't wake up", "will not wake up", "unconscious", "collapsed"]
ACTIVE_SEIZURE:
  negatable: true
  phrases: ["seizure", "seizuring", "convulsing", "convulsion", "fitting", "shaking uncontrollably"]
UNCONTROLLED_BLEEDING:
  negatable: true
  phrases: ["bleeding a lot", "won't stop bleeding", "will not stop bleeding", "bleeding heavily", "blood everywhere", "profuse bleeding"]
MALE_CAT_NO_URINE:
  negatable: false
  requires: {species: CAT, sex: MALE}
  phrases: ["no urine", "nothing comes out", "can't pee", "cannot pee", "not peeing", "straining to pee",
            "straining in the litter box", "no urine coming out", "keeps trying to pee"]
TOXIN_INGESTION:
  negatable: true
  phrases: ["ate rat poison", "rat poison", "rodenticide", "ate chocolate", "swallowed medicine",
            "swallowed pills", "ate paracetamol", "ate poison", "drank chemicals"]
PALE_OR_BLUE_GUMS:
  negatable: true
  phrases: ["pale gums", "white gums", "blue gums", "bluish gums", "gums look pale", "gums look blue"]
```

> ⚠️ This list is a **draft**. Send it to the veterinary reviewer with the rules' minimum categories. Record the approval in `knowledge_base/APPROVALS.md`, then approve the rules in W-08 (P08). Descriptions are entered in English (FR-18), so the phrases are English only. Staff translate Filipino or Bikol wording at intake, which means the phrase list must cover the plain English that staff are likely to type, not only clinical terms.

### Step B2. Create `backend/app/pipeline/redflags_keywords.py`

```python
"""Keyword red-flag screener (M1). Deterministic; runs before any LLM call (NFR-05)."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import yaml

from app.pipeline.types import RedFlagHit

NEGATORS = {"no", "not", "never", "without", "none", "denies", "hasn't", "has not"}
PHRASES_PATH = Path(__file__).resolve().parents[3] / "knowledge_base" / "red_flag_phrases.yaml"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9' ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


class KeywordRedFlagScreener:
    model_id = "keywords"
    prompt_version = "redflag-phrases-v1"   # bump when red_flag_phrases.yaml changes
    last_latency_ms = 0

    def __init__(self, phrases: dict, rules_provider):
        self._rules_provider = rules_provider
        self._compiled = {
            code: {
                "negatable": spec.get("negatable", False),
                "requires": spec.get("requires", {}),
                "patterns": [re.compile(rf"\b{re.escape(normalize(p))}\b") for p in spec["phrases"]],
            }
            for code, spec in phrases.items()
        }

    @classmethod
    def from_settings(cls, settings, deps) -> "KeywordRedFlagScreener":
        with open(PHRASES_PATH, encoding="utf-8") as fh:
            phrases = yaml.safe_load(fh)
        return cls(phrases, deps.rules_provider)

    def screen(self, text: str, species, sex: str | None) -> list[RedFlagHit]:
        norm = normalize(text)
        active = {r.code: r for r in self._rules_provider()}
        hits: list[RedFlagHit] = []
        for code, spec in self._compiled.items():
            rule = active.get(code)
            if rule is None:  # rule not approved / retired → ignore
                continue
            req = spec["requires"]
            if req.get("species") and req["species"] != getattr(species, "value", species):
                continue
            if req.get("sex") and sex not in (None, "UNKNOWN", req["sex"]):
                continue  # unknown sex still triggers (fail safe)
            for pat in spec["patterns"]:
                m = pat.search(norm)
                if not m:
                    continue
                if spec["negatable"]:
                    preceding = norm[: m.start()].split(" ")[-4:-1] if m.start() else []
                    if NEGATORS.intersection(preceding):
                        continue
                hits.append(RedFlagHit(rule_code=code, matched_text=m.group(0),
                                       min_category=rule.min_category))
                break
        return hits
```

Adjust `PHRASES_PATH` if your container mounts `knowledge_base/` somewhere else, for example by adding a `KB_DIR` setting.

**Container note.** The backend container needs `knowledge_base/`. Add this volume to the `backend` service in `docker-compose.yml`, and copy the folder in the production Dockerfile:

```yaml
- ./knowledge_base:/knowledge_base:ro
```

### Step B3. Tests — `backend/tests/unit/pipeline/test_redflags_keywords.py`

Use a fake `rules_provider` that returns approved rules. Write a table-driven test:

| Text | Species | Sex | Expected codes |
|---|---|---|---|
| "He keeps going to the litter box but nothing comes out" | CAT | MALE | `MALE_CAT_NO_URINE` |
| same text | CAT | UNKNOWN | `MALE_CAT_NO_URINE` (fail safe) |
| same text | CAT | FEMALE | none |
| "He keeps trying to pee but no urine coming out" | CAT | MALE | `MALE_CAT_NO_URINE` |
| "He had a seizure 10 minutes ago" | DOG | – | `ACTIVE_SEIZURE` |
| "No seizures, just vomiting" | DOG | – | none (negated) |
| "Not breathing!!" | DOG | – | `NOT_BREATHING` |
| "Gums look very pale" | DOG | – | none: phrase is "pale gums". Decide with the vet whether to add "gums look pale" |
| "Ate rat poison yesterday" | DOG | – | `TOXIN_INGESTION` |
| "Itching for two weeks" | DOG | – | none |

Also test that a rule missing from `rules_provider` (unapproved) produces no hit, and that screening a 2,000-character text takes under 50 ms.

**Check B3.** All tests pass. Review misses with the vet and add phrases. **Every phrase change needs vet approval** (BR-04).

---

## Part C — Switch the stages on

1. In `.env`, set `PIPELINE_DEIDENTIFIER=rules` and `PIPELINE_REDFLAGS=keywords`.
2. Run `docker compose restart backend`. The logs must not show "module not implemented yet".
3. **End-to-end check:**
   1. Log in as intake. Submit a new male-cat case with the text: *"Since this morning he keeps going to the litter box and cries, but nothing comes out. Call me at 0917 123 4567."*
   2. The red-flag banner appears in the queue within 2 seconds (NFR-05).
   3. In the database, the stored extraction input no longer contains the number:

      ```bash
      docker compose exec db psql -U triageai -d triageai -c "select input_text from extraction_results order by created_at desc limit 1;"
      ```

      Expected: `... Call me at [PHONE].`
4. **Timing check.** Submit 10 cases and confirm `params.stage_ms.deidentify + screen` is under 100 ms.

## Done when

- [ ] Both test files pass, and the false-positive review is done.
- [ ] The vet has approved the rules and phrases; the approval is logged in `APPROVALS.md` and in W-08.
- [ ] The end-to-end check passes with the real stages enabled.
- [ ] Committed on `feat/m1-deidentify-redflags`, with a PR into `develop`.
