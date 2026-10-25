/**
 * The metric cards of W-10, one per SRS target (NFR-01, NFR-16, NFR-17).
 *
 * Rendered from the run's `targets`, so no threshold is written here. Each card
 * says its target and its result in words ("✓ target met"), never in colour
 * alone (IR-03). A missed target is a valid result (NFR-16), so it reads as
 * data: the same weight as a met one, not an alarm.
 *
 * The two latency targets share one card, "8.4 / 16.9 s", and that card's mark
 * is only "met" when both percentiles are.
 */
import type { EvalTarget, EvalTargetStatus } from "../../api/eval";
import { strings } from "../../i18n/strings";
import styles from "./Evaluation.module.css";
import {
  LATENCY_KEYS,
  formatValue,
  latencyTargetText,
  latencyValueText,
  targetText,
} from "./runFormat";

const copy = strings.evaluation.metrics;

const MARK: Record<EvalTargetStatus, string> = {
  PASS: copy.pass,
  FAIL: copy.fail,
  "n/a": copy.notAvailable,
};

/** Met only if both are; unknown if either could not be computed. */
function combinedStatus(a: EvalTargetStatus, b: EvalTargetStatus): EvalTargetStatus {
  if (a === "n/a" || b === "n/a") {
    return "n/a";
  }
  return a === "PASS" && b === "PASS" ? "PASS" : "FAIL";
}

interface CardModel {
  key: string;
  label: string;
  value: string;
  target: string;
  status: EvalTargetStatus;
}

function cardsFor(targets: readonly EvalTarget[]): CardModel[] {
  const p50 = targets.find((target) => target.key === LATENCY_KEYS.p50);
  const p95 = targets.find((target) => target.key === LATENCY_KEYS.p95);

  const cards: CardModel[] = targets
    .filter((target) => target.key !== LATENCY_KEYS.p50 && target.key !== LATENCY_KEYS.p95)
    .map((target) => ({
      key: target.key,
      label: target.label,
      value: formatValue(target),
      target: targetText(target),
      status: target.status,
    }));

  if (p50 !== undefined && p95 !== undefined) {
    cards.push({
      key: "latency",
      label: copy.latencyTitle,
      value: latencyValueText(p50, p95),
      target: latencyTargetText(p50, p95),
      status: combinedStatus(p50.status, p95.status),
    });
  }
  return cards;
}

export function MetricCards({ targets }: { targets: readonly EvalTarget[] }) {
  return (
    <ul className={styles.cards} aria-label={copy.title}>
      {cardsFor(targets).map((card) => (
        <li key={card.key} className={styles.card} data-status={card.status}>
          <span className={styles.cardLabel}>{card.label}</span>
          <strong className={styles.cardValue}>{card.value}</strong>
          <span className={styles.cardTarget}>{card.target}</span>
          <span className={styles.cardMark}>{MARK[card.status]}</span>
        </li>
      ))}
    </ul>
  );
}
