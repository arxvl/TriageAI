/**
 * The per-case audit timeline, W-07's right-hand panel (FR-42, FR-43, FR-45,
 * FR-46, ADR-12 · UC-10).
 *
 * Three things decide its shape:
 *
 * 1. **It is presentational.** The timeline arrives as a prop, so the same panel
 *    serves the per-case route built here and, in P07, the row a reviewer selects
 *    in Case History. Nothing here fetches, polls, or caches.
 * 2. **The server owns the wording.** Each entry carries a `label` and `details`
 *    the backend composed from the audit row and its related tables; this file
 *    prints them. `action` is the stable code and is never shown — it is a hook
 *    for styling and for tests, so a translated interface can substitute its own
 *    sentences later (NFR-27).
 * 3. **It is a record, not a view of one.** The order is the meaning, so the
 *    entries are an ordered list; the caption states the append-only guarantee the
 *    database enforces (FR-43); and an interval the case has not reached prints a
 *    dash rather than disappearing, so "not yet" cannot be misread as "instant".
 *
 * Day headings are this component's one addition to the wireframe, whose sample
 * case spans a single morning. A case that arrives at 23:40 and is closed after
 * midnight would otherwise show a closing time three hours *before* it arrived —
 * the one impression an audit trail may not give.
 */
import { Fragment } from "react";

import type { AuditTimeline as AuditTimelineData, AuditTimelineItem } from "../api/cases";
import { strings } from "../i18n/strings";
import { clinicToday, formatDisplayDate, formatElapsed, formatPreciseTime } from "../lib/datetime";
import styles from "./AuditTimeline.module.css";

const copy = strings.caseAudit;

interface AuditTimelineProps {
  timeline: AuditTimelineData;
  /** The case number for the heading, when the caller knows it (W-07). */
  caseNo?: string;
}

export function AuditTimeline({ timeline, caseNo }: AuditTimelineProps) {
  const title = caseNo === undefined ? copy.titleFallback : copy.title.replace("{caseNo}", caseNo);

  return (
    <section className={styles.panel} aria-label={title}>
      <h2 className={styles.title}>{title}</h2>

      <Intervals timeline={timeline} />

      {timeline.items.length === 0 ? (
        <p className={styles.empty}>{copy.empty}</p>
      ) : (
        <ol className={styles.timeline} aria-label={copy.eventsLabel}>
          {timeline.items.map((item, index) => {
            const opensDay =
              index === 0 || clinicDay(item.ts) !== clinicDay(timeline.items[index - 1].ts);
            const day = opensDay ? formatDisplayDate(item.ts) : null;

            // Nothing in an audit entry is a stable identifier on its own: two
            // entries can share a timestamp, and the id is not sent. The index
            // is safe here because the list is read-only and never re-ordered.
            return (
              <Fragment key={index}>
                {day !== null && (
                  <li className={styles.dayItem}>
                    <p className={styles.day}>{day}</p>
                  </li>
                )}
                <Event item={item} />
              </Fragment>
            );
          })}
        </ol>
      )}

      {/* FR-43, ADR-12: a property of the database, which the server reports. */}
      {timeline.append_only && <p className={styles.caption}>{copy.appendOnly}</p>}
    </section>
  );
}

/** The two FR-46 figures above the entries, as W-07 places them. */
function Intervals({ timeline }: { timeline: AuditTimelineData }) {
  return (
    <dl className={styles.intervals} aria-label={copy.intervalsLabel}>
      <div className={styles.interval}>
        <dt className={styles.intervalLabel}>{copy.submissionToRecommendation}</dt>
        <dd className={styles.intervalValue}>
          {intervalText(timeline.submission_to_recommendation_s)}
        </dd>
      </div>
      <div className={styles.interval}>
        <dt className={styles.intervalLabel}>{copy.recommendationToDecision}</dt>
        <dd className={styles.intervalValue}>
          {intervalText(timeline.recommendation_to_decision_s)}
        </dd>
      </div>
    </dl>
  );
}

/** One entry: when, what, and who — in that order, as the panel is scanned. */
function Event({ item }: { item: AuditTimelineItem }) {
  const time = formatPreciseTime(item.ts);
  const actor = actorText(item);

  return (
    <li className={styles.event} data-action={item.action}>
      <p className={styles.headline}>
        {time !== null && (
          <>
            <time className={styles.time} dateTime={item.ts}>
              {time}
            </time>{" "}
            ·{" "}
          </>
        )}
        <b>{item.label}</b>
      </p>
      <p className={styles.detail}>
        <span className={styles.actor}>{actor}</span>
        {item.details !== null && <> · {item.details}</>}
      </p>
    </li>
  );
}

/** "Reviewer Demo (Veterinary Reviewer)", or "System" for a pipeline entry. */
function actorText(item: AuditTimelineItem): string {
  if (item.actor_name === null) {
    return copy.actorSystem;
  }
  if (item.actor_role === null) {
    return item.actor_name;
  }
  return copy.actor
    .replace("{name}", item.actor_name)
    .replace("{role}", strings.roles[item.actor_role]);
}

function intervalText(seconds: number | null): string {
  return seconds === null ? copy.intervalNotAvailable : formatElapsed(seconds);
}

/**
 * The clinic-timezone calendar day an instant falls on, as `YYYY-MM-DD`.
 *
 * Empty for a value that is not an instant, which keeps a malformed timestamp
 * from opening a day heading of its own on top of having no time to show.
 */
function clinicDay(iso: string): string {
  const instant = new Date(iso);
  return Number.isNaN(instant.getTime()) ? "" : clinicToday(instant);
}
