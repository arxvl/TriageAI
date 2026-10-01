/**
 * The red-flag alert area at the top of W-02 (FR-12, NFR-05).
 *
 * P05 is what fills it: the deterministic pre-screen runs inside the pipeline
 * and writes its alerts before any model call, which is how NFR-05's two-second
 * promise is kept. Until that exists there is nothing to announce, so the banner
 * renders nothing for an empty list — it is here now with the prop it will be
 * given, so the screen's layout, its live region and its tests are in place
 * before the alerts are.
 *
 * `role="alert"` is deliberate here, where the toast avoids it: a case that needs
 * a reviewer now is exactly the kind of thing that should interrupt whatever a
 * screen reader is in the middle of.
 */
import { Link } from "react-router-dom";

import { strings } from "../i18n/strings";
import styles from "./RedFlagBanner.module.css";

const copy = strings.queue;

/**
 * One alert. `summary` is clinic-written text about the patient — never the
 * owner's description and never an owner name (FR-07, DR-04).
 */
export interface QueueRedFlagAlert {
  caseId: string;
  caseNo: string;
  summary: string;
}

export function RedFlagBanner({ alerts }: { alerts: readonly QueueRedFlagAlert[] }) {
  if (alerts.length === 0) {
    return null;
  }

  return (
    <div className={styles.region} role="alert" aria-label={copy.redFlagBannerLabel}>
      {alerts.map((alert) => (
        <p key={alert.caseId} className={styles.banner}>
          <span className={styles.icon} aria-hidden="true">
            !
          </span>
          {copy.redFlagAlert.replace("{caseNo}", alert.caseNo).replace("{summary}", alert.summary)}
          <Link className={styles.open} to={`/cases/${alert.caseId}`}>
            {copy.redFlagOpenCase}
          </Link>
        </p>
      ))}
    </div>
  );
}
