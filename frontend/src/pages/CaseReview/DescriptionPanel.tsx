/**
 * W-04 panel 1: what the owner said, with the evidence marked (FR-13, FR-31).
 *
 * This is the panel the whole screen is ordered around. ADR-15 puts the owner's
 * own words first and the AI's answer last, so a reviewer reads the evidence
 * before the conclusion drawn from it — the structural defence against
 * automation bias.
 *
 * The highlights come with a complication worth stating plainly. The extraction
 * never saw this text: it saw the de-identified version, and its evidence spans
 * are offsets into *that* string (ADR-10). Where the two differ, a highlight
 * drawn over the original would mark the wrong words — so the panel shows the
 * de-identified text instead and says it is doing so. Where they are identical,
 * which is every case with nothing to redact, the verbatim text is shown.
 *
 * Spans the server could not place come back `found: false`. They are listed
 * underneath as quoted text rather than dropped: the extraction claimed that
 * evidence, and silently showing less than it claimed would hide a disagreement
 * between the stored extraction and the stored text.
 */
import type { CaseDescription, CaseExtraction } from "../../api/cases";
import { strings } from "../../i18n/strings";
import { highlightSegments, unmatchedSpans } from "../../lib/evidenceHighlight";
import styles from "./CaseReview.module.css";

const copy = strings.caseReview;

export function DescriptionPanel({
  description,
  extraction,
}: {
  description: CaseDescription;
  extraction: CaseExtraction | null;
}) {
  // The offsets index into the de-identified text, so that is the only string
  // they may be laid over. Without one there is nothing to highlight against.
  const canHighlight = description.deidentified_text !== null;
  const text = description.differs
    ? description.deidentified_text ?? description.text
    : description.text;

  const spans = extraction?.evidence_spans ?? [];
  const segments = canHighlight ? highlightSegments(text, spans) : [{ text, fields: [] }];
  const unplaced = unmatchedSpans(spans);

  return (
    <section className={`${styles.panel} ${styles.panelDescription}`}>
      <h2 className={styles.panelTitle}>{copy.descriptionTitle}</h2>

      <p className={styles.description}>
        {segments.map((segment, index) =>
          segment.fields.length === 0 ? (
            <span key={index}>{segment.text}</span>
          ) : (
            <mark key={index} className={styles.mark} title={fieldNames(segment.fields)}>
              {segment.text}
            </mark>
          ),
        )}
      </p>

      {spans.length > 0 && <p className={styles.note}>{copy.highlightNote}</p>}
      {description.differs && <p className={styles.note}>{copy.deidentifiedNote}</p>}

      {unplaced.length > 0 && (
        <div className={styles.unmatched}>
          <b>{copy.unmatchedEvidenceTitle}</b>
          <ul className={styles.unmatchedList}>
            {unplaced.map((span, index) => (
              <li key={index}>
                {copy.unmatchedEvidence
                  .replace("{field}", fieldNames([span.field]))
                  .replace("{text}", span.text)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/**
 * The extraction fields a highlight belongs to, as the reviewer's own words.
 *
 * A field with no entry in `strings` falls back to its own name rather than
 * disappearing: the tooltip would be wrong, but a silent gap would be worse, and
 * the field names are the contract in `pipeline/types.py`.
 */
function fieldNames(fields: readonly string[]): string {
  const labels: Record<string, string> = copy.fields;
  return fields.map((field) => labels[field] ?? field).join(" · ");
}
