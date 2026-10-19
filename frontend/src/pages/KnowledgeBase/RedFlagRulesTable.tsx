/**
 * The red-flag rules tab (FR-12, FR-23, NFR-08, BR-04 · W-08 §5).
 *
 * A rule sets the minimum urgency category for a case whose description matches
 * its phrases, so this table is the safety floor in one place. Three things it
 * has to be honest about:
 *
 * - **Approval is what makes a rule real.** A rule anyone creates is unapproved
 *   and changes no triage until a KB approver approves it, which also publishes
 *   a knowledge-base version (NFR-08). Both actions here are the approver's:
 *   retiring a rule *lowers* the floor.
 * - **`is_active` is the pipeline's answer, not a guess.** It is what
 *   `get_active_rules` would say for this rule in the environment the server is
 *   actually running in, so the table cannot imply that an unapproved
 *   placeholder is screening cases in production.
 * - **The minimum category is never colour alone** (IR-03): every row renders a
 *   `VtlBadge`, which prints the code and its target waiting time.
 *
 * The phrases themselves are not here and never will be: they are maintained by
 * hand in `knowledge_base/red_flag_phrases.yaml` (M1), and `phrases_ref` is the
 * key that points at them.
 */
import type { RedFlagRuleOut } from "../../api/kb";
import { VtlBadge } from "../../components/VtlBadge";
import { strings } from "../../i18n/strings";
import { formatDisplayTime } from "../../lib/datetime";
import styles from "./KnowledgeBase.module.css";

const copy = strings.knowledgeBase;
const rulesCopy = copy.rules;

export function RedFlagRulesTable({
  rules,
  isPending,
  isError,
  canApprove,
  isBusy,
  onApprove,
  onRetire,
}: {
  rules: readonly RedFlagRuleOut[] | undefined;
  isPending: boolean;
  isError: boolean;
  /** Approving or retiring a rule is the KB approver's (BR-04, NFR-08). */
  canApprove: boolean;
  isBusy: boolean;
  onApprove: (ruleId: string) => void;
  onRetire: (ruleId: string) => void;
}) {
  if (isError) {
    return (
      <p className={styles.error} role="alert">
        {copy.errors.unexpected}
      </p>
    );
  }

  if (isPending || rules === undefined) {
    return <p className={styles.notice}>{rulesCopy.loading}</p>;
  }

  return (
    <section className={styles.rulesCard}>
      <h2 className={styles.detailTitle}>{rulesCopy.heading}</h2>
      <p className={styles.note}>{rulesCopy.note}</p>

      {rules.length === 0 ? (
        <p className={styles.notice}>{rulesCopy.empty}</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">{rulesCopy.columns.rule}</th>
              <th scope="col">{rulesCopy.columns.minCategory}</th>
              <th scope="col">{rulesCopy.columns.species}</th>
              <th scope="col">{rulesCopy.columns.status}</th>
              <th scope="col">{rulesCopy.columns.approval}</th>
              {canApprove && (
                <th scope="col">
                  <span className="visuallyHidden">{copy.viewRules}</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {rules.map((rule) => (
              <tr key={rule.id} className={styles.row}>
                <td data-label={rulesCopy.columns.rule}>
                  <b>{rule.label}</b>
                  <span className={styles.ruleCode}>{rule.code}</span>
                  {rule.is_placeholder && (
                    <span className={styles.placeholderBadge} title={rulesCopy.placeholderHint}>
                      {rulesCopy.placeholderBadge}
                    </span>
                  )}
                </td>
                <td data-label={rulesCopy.columns.minCategory}>
                  <VtlBadge category={rule.min_category} />
                  <span className={styles.minimumSuffix}>{copy.detail.minimumSuffix}</span>
                </td>
                <td data-label={rulesCopy.columns.species}>
                  {rule.species.map((name) => copy.species[name]).join(", ")}
                </td>
                <td data-label={rulesCopy.columns.status}>{statusText(rule)}</td>
                <td data-label={rulesCopy.columns.approval}>{approvalText(rule)}</td>
                {canApprove && (
                  <td>
                    {rule.retired_at === null &&
                      (rule.approved_at === null ? (
                        <button
                          type="button"
                          className={styles.secondary}
                          disabled={isBusy}
                          onClick={() => onApprove(rule.id)}
                        >
                          {rulesCopy.approve}
                        </button>
                      ) : (
                        <button
                          type="button"
                          className={styles.danger}
                          disabled={isBusy}
                          onClick={() => onRetire(rule.id)}
                        >
                          {rulesCopy.retire}
                        </button>
                      ))}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

/** Whether this rule is screening cases right now, in this environment. */
function statusText(rule: RedFlagRuleOut): string {
  if (rule.retired_at !== null) {
    return rulesCopy.retiredStatus;
  }
  return rule.is_active ? rulesCopy.screening : rulesCopy.notScreening;
}

function approvalText(rule: RedFlagRuleOut): string {
  if (rule.approved_by_name === null) {
    return rulesCopy.notApproved;
  }
  const approved = rulesCopy.approvedBy.replace("{name}", rule.approved_by_name);
  const at = rule.approved_at === null ? null : formatDisplayTime(rule.approved_at);
  return at === null ? approved : `${approved} · ${at}`;
}
