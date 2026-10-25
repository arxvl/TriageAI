/**
 * The audit timeline for one case — W-07's right-hand panel on a route of its own
 * (FR-42, FR-43, FR-45, FR-46, ADR-12 · UC-10).
 *
 * The other half of W-07, the Case History search list (`pages/CaseHistory`),
 * shows this same timeline beside a selected row. The panel is therefore a shared
 * component and this page is only the part that is its own: the fetch, the
 * heading, and the way back to the case.
 *
 * Open to all three roles, matching the endpoint's own guard. An administrator may
 * never decide a case (BR-02) but may always read what was decided, and so may the
 * Intake Staff member who entered it: the audit trail is what makes the system
 * answerable, and a record only some of its users can read is a weaker one (FR-45).
 *
 * There is no polling here, unlike W-04. A timeline is read after the fact; a
 * reviewer who wants the newest entry has the case screen for that.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { readCaseAudit, type CaseDetail } from "../../api/cases";
import { ApiErrorCode, isApiError } from "../../api/errors";
import { AuditTimeline } from "../../components/AuditTimeline";
import { strings } from "../../i18n/strings";
import styles from "./CaseAudit.module.css";

const copy = strings.caseAudit;

export function CaseAudit() {
  const { caseId = "" } = useParams<{ caseId: string }>();

  const { data, isPending, error } = useQuery({
    queryKey: ["cases", "audit", caseId],
    queryFn: () => readCaseAudit(caseId),
  });

  // The case number for the heading, read from W-04's cache entry and never
  // fetched. Reading a case *acknowledges* its red-flag alerts (FR-12, §6.1), so
  // a page that only shows the record must not make that request: it would clear
  // the queue's banner for a reviewer who never opened the case. Arriving by the
  // "View audit" link the entry is there; reached by its URL it is not, and the
  // heading falls back to one without a case number.
  const queryClient = useQueryClient();
  const caseNo = queryClient.getQueryData<CaseDetail>(["cases", "detail", caseId])?.case_no;

  return (
    <section className={styles.page}>
      <Link className={styles.back} to={`/cases/${caseId}`}>
        {copy.backToCase}
      </Link>

      {isPending && <p className={styles.notice}>{copy.loading}</p>}

      {!isPending && data === undefined && (
        <p className={styles.error} role="alert">
          {loadErrorText(error)}
        </p>
      )}

      {data !== undefined && <AuditTimeline timeline={data} caseNo={caseNo} />}
    </section>
  );
}

/** The same mapping W-04 uses: a 404 and a 403 each say which it was (IR-05). */
function loadErrorText(error: unknown): string {
  if (isApiError(error)) {
    if (error.code === ApiErrorCode.notFound) {
      return copy.errors.notFound;
    }
    if (error.code === ApiErrorCode.forbidden) {
      return copy.errors.forbidden;
    }
  }
  return copy.errors.unexpected;
}
