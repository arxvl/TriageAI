/**
 * The guidance panel beside the W-03 intake form.
 *
 * This is **content, not logic**. Nothing here screens a description: red-flag
 * detection is the keyword screener on the server, written by hand against
 * veterinarian-approved rules (CLAUDE.md §8, ADR-09). These sentences only tell
 * the person at the counter when to fetch a reviewer instead of waiting for a
 * recommendation.
 *
 * The list is provisional. It mirrors the seven placeholder rules the P03 seed
 * script inserts into `red_flag_rules` (`is_placeholder=true`, no approver), and
 * the caption says so on screen. A veterinary reviewer approves the final list in
 * P08, at which point both this file and those rows change together.
 *
 * English only (FR-18, ADR-16). It lives here rather than in `i18n/strings.ts`
 * because the phase prompt names this path, and because the list is clinical
 * content a reviewer signs off on rather than interface wording.
 */

export const redFlagPanel = {
  heading: "Red-flag signs – notify a Veterinary Reviewer immediately",

  signs: [
    "Not breathing or struggling to breathe",
    "Collapsed or unresponsive",
    "Seizure happening now",
    "Bleeding that will not stop",
    "Male cat straining with no urine",
    "Possible poison or medication swallowed",
    "Pale, white, or bluish gums",
  ],

  caption: "Final list to be validated by the veterinary reviewer",

  tipsHeading: "Tips for a useful description",
  tips:
    "Ask when it started, how often it happens, whether it is getting worse, and whether " +
    "the pet is eating and drinking.",
} as const;
