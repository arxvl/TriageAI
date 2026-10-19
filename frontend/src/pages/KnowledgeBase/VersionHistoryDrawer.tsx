/**
 * The W-08 version history drawer (FR-54, DR-05, ADR-14).
 *
 * Every approval and every retirement publishes a new immutable knowledge-base
 * version, and a recommendation records the version it was produced from. So
 * this list is what makes an old recommendation explainable: it says which
 * knowledge existed when, who published it, and how many entries it held.
 *
 * A published version is never modified — the database enforces that with a
 * trigger — so nothing here is editable.
 */
import { useQuery } from "@tanstack/react-query";

import { listVersions } from "../../api/kb";
import { strings } from "../../i18n/strings";
import { formatDisplayDate, formatDisplayTime } from "../../lib/datetime";
import styles from "./KnowledgeBase.module.css";

const copy = strings.knowledgeBase.versions;

export function VersionHistoryDrawer({ onClose }: { onClose: () => void }) {
  const versions = useQuery({ queryKey: ["kb", "versions"], queryFn: listVersions });

  return (
    <section className={styles.drawer} aria-label={copy.heading}>
      <div className={styles.drawerHeader}>
        <h2 className={styles.sectionTitle}>{copy.heading}</h2>
        <button type="button" className={styles.link} onClick={onClose}>
          {copy.close}
        </button>
      </div>

      {versions.isPending ? (
        <p className={styles.notice}>{copy.loading}</p>
      ) : versions.isError ? (
        <p className={styles.error} role="alert">
          {strings.knowledgeBase.errors.unexpected}
        </p>
      ) : versions.data.length === 0 ? (
        <p className={styles.notice}>{copy.empty}</p>
      ) : (
        <ol className={styles.versionList}>
          {versions.data.map((version) => (
            <li key={version.id} className={styles.versionItem}>
              <b>{copy.label.replace("{version}", String(version.version_no))}</b>
              <span>{publishedAtText(version.published_at)}</span>
              <span>
                {version.published_by_name === null
                  ? copy.publishedBySystem
                  : copy.publishedBy.replace("{name}", version.published_by_name)}
              </span>
              <span>{copy.entryCount.replace("{count}", String(version.entry_count))}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/** "12 Oct 2026 · 4:05 PM" in the clinic's timezone (CLAUDE.md §7). */
function publishedAtText(publishedAt: string | null): string {
  if (publishedAt === null) {
    return strings.knowledgeBase.notAvailable;
  }
  // The clinic's own day and time, from the one instant: taking the date from
  // the UTC string and the time from Manila would disagree across midnight.
  const day = formatDisplayDate(publishedAt);
  const time = formatDisplayTime(publishedAt);
  if (day === null || time === null) {
    return strings.knowledgeBase.notAvailable;
  }
  return `${day} · ${time}`;
}
