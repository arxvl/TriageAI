/**
 * W-04 panel 3: the AI's answer, and everything needed to check it
 * (FR-20..FR-26, FR-31, IR-03, IR-04).
 *
 * What this panel shows is deliberately never just a category:
 *
 * - **The safety floor**, when a red-flag rule raised the category rather than
 *   the model's reading (FR-23, ADR-09). A reviewer is entitled to know which of
 *   the two they are looking at, and the notice names the rule.
 * - **The rationale**, in the model's own words.
 * - **The confidence, with its reasons in plain language** (FR-24). The reasons
 *   are stored as codes; the screen maps them, and an unrecognised code falls
 *   back to a general sentence rather than printing the code at a clinician
 *   (IR-05).
 * - **Every retrieved passage, in rank order, marked as cited or not** (FR-22,
 *   FR-25). The uncited ones stay on screen: "the model had this passage and did
 *   not use it" is part of judging the answer.
 * - **The configuration footnote** — model, prompt version, knowledge-base
 *   version, time, latency — so a recommendation can be reproduced and compared
 *   (FR-26, NFR-23, ADR-14).
 *
 * The suggested-action checklist is rendered here too, beneath the rationale,
 * where ADR-18 and IR-23 put it: the actions belong to the category, and reading
 * them before the rationale would invite accepting them without it.
 */
import { useState, type ReactNode } from "react";

import type {
  CaseConfiguration,
  CaseRecommendation,
  CaseReference,
  ConfidenceLevel,
} from "../../api/cases";
import { VtlBadge } from "../../components/VtlBadge";
import { strings } from "../../i18n/strings";
import { formatPreciseTime } from "../../lib/datetime";
import styles from "./CaseReview.module.css";

const copy = strings.caseReview;

/** How much of a passage W-04 shows before "Show more" (P06 §6.2). */
const PASSAGE_PREVIEW_LENGTH = 300;

/** Filled blocks per level, for the prototype's "Medium ▮▮▯" meter. */
const CONFIDENCE_FILLED: Record<ConfidenceLevel, number> = { HIGH: 3, MEDIUM: 2, LOW: 1 };

export function RecommendationPanel({
  recommendation,
  references,
  configuration,
  children,
}: {
  recommendation: CaseRecommendation | null;
  references: readonly CaseReference[];
  configuration: CaseConfiguration | null;
  /** The action checklist, which is shown whether or not there is a recommendation. */
  children?: ReactNode;
}) {
  return (
    <section className={`${styles.panel} ${styles.panelRecommendation}`}>
      <h2 className={styles.panelTitle}>{copy.recommendationTitle}</h2>

      {recommendation === null ? (
        // W-06's reading of a missing recommendation: a case to triage by hand,
        // never an error (NFR-09).
        <p className={styles.muted}>{copy.recommendationUnavailable}</p>
      ) : (
        <>
          <div className={styles.categoryLine}>
            <VtlBadge category={recommendation.category} size="md" />
            <span className={styles.categoryLabel}>
              {copy.categoryHeading
                .replace("{label}", strings.vtl.labels[recommendation.category])
                .replace("{target}", strings.vtl.targets[recommendation.category])}
            </span>
          </div>

          {recommendation.safety_floor_applied && (
            <SafetyFloorNotice recommendation={recommendation} />
          )}

          <p className={styles.rationale}>
            <b>{copy.rationaleLabel}</b> {recommendation.rationale}
          </p>

          <Confidence
            level={recommendation.confidence}
            reasons={recommendation.low_confidence_reasons}
          />
        </>
      )}

      {children}

      {recommendation !== null && (
        <>
          <h3 className={styles.sectionTitle}>{copy.referencesTitle}</h3>
          {references.length === 0 ? (
            <p className={styles.actionsIntro}>{copy.referencesEmpty}</p>
          ) : (
            references.map((reference) => <Reference key={reference.rank} reference={reference} />)
          )}
        </>
      )}

      {configuration !== null && <Footnote configuration={configuration} />}
    </section>
  );
}

/**
 * "Safety floor applied: the red flag … requires at least Orange." (FR-23)
 *
 * Amber, not red: the floor working as designed is reassuring, not a failure.
 * A rule whose label has since been cleared still produces a notice — that the
 * floor was applied is the fact, and the label is the detail.
 */
