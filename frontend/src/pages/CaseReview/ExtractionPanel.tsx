/**
 * W-04 panel 2: the clinical detail the extraction read (FR-09, FR-31).
 *
 * Read-only in this subphase. Correcting a value and regenerating from the
 * correction is P07, so "Save and regenerate" is on screen and disabled with the
 * tooltip the phase prompt asks for — the control is where it will be, rather
 * than appearing later and moving everything else.
 *
 * Two rows are not like the others. Red flags are shown in the danger colour
 * *and* as bold text, so the emphasis survives without colour (NFR-21). "Ask the
 * owner" is `missing_information`, renamed: to a reviewer it is not a gap in the
 * data, it is the next question to ask.
 *
 * A row with nothing in it still renders, reading "None stated". An absent value
 * and a value the extraction positively denied are different findings, and a grid
 * that quietly dropped its empty rows would make the two look the same.
 */
import type { CaseExtraction } from "../../api/cases";
import { strings } from "../../i18n/strings";
import styles from "./CaseReview.module.css";

const copy = strings.caseReview;

export function ExtractionPanel({ extraction }: { extraction: CaseExtraction | null }) {
  return (
    <section className={`${styles.panel} ${styles.panelExtraction}`}>
      <h2 className={styles.panelTitle}>{copy.extractionTitle}</h2>

      {extraction === null ? (
        <p className={styles.muted}>{copy.extractionUnavailable}</p>
      ) : (
        <Rows extraction={extraction} />
      )}

      <div className={styles.addRow}>
        <button
          type="button"
          className={`${styles.button} ${styles.buttonSmall}`}
          disabled
          title={copy.availableInP07}
        >
          {copy.saveAndRegenerate}
        </button>
      </div>
    </section>
  );
}

function Rows({ extraction }: { extraction: CaseExtraction }) {
  return (
    <dl className={styles.grid}>
      <Row label={copy.fields.species}>
        {extraction.species === null ? null : strings.queue.species[extraction.species]}
      </Row>

      <Row label={copy.fields.presenting_complaints}>
        {extraction.presenting_complaints.length === 0
          ? null
          : extraction.presenting_complaints.map((complaint) => (
              <span key={complaint.code} className={styles.gridValue}>
                {complaint.name ?? complaint.code}
                {complaint.is_primary && <b className={styles.primary}> {copy.primaryMarker}</b>}
                <br />
              </span>
            ))}
      </Row>

      <Row label={copy.fields.onset_duration}>{extraction.onset_duration}</Row>
      <Row label={copy.fields.frequency_severity}>{extraction.frequency_severity}</Row>
      <Row label={copy.fields.associated_signs}>{joined(extraction.associated_signs)}</Row>
      <Row label={copy.fields.negated_findings}>{joined(extraction.negated_findings)}</Row>
      <Row label={copy.fields.exposure_history}>{extraction.exposure_history}</Row>
      <Row label={copy.fields.relevant_history}>{extraction.relevant_history}</Row>

      <Row label={copy.fields.red_flags}>
        {extraction.red_flags.length === 0 ? null : (
          <b className={styles.redFlagValue}>{joined(extraction.red_flags)}</b>
        )}
      </Row>

      <Row label={copy.fields.missing_information}>{joined(extraction.missing_information)}</Row>
    </dl>
  );
}

/** One key and its value, or "None stated" where the extraction read nothing. */
function Row({ label, children }: { label: string; children: React.ReactNode }) {
  const isEmpty = children === null || children === undefined || children === "";

  return (
    <>
      <dt className={styles.gridKey}>{label}</dt>
      <dd className={isEmpty ? `${styles.gridValue} ${styles.muted}` : styles.gridValue}>
        {isEmpty ? copy.emptyValue : children}
      </dd>
    </>
  );
}

function joined(values: readonly string[]): string | null {
  return values.length === 0 ? null : values.join(" · ");
}
