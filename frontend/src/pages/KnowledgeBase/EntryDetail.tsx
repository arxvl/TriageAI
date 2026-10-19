/**
 * W-08's right-hand panel, read-only: the entry as it stands, and what may be
 * done to it next (FR-50, FR-51, FR-52, FR-53, IR-03, IR-08).
 *
 * The controls follow the role, and that split is the phase:
 *
 * - An **administrator** edits a draft, submits it, and retires live content.
 * - A **KB approver** approves and publishes, or rejects with comments. The
 *   approver-only note from W-08 sits beside those two buttons, because the
 *   point of the sentence is that not every reviewer sees them (BR-04, FR-52).
 *
 * Approval does not finish the job: the entry stays `PENDING_REVIEW` while a
 * `KB_INDEX` job indexes it, so this panel reports that state and, on failure,
 * the job's reason code with the entry still awaiting review (FR-53).
 *
 * Every minimum category is a `VtlBadge`, which prints the name and target time:
 * no category is ever shown as colour alone (IR-03).
 */
import type { ComplaintOption, KBEntryDetail as Entry, RedFlagRuleOut } from "../../api/kb";
import { VtlBadge } from "../../components/VtlBadge";
import { strings } from "../../i18n/strings";
import { formatCalendarDate, formatDisplayTime } from "../../lib/datetime";
import { complaintName } from "./catalogue";
import styles from "./KnowledgeBase.module.css";

const copy = strings.knowledgeBase;