function SafetyFloorNotice({ recommendation }: { recommendation: CaseRecommendation }) {
  const labels = recommendation.safety_floor_rules
    .map((rule) => rule.label)
    .filter((label): label is string => label !== null && label !== "");

  const category = strings.vtl.names[recommendation.category];
  const text =
    labels.length === 0
      ? copy.safetyFloorNoticeUnlabelled.replace("{category}", category)
      : copy.safetyFloorNotice
          .replace("{rules}", labels.map((label) => `“${label}”`).join(" and "))
          .replace("{category}", category);

  return (
    <p className={styles.warnBanner}>
      <span className={styles.warnIcon} aria-hidden="true">
        ✓
      </span>
      {text}
    </p>
  );
}

function Confidence({ level, reasons }: { level: ConfidenceLevel; reasons: readonly string[] }) {
  const filled = CONFIDENCE_FILLED[level];

  return (
    <div>
      <p className={styles.confidence}>
        <b>{copy.confidenceLabel}</b> {copy.confidence[level]}
        {/* Decoration: the level is already there in words (NFR-21). */}
        <span className={styles.confidenceMeter} aria-hidden="true">
          {"▮".repeat(filled)}
          {"▯".repeat(3 - filled)}
        </span>
      </p>

      {reasons.length > 0 && (
        <ul className={styles.reasons}>
          {reasons.map((reason) => (
            <li key={reason}>{reasonText(reason)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** A stored reason code as a sentence, never as the code itself (FR-24, IR-05). */
function reasonText(code: string): string {
  const sentences: Record<string, string> = copy.lowConfidenceReasons;
  return sentences[code] ?? copy.lowConfidenceFallback;
}

/**
 * One retrieved passage (FR-22, FR-25).
 *
 * The excerpt is capped so a long entry does not bury the next reference, and
 * "Show more" reveals the rest in place — the whole passage is what the reviewer
 * is checking the rationale against, so it must be reachable without leaving the
 * screen.
 */
function Reference({ reference }: { reference: CaseReference }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const isLong = reference.passage_text.length > PASSAGE_PREVIEW_LENGTH;
  const shown =
    isLong && !isExpanded
      ? `${reference.passage_text.slice(0, PASSAGE_PREVIEW_LENGTH).trimEnd()}…`
      : reference.passage_text;

  return (
    <div className={styles.reference}>
      <div className={styles.referenceHead}>
        <span className={styles.referenceTitle}>
          [{reference.rank}] {reference.entry_title}
        </span>
        {reference.source_title !== null && (
          <span className={styles.muted}>{reference.source_title}</span>
        )}
        {reference.is_cited && (
          <span className={styles.cited} title={copy.citedTitle}>
            {copy.citedMarker}
          </span>
        )}
      </div>

      <p className={styles.passage}>
        {shown}
        {isLong && (
          <>
            {" "}
            <button
              type="button"
              className={styles.inlineButton}
              aria-expanded={isExpanded}
              onClick={() => setIsExpanded(!isExpanded)}
            >
              {isExpanded ? copy.showLess : copy.showMore}
            </button>
          </>
        )}
      </p>

      {reference.source_url !== null && (
        <a
          className={styles.inlineButton}
          href={reference.source_url}
          target="_blank"
          rel="noreferrer"
        >
          {copy.openSource}
        </a>
      )}
    </div>
  );
}

/** "Model: … · Prompt v1.0 · KB version 7 · generated 09:36 in 9.2 s" (FR-26). */
function Footnote({ configuration }: { configuration: CaseConfiguration }) {
  const time = formatPreciseTime(configuration.generated_at) ?? copy.configurationKbUnknown;

  let text = copy.configurationFootnote
    .replace("{model}", configuration.model_id)
    .replace("{prompt}", configuration.prompt_version)
    .replace(
      "{kb}",
      configuration.kb_version_no === null
        ? copy.configurationKbUnknown
        : String(configuration.kb_version_no),
    )
    .replace("{time}", time);

  if (configuration.latency_ms !== null) {
    text += copy.configurationLatency.replace(
      "{latency}",
      (configuration.latency_ms / 1000).toFixed(1),
    );
  }

  return <p className={styles.footnote}>{text}</p>;
}
