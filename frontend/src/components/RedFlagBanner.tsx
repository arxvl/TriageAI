/**
 * The red-flag alert area at the top of W-02 and W-04 (FR-12, NFR-05).
 *
 * The pipeline's deterministic pre-screen is what fills it: it runs before any
 * model call, which is how NFR-05's two-second promise is kept. An empty list
 * renders nothing at all, so neither screen reserves space for a banner that is
 * not there.
 *
 * The component owns the announcement and not the wording. Each alert arrives as
 * a finished `message`, because the same rule is described differently depending
 * on where it is read: the queue names the case ("Red-flag alert – C-0142: …"),
 * while the case a reviewer already has open does not ("Red flag detected by the
 * pre-screen: …"). `caseId` is likewise optional — a link back to the case you
 * are standing on leads nowhere.
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
 * One alert.
 *
 * `message` is clinic-written text about the patient and the rule that fired —
 * never the owner's description, never the text the rule matched, and never an
 * owner name (FR-07, DR-04).
 */
export interface QueueRedFlagAlert {
  /** When given, the banner offers a link to that case. */
  caseId?: string;
  message: string;
}

export function RedFlagBanner({ alerts }: { alerts: readonly QueueRedFlagAlert[] }) {
  if (alerts.length === 0) {
    return null;
  }

  return (
    <div className={styles.region} role="alert" aria-label={copy.redFlagBannerLabel}>
      {alerts.map((alert, index) => (
        // The case id is the key where there is one: it is stable across a poll
        // that re-orders the list. Without one, the index is all there is.
        <p key={alert.caseId ?? index} className={styles.banner}>
          <span className={styles.icon} aria-hidden="true">
            !
          </span>
          {alert.message}
          {alert.caseId !== undefined && (
            <Link className={styles.open} to={`/cases/${alert.caseId}`}>
              {copy.redFlagOpenCase}
            </Link>
          )}
        </p>
      ))}
    </div>
  );
}