export function EntryDetail({
  entry,
  isPending,
  rules,
  complaints,
  isAdministrator,
  canApprove,
  isBusy,
  nextVersionNo,
  retireWarning,
  onEdit,
  onSubmit,
  onApprove,
  onReject,
  onRetire,
}: {
  entry: Entry | undefined;
  isPending: boolean;
  rules: readonly RedFlagRuleOut[];
  complaints: readonly ComplaintOption[];
  isAdministrator: boolean;
  canApprove: boolean;
  isBusy: boolean;
  /** The version an approval would publish, named on the button (FR-54). */
  nextVersionNo: number;
  /** The consequence a retirement had that nothing refused (FR-72). */
  retireWarning: string | null;
  onEdit: () => void;
  onSubmit: () => void;
  onApprove: () => void;
  onReject: () => void;
  onRetire: () => void;
}) {
  if (isPending) {
    return <p className={styles.notice}>{copy.loading}</p>;
  }

  if (entry === undefined) {
    return <p className={styles.notice}>{copy.selectPrompt}</p>;
  }

  const isDraft = entry.status === "DRAFT";
  const isPendingReview = entry.status === "PENDING_REVIEW";
  const isActive = entry.status === "ACTIVE";
  const citationComplete =
    entry.source.title !== null &&
    entry.source.publisher !== null &&
    entry.source.url !== null &&
    entry.source.access_date !== null;

  return (
    <div className={styles.detail}>
      <div className={styles.detailHeader}>
        <h2 className={styles.detailTitle}>{entry.title}</h2>
        <span className={styles.statusChip}>{copy.tabs[entry.status]}</span>
      </div>

      <dl className={styles.facts}>
        <div>
          <dt>{copy.columns.filedUnder}</dt>
          <dd>
            {entry.urgency_category !== null ? (
              <VtlBadge category={entry.urgency_category} />
            ) : (
              complaintName(entry.complaint_code, complaints)
            )}
          </dd>
        </div>
        <div>
          <dt>{copy.columns.species}</dt>
          <dd>{entry.species.map((name) => copy.species[name]).join(", ")}</dd>
        </div>
        <div>
          <dt>{copy.kindFilterLabel}</dt>
          <dd>{copy.kinds[entry.kind]}</dd>
        </div>
        <div>
          <dt>{copy.columns.words}</dt>
          <dd>
            {(entry.kind === "URGENCY_ACTIONS" ? copy.actionCount : copy.wordCount).replace(
              "{count}",
              String(entry.word_count),
            )}
          </dd>
        </div>
      </dl>

      {entry.revises_entry_id !== null && <p className={styles.note}>{copy.detail.revisesNote}</p>}

      {entry.review_comments !== null && (
        <section className={styles.rejection}>
          <h3 className={styles.sectionTitle}>{copy.detail.rejectionHeading}</h3>
          <p className={styles.rejectionText}>{entry.review_comments}</p>
        </section>
      )}

      {retireWarning !== null && (
        <p className={styles.warning} role="status">
          {retireWarning}
        </p>
      )}

      <section>
        <h3 className={styles.sectionTitle}>{copy.detail.contentHeading}</h3>
        {/* Pre-wrapped: a baseline action set is one action per line, and the
            lines are what the pipeline reads back (FR-72, ADR-18). */}
        <p className={styles.content}>{entry.content}</p>
      </section>

      <section>
        <h3 className={styles.sectionTitle}>{copy.detail.redFlagsHeading}</h3>
        <RedFlagList codes={entry.red_flag_codes} rules={rules} />
      </section>

      <section>
        <h3 className={styles.sectionTitle}>{copy.detail.citationHeading}</h3>
        {citationComplete ? (
          <dl className={styles.facts}>
            <div>
              <dt>{copy.editor.sourceTitleLabel}</dt>
              <dd>{entry.source.title}</dd>
            </div>
            <div>
              <dt>{copy.detail.publisherLabel}</dt>
              <dd>{entry.source.publisher}</dd>
            </div>
            <div>
              <dt>{copy.detail.urlLabel}</dt>
              <dd className={styles.url}>{entry.source.url}</dd>
            </div>
            <div>
              <dt>{copy.detail.accessDateLabel}</dt>
              <dd>
                {formatCalendarDate(entry.source.access_date ?? "") ?? entry.source.access_date}
              </dd>
            </div>
          </dl>
        ) : (
          <p className={styles.warning}>{copy.detail.citationIncomplete}</p>
        )}
      </section>

      <dl className={styles.facts}>
        <div>
          <dt>{copy.detail.createdByLabel}</dt>
          <dd>{entry.created_by_name ?? copy.notAvailable}</dd>
        </div>
        <div>
          <dt>{copy.detail.approvedByLabel}</dt>
          <dd>{approvalText(entry)}</dd>
        </div>
        {entry.slug !== null && (
          <div>
            <dt>{copy.detail.slugLabel}</dt>
            <dd>{entry.slug}</dd>
          </div>
        )}
      </dl>

      {entry.indexing !== null && (
        <section className={styles.indexing}>
          <h3 className={styles.sectionTitle}>{copy.indexing.heading}</h3>
          <p className={entry.indexing.status === "FAILED" ? styles.warning : styles.note}>
            {copy.indexing[entry.indexing.status]}
          </p>
          {entry.indexing.status === "FAILED" && (
            <>
              {entry.indexing.error !== null && (
                <p className={styles.note}>
                  {copy.indexing.reason.replace("{reason}", entry.indexing.error)}
                </p>
              )}
              <p className={styles.note}>{copy.indexing.stillPending}</p>
            </>
          )}
        </section>
      )}

      <div className={styles.actions}>
        {isAdministrator && isDraft && (
          <>
            <button type="button" className={styles.secondary} disabled={isBusy} onClick={onEdit}>
              {copy.editor.edit}
            </button>
            <button type="button" className={styles.primary} disabled={isBusy} onClick={onSubmit}>
              {copy.editor.submitForReview}
            </button>
          </>
        )}

        {canApprove && isPendingReview && (
          <>
            <button type="button" className={styles.primary} disabled={isBusy} onClick={onApprove}>
              {copy.approve.replace("{version}", String(nextVersionNo))}
            </button>
            <button type="button" className={styles.secondary} disabled={isBusy} onClick={onReject}>
              {copy.reject}
            </button>
            <span className={styles.approverNote}>{copy.approverOnlyNote}</span>
          </>
        )}

        {isAdministrator && isActive && (
          <button type="button" className={styles.danger} disabled={isBusy} onClick={onRetire}>
            {copy.retire}
          </button>
        )}

        {isAdministrator && !isDraft && !isActive && (
          <span className={styles.approverNote}>{copy.editor.notEditable}</span>
        )}
      </div>
    </div>
  );
}

/** "Approved by Dr. A. Rivera · 12 Oct 2026", or that it has not been. */
function approvalText(entry: Entry): string {
  if (entry.approved_by_name === null) {
    return copy.rules.notApproved;
  }
  const at = entry.approved_at === null ? null : formatDisplayTime(entry.approved_at);
  return at === null ? entry.approved_by_name : `${entry.approved_by_name} · ${at}`;
}

/**
 * The rules this entry explains, with the minimum category each one floors a
 * case to (FR-23, FR-49).
 *
 * A code with no matching rule is still listed by its code: the link exists in
 * the database, and hiding it would make the panel disagree with the entry.
 */
function RedFlagList({
  codes,
  rules,
}: {
  codes: readonly string[];
  rules: readonly RedFlagRuleOut[];
}) {
  if (codes.length === 0) {
    return <p className={styles.note}>{copy.detail.noRedFlags}</p>;
  }

  return (
    <ul className={styles.redFlagList}>
      {codes.map((code) => {
        const rule = rules.find((candidate) => candidate.code === code);
        return (
          <li key={code} className={styles.redFlagItem}>
            <span>{rule?.label ?? code}</span>
            {rule !== undefined && (
              <span className={styles.redFlagCategory}>
                <VtlBadge category={rule.min_category} />
                <span className={styles.minimumSuffix}>{copy.detail.minimumSuffix}</span>
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
