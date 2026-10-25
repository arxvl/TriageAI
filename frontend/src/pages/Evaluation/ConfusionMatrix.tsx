/**
 * The confusion matrix of W-10 (FR-66): rows are the reference category, columns
 * the predicted one, both in VTL order.
 *
 * Cells right of the diagonal are cases predicted *less* urgent than the
 * reference, i.e. under-triage, which is the error that matters here (NFR-14).
 * They are marked with a heavier border as well as the note under the table, so
 * the distinction does not rest on colour (IR-03).
 */
import type { VTLCategory } from "../../api/cases";
import { strings } from "../../i18n/strings";
import styles from "./Evaluation.module.css";

const copy = strings.evaluation.matrix;

export function ConfusionMatrix({
  labels,
  matrix,
}: {
  labels: readonly VTLCategory[];
  matrix: readonly (readonly number[])[];
}) {
  return (
    <section className={styles.panel} aria-labelledby="eval-matrix-title">
      <h2 id="eval-matrix-title" className={styles.panelTitle}>
        {copy.title}
      </h2>
      <table className={styles.matrix}>
        <thead>
          <tr>
            <th scope="col">
              <span className="visuallyHidden">{`${copy.reference} / ${copy.predicted}`}</span>
            </th>
            {labels.map((label) => (
              <th key={label} scope="col">
                <span className="visuallyHidden">{`${copy.predicted} `}</span>
                {strings.vtl.names[label]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {labels.map((reference, row) => (
            <tr key={reference}>
              <th scope="row">
                <span className="visuallyHidden">{`${copy.reference} `}</span>
                {strings.vtl.names[reference]}
              </th>
              {labels.map((predicted, column) => {
                const kind =
                  column === row ? styles.diagonal : column > row ? styles.underTriage : undefined;
                return (
                  <td key={predicted} className={kind}>
                    {matrix[row]?.[column] ?? 0}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className={styles.helper}>{copy.note}</p>
    </section>
  );
}
