/**
 * The Veterinary Triage List, as the reviewer reads it on W-06.
 *
 * This is **content, not logic**. Nothing here assigns a category: a reviewer
 * triaging by hand does that, and the examples below are the memory aid W-06
 * prints beside each option so they are not working from the colour alone
 * (IR-03, NFR-21). No code branches on these strings.
 *
 * The five lists are the discriminators drawn in the W-06 wireframe, word for
 * word. They are examples, not a decision rule and not an exhaustive list, which
 * is what `caption` says on screen — a reviewer who matches a sign to the wrong
 * line because it was the closest one printed is the failure this file could
 * cause.
 *
 * Provisional, like `redFlagSigns.ts`: a veterinary reviewer approves the final
 * wording in P08 alongside the knowledge-base entries, and both change together.
 *
 * English only (FR-18, ADR-16). It lives here rather than in `i18n/strings.ts`
 * because the phase prompt names this path (P06 §6.3), and because this is
 * clinical content a reviewer signs off on rather than interface wording.
 */
import type { VTLCategory } from "../api/cases";

/** The W-06 examples for each category, in urgency order. */
export const VTL_DISCRIMINATORS: Record<VTLCategory, string> = {
  RED: "not breathing, unresponsive, ongoing seizure, uncontrolled bleeding",
  ORANGE: "breathing difficulty, severe pain, suspected toxin, male cat unable to urinate",
  YELLOW: "repeated vomiting with lethargy, controlled bleeding",
  GREEN: "lameness while bearing weight, single vomiting episode",
  BLUE: "chronic itching, mild eye or ear discharge",
};

export const vtlReference = {
  /** Prefixes each list, so no line reads as a rule. */
  examplePrefix: "e.g.",

  caption:
    "Examples only, to help you place the case. They are not a complete list and do " +
    "not decide the category — your clinical judgement does. Final wording to be " +
    "validated by the veterinary reviewer.",
} as const;
