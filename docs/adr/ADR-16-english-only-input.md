# ADR-16: English-only input, with staff translating at intake

- **Status:** Accepted
- **Requirements:** FR-18, NFR-27, TBD-5
- **Supersedes:** the earlier best-effort Taglish handling (SRS v1.0, FR-18)
- **Related:** ADR-07, ADR-10, ADR-15

## Context

Owners in the Bicol region describe symptoms in Bikol, Filipino or a mix with
English. SRS v1.0 said the system SHOULD process code-switched descriptions on a
best-effort basis, with the extent of support left open as TBD-5.

Instructor feedback on PD2 asked for the scope to be settled. Supporting mixed
input properly would require multilingual red-flag phrases, multilingual
extraction prompts and multilingual vignettes — each needing review by a native
speaker as well as by the veterinarian — inside a four-week window before PD8.

## Decision

**All input, stored content and interface text is English.**

- The Case Intake form (W-03) instructs staff: enter the description in English,
  translate Filipino or Bikol wording the owner used, and keep the owner's exact
  wording in quotation marks when the meaning is uncertain.
- Red-flag phrases (the keyword screener), the extraction and generation prompts,
  knowledge-base entries and evaluation vignettes are English only.
- No language detection and no translation component is built.
- Interface strings still live in resource files, so a translated UI can be added
  later without code changes (NFR-27).
- Automatic processing of non-English descriptions is **out of scope** and
  recorded as future work.

## Consequences

**Positive**

- One language to write phrases, prompts and vignettes for, and one reviewer
  profile to validate them. This is what makes the PD8 timeline realistic.
- Evaluation metrics measure triage reasoning rather than language handling,
  which matters with a small vignette set where per-language results would be
  meaningless.
- The English embedding model becomes a legitimate default (ADR-07), giving a
  longer input limit and larger chunks.

**Negative**

- **Staff translation becomes an unverified step in a safety path.** If a
  translation drops a warning sign, the red-flag screener never sees it. This is
  the main cost of the decision and is stated as a limitation.
- The stored description is the staff member's English rendering, not the
  owner's words, even though the field is verbatim and immutable (FR-05). The
  quotation-mark instruction partly mitigates this.
- Real-world language handling cannot be measured, so the project cannot claim
  anything about it.
- Adding Filipino later means new phrase lists, prompts, embedding checks and
  vignettes.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Keep best-effort Taglish (SRS v1.0) | Untestable claim within the timeline; the phrase and vignette work would need native-speaker review the project cannot schedule |
| Full multilingual support as a requirement | Doubles the content work in the highest-risk weeks; the small vignette set could not evidence it |
| Store the owner's original text and an English translation side by side | Considered; deferred as TBD-5 because it changes the intake form and the de-identification surface |
