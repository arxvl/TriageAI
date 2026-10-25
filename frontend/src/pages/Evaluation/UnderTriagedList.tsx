/**
 * The under-triaged vignettes of W-10 (NFR-14): every vignette the pipeline
 * placed in a less urgent category than the reference, to forward to the
 * veterinary reviewer.
 *
 * The API sends the whole list. The first rows show and the rest fold into
 * "+ N more", as W-10 draws it, so a long list does not push the export buttons
 * off screen; nothing is dropped, and "Show all" opens it.
 */
import { useState } from "react";

import type { UnderTriagedVignette } from "../../api/eval";
import { VtlBadge } from "../../components/VtlBadge";
import { strings } from "../../i18n/strings";
import styles from "./Evaluation.module.css";
import { fill } from "./runFormat";

const copy = strings.evaluation.underTriaged;

/** Rows shown before the rest fold away; W-10 shows three. */
export const UNDER_TRIAGED_PREVIEW_ROWS = 3;

export function UnderTriagedList({ items }: { items: readonly UnderTriagedVignette[] }) {
  const [showAll, setShowAll] = useState(false);

  const visible = showAll ? items : items.slice(0, UNDER_TRIAGED_PREVIEW_ROWS);
  const hidden = items.length - visible.length;

  return (
    <section className={styles.panel} aria-labelledby="eval-under-title">
      <h2 id="eval-under-title" className={styles.panelTitle}>
        {copy.title}
      </h2>

      {items.length === 0 ? (
        <p className={styles.notice}>{copy.none}</p>
      ) : (
        <>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">{copy.columns.vignette}</th>
                <th scope="col">{copy.columns.reference}</th>
                <th scope="col">{copy.columns.predicted}</th>
                <th scope="col">{copy.columns.complaint}</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((item) => (
                <tr key={item.external_id}>
                  <td>{item.external_id}</td>
                  <td>
                    <VtlBadge category={item.reference} />
                  </td>
                  <td>
                    <VtlBadge category={item.predicted} />
                  </td>
                  <td>{item.primary_complaint ?? copy.noComplaint}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {items.length > UNDER_TRIAGED_PREVIEW_ROWS ? (
            <p className={styles.helper}>
              {hidden > 0 ? `${fill(copy.more, { count: hidden })} ` : null}
              <button type="button" className={styles.link} onClick={() => setShowAll(!showAll)}>
                {showAll ? copy.showFewer : copy.showAll}
              </button>
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
