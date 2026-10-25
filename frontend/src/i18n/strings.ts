/**
 * Every user-visible string in the interface (NFR-27).
 *
 * All text is English (FR-18, ADR-16). Keeping it here rather than inline means
 * a Filipino translation can be added later as a second file with the same type
 * and no code changes. Group keys by screen; `common` holds anything the shell
 * reuses.
 *
 * Nothing here may contain an error code, a stack trace, or a field name from
 * the API (IR-05).
 */
export const strings = {
  common: {
    systemName: "TriageAI",
    tagline: "Clinical decision support",
    taglineAdmin: "Administration",
    help: "Help",
    logOut: "Log out",
    skipToContent: "Skip to main content",
    loadingSession: "Checking your session…",
    dismiss: "Dismiss",
    mainNavLabel: "Main",
    // The reveal button on every password field. The name states what the next
    // click does, which is also how its state is announced (IR-07, NFR-21).
    showPassword: "Show password",
    hidePassword: "Hide password",
  },

  // The light/dark control in the header and on the sign-in card (NFR-21).
  theme: {
    label: "Theme",
    system: "System",
    light: "Light",
    dark: "Dark",
    // {theme} is replaced with the resolved name, so "System" says what it means
    // on this device right now.
    systemHint: "Follow the device setting (currently {theme})",
  },

  roles: {
    INTAKE_STAFF: "Intake Staff",
    VETERINARY_REVIEWER: "Veterinary Reviewer",
    ADMINISTRATOR: "Administrator",
  },

  nav: {
    queue: "Triage Queue",
    newCase: "New Case",
    caseHistory: "Case History",
    caseDetail: "Case",
    kbApprovals: "KB Approvals",
    users: "Users",
    knowledgeBase: "Knowledge Base",
    evaluation: "Evaluation",
    exports: "Exports",
  },

  login: {
    title: "TriageAI",
    subtitle: "Canine and Feline Symptom Triage and Clinical Decision Support",
    intro: "Sign in with your clinic account.",
    emailLabel: "Username or e-mail",
    passwordLabel: "Password",
    submit: "Log In",
    submitting: "Signing in…",
    forgotPassword: "Forgot password? Ask your administrator.",
    lockoutNotice: "After 5 failed attempts your account is locked for 15 minutes.",
    privacyNotice:
      "Privacy notice: personal data is processed under the Data Privacy Act of 2012 " +
      "(RA 10173) for triage and project evaluation only.",
    errors: {
      // Deliberately the same sentence for every cause, so the form cannot be
      // used to discover which accounts exist (SR-03, matches the API).
      invalidCredentials: "Incorrect username or password.",
      missingEmail: "Enter your username or e-mail address.",
      missingPassword: "Enter your password.",
      unexpected: "Sign-in is unavailable right now. Please try again in a moment.",
    },
    // {time} is replaced with the unlock time in the clinic's timezone.
    lockedUntil:
      "Too many failed sign-in attempts. This account is locked until {time} " +
      "and will unlock automatically.",
  },

  changePassword: {
    title: "Change your password",
    intro: "Your account uses a temporary password. Choose a new one to continue.",
    policyHint: "Use at least 12 characters, including at least one letter and one number.",
    currentLabel: "Current password",
    newLabel: "New password",
    confirmLabel: "Confirm new password",
    submit: "Change password",
    submitting: "Saving…",
    errors: {
      missingCurrent: "Enter your current password.",
      policy: "Use at least 12 characters, including at least one letter and one number.",
      mismatch: "The two new passwords do not match. Re-type them to continue.",
      unexpected: "The password could not be changed right now. Please try again.",
    },
  },

  // W-03 Case Intake (FR-01, FR-02, FR-04, FR-07, FR-18).
  caseIntake: {
    title: "New Triage Case",

    speciesLabel: "Species (required)",
    species: {
      DOG: "Dog",
      CAT: "Cat",
      OTHER: "Other species",
    },

    petNameLabel: "Pet name",
    optionalSuffix: "(optional)",
    ageLabel: "Age",
    // Visually hidden: the visible "Age" label belongs to the number input, and
    // the unit dropdown still needs a name of its own (NFR-21).
    ageUnitLabel: "Age unit",
    ageUnits: {
      YEARS: "years",
      MONTHS: "months",
    },
    // One control for two API fields, `sex` and `neutered`; the split happens in
    // `lib/caseValidation.ts`.
    sexLabel: "Sex and neuter status",
    sexOptions: {
      UNKNOWN: "Unknown",
      MALE_INTACT: "Male, intact",
      MALE_NEUTERED: "Male, neutered",
      FEMALE_INTACT: "Female, intact",
      FEMALE_SPAYED: "Female, spayed",
    },
    breedLabel: "Breed",
    weightLabel: "Body weight (kg)",

    intakeChannelLabel: "Intake channel",
    intakeChannels: {
      WALK_IN: "Walk-in",
      PHONE: "Phone",
      MESSAGE: "Message",
    },

    descriptionLabel: "Owner’s description of the problem (required, 20–2,000 characters)",
    // The FR-18 instruction. Staff translate at intake; the system has no
    // language detection and no translation component (ADR-16).
    descriptionHelper:
      "Enter the description in English. Translate any Filipino or Bikol words the owner " +
      "used, and keep their exact wording in quotation marks if you are unsure of the " +
      "meaning. Do not include the owner’s name or phone number here.",
    // {count} and {max} are replaced with the live length and the limit.
    descriptionCounter: "{count} / {max}",

    ownerReferenceTitle: "Owner reference (optional)",
    ownerReferenceCaption: "stored separately and never sent to AI services",
    ownerNameLabel: "Owner name",
    contactNumberLabel: "Contact number",

    submit: "Submit for triage",
    submitting: "Submitting…",
    cancel: "Cancel",
    latencyNote: "The recommendation usually appears within 10 seconds.",
    // {caseNo} is replaced with the case number the server assigned.
    submittedToast: "Case {caseNo} submitted",
    // Shown between the 202 and the move to the queue: the case is recorded and
    // the pipeline has it (FR-06). {caseNo} is the number just assigned.
    processingNotice: "Case {caseNo} recorded. Processing… the queue will show it shortly.",

    // The same sentences as the server's `core/validation_messages.py`, so the
    // form and the API cannot drift apart (IR-05). These keep the server's plain
    // apostrophe, character for character; the labels above use the typographic
    // one the wireframe draws.
    errors: {
      species: "Choose the species.",
      // FR-02, BR-06. Identical to the server's SPECIES_OUT_OF_SCOPE message.
      speciesOutOfScope: "Other species are not processed by the AI and must be triaged manually.",
      descriptionMissing: "Enter the owner's description of the problem.",
      descriptionTooShort:
        "The description must be at least 20 characters. " +
        "Add a little more detail about what the owner reported.",
      descriptionTooLong: "The description must be 2,000 characters or fewer. Shorten it a little.",
      petNameTooLong: "The pet name can be at most 60 characters.",
      ageNotANumber: "Enter the age as a number, e.g. 3.",
      ageOutOfRange: "Enter an age between 0 and 40.",
      breedTooLong: "The breed can be at most 60 characters.",
      weightNotANumber: "Enter the weight as a number, e.g. 4.2.",
      weightOutOfRange: "Enter a weight between 0.1 and 120 kg.",
      ownerNameTooLong: "The owner name can be at most 80 characters.",
      contactNumberTooLong: "The contact number can be at most 30 characters.",
      unexpected: "The case could not be submitted right now. Please try again.",
    },
  },

  // The VTL badge (IR-03). Every badge shows a category name *and* its target
  // waiting time as text, so meaning is never carried by colour alone. The
  // target wording is CLAUDE.md §6's Display column, character for character.
  vtl: {
    codes: {
      RED: "RED",
      ORANGE: "ORANGE",
      YELLOW: "YELLOW",
      GREEN: "GREEN",
      BLUE: "BLUE",
      MANUAL: "MANUAL",
    },
    targets: {
      RED: "Immediate",
      ORANGE: "≤ 15 min",
      YELLOW: "≤ 30–60 min",
      GREEN: "≤ 120 min",
      BLUE: "≤ 240 min",
    },
    // Title case, for a category named inside a sentence ("Adjusted (Yellow →
    // Green)"), where the badge's shouting capitals would not belong.
    names: {
      RED: "Red",
      ORANGE: "Orange",
      YELLOW: "Yellow",
      GREEN: "Green",
      BLUE: "Blue",
    },
    // The category's own name, for a heading that states the urgency in words
    // next to the badge: "ORANGE · Very urgent" (IR-03, W-04). RED's name and
    // its target wording coincide, which is why both exist as separate keys.
    labels: {
      RED: "Immediate",
      ORANGE: "Very urgent",
      YELLOW: "Urgent",
      GREEN: "Standard",
      BLUE: "Non-urgent",
    },
    manualCaption: "Needs manual triage",
    // A case still in the pipeline has no category and no target yet. Read out
    // in place of the em dash the column shows (NFR-21).
    noCategory: "No category yet",
  },

  // The status chip (FR-36, IR-04). An AI recommendation is never shown as
  // settled: until a reviewer decides, the chip says so in words.
  statusChip: {
    processing: "Processing",
    awaitingReview: "AI recommendation · pending",
    manualTriageRequired: "Manual triage required",
    confirmed: "Confirmed",
    // {from} and {to} are replaced with the two category names.
    adjusted: "Adjusted ({from} → {to})",
    manuallyTriaged: "Manually triaged",
    closed: "Closed",
  },

  // W-02 Triage Queue and W-11 tablet layout (FR-29, FR-30, FR-36, FR-39, IR-22).
  queue: {
    title: "Triage Queue",
    newCase: "+ New Case",

    // {seconds} is replaced with the age of the data in whole seconds.
    updatedAgo: "Updated {seconds} s ago · auto-refresh every 15 s",
    updatedJustNow: "Updated just now · auto-refresh every 15 s",

    redFlagBannerLabel: "Red-flag alerts",
    // {caseNo} and {summary} come from the alert.
    redFlagAlert: "Red-flag alert – {caseNo}: {summary}",
    // The {summary} the banner shows: the patient and the rule that fired, never
    // the text the rule matched (DR-04). {patient} is built from the species, the
    // pet's name and {rule}, the clinic's label for the rule.
    redFlagSummary: "{patient} – {rule}",
    redFlagOpenCase: "Open case",

    countersLabel: "Case counts by urgency",
    awaitingReviewCaption: "Awaiting review",
    // {category} is replaced with a category name; used as the tile's accessible
    // name, since the visible tile is a badge and a number.
    counterFilterHint: "Show only {category} cases",
    counterFilterClearHint: "Clear the {category} filter",

    searchLabel: "Search",
    searchPlaceholder: "Search case ID, pet name, or complaint…",
    speciesFilterLabel: "Species",
    categoryFilterLabel: "Category",
    statusFilterLabel: "Status",
    dateFilterLabel: "Date",
    filterAll: "All",
    // The queue never lists a closed case, so "open" is the widest status there
    // is here, not a filter that hides anything.
    statusAll: "Open",
    species: {
      DOG: "Dog",
      CAT: "Cat",
    },
    status: {
      SUBMITTED: "Submitted",
      PROCESSING: "Processing",
      AWAITING_REVIEW: "Awaiting review",
      MANUAL_TRIAGE_REQUIRED: "Manual triage required",
      CONFIRMED: "Confirmed",
      ADJUSTED: "Adjusted",
      MANUALLY_TRIAGED: "Manually triaged",
    },
    dateRanges: {
      ALL: "All open dates",
      TODAY: "Today",
      LAST_7_DAYS: "Last 7 days",
    },

    columns: {
      urgency: "Urgency",
      case: "Case",
      patient: "Patient",
      complaint: "Primary complaint",
      arrived: "Arrived",
      waiting: "Waiting / target",
      status: "Status",
      flags: "Flags",
    },

    // {waiting} and {target} are whole minutes.
    waiting: "{waiting} / {target} min",
    // A case with no category has no target to measure against.
    waitingNoTarget: "{waiting} min / —",
    overdueSuffix: "overdue",
    redFlag: "Red flag",
    // Shown where a value the pipeline has not produced yet would go.
    notAvailable: "—",
    // {species}, {name} and {age} are joined only when present.
    ageYears: "{value} y",
    ageMonths: "{value} mo",

    colorNote:
      "Colors are always shown with the category name and target waiting time. " +
      "Cases without a category are listed directly below Red.",

    loading: "Loading the queue…",
    empty: "No open cases. Submitted cases appear here within 15 seconds.",
    emptyFiltered: "No open cases match these filters.",
    clearFilters: "Clear filters",
    errors: {
      unexpected: "The queue could not be loaded right now. It will retry automatically.",
    },
  },

  // W-04 Case Review (FR-13, FR-31, FR-32, FR-36, FR-71..FR-79, IR-03, IR-04,
  // IR-06, IR-08, IR-23, BR-10 · UC-05).
  caseReview: {
    backToQueue: "← Back to queue",

    // IR-04, the sentence that must stay on screen until a reviewer decides.
    aiPendingChip: "AI Recommendation – requires staff confirmation",

    // {time} is the arrival time in the clinic's timezone, {channel} the intake
    // channel and {name} whoever recorded the case.
    arrivedBy: "Arrived {time} by {channel} · recorded by {name}",
    arrivedByUnknown: "Arrived {time} by {channel}",
    // {waiting} and {target} are whole minutes.
    waiting: "waiting {waiting} min of {target} min",
    waitingNoTarget: "waiting {waiting} min",
    overdueSuffix: "overdue",
    // {time} is the closing time.
    closedAt: "Closed {time}",

    // The W-04 banner. The rule's label only — never the words it matched
    // (DR-04). {rule} is the clinic's wording for the rule.
    redFlagDetected: "Red flag detected by the pre-screen: {rule}",
    redFlagDetectedUnlabelled: "Red flag detected by the pre-screen.",

    // Panel 1 (FR-13).
    descriptionTitle: "Owner’s description (verbatim)",
    highlightNote: "Highlights show the evidence used for each extracted value.",
    // Shown when the pipeline read a different string from the one on screen
    // (ADR-10): the offsets index into the de-identified text, so a highlight
    // drawn against the original would mark the wrong words.
    deidentifiedNote: "Highlights refer to the de-identified text, shown here.",
    // Spans the extraction claimed that no longer match the stored text.
    unmatchedEvidenceTitle: "Evidence no longer found in the text",
    // {field} is the extraction field, {text} the quoted evidence.
    unmatchedEvidence: "{field}: “{text}”",

    // Panel 2 (FR-09, FR-31). A reviewer can correct it and regenerate (P07 §7.2).
    extractionTitle: "Extracted information",
    extractionUnavailable: "Extracted information: not available for this case.",
    fields: {
      species: "Species",
      presenting_complaints: "Presenting complaints",
      onset_duration: "Onset / duration",
      frequency_severity: "Frequency / severity",
      associated_signs: "Associated signs",
      negated_findings: "Negated findings",
      exposure_history: "Exposure history",
      relevant_history: "Relevant history",
      red_flags: "Red flags",
      missing_information: "Ask the owner",
    },
    primaryMarker: "(primary)",
    emptyValue: "None stated",
    saveAndRegenerate: "Save and regenerate",
    saving: "Saving…",
    // W-04's hint beside the panel title, and beside the button until a value changes.
    editHint: "Click a value to correct it",
    enabledAfterCorrection: "enabled after a correction",
    // {field} is the field's label.
    editField: "Edit {field}",
    editDone: "Done",
    editListHelper: "One per line.",
    editComplaintsHelper: "Choose the complaints and mark one as primary.",
    editedMarker: "edited",
    // Names the complaint a primary radio belongs to; {complaint} is its name.
    primaryFor: "Primary complaint: {complaint}",
    complaintsLoading: "Loading the complaint list…",
    complaintsUnavailable: "The complaint list could not be loaded. Try again in a moment.",
    // The note under panel 2 once a reviewer has corrected it.
    correctedBy: "Version {version} – corrected by {name}.",
    correctedByUnknown: "Version {version} – corrected by a reviewer.",

    // Panel 3 (FR-20..FR-26).
    recommendationTitle: "Recommended urgency",
    recommendationUnavailable:
      "No AI recommendation for this case. It must be triaged manually using the VTL.",
    // {label} is the category name, {target} its target waiting time.
    categoryHeading: "{label} · see within {target}",
    // FR-23. {rules} is one or more rule labels, joined with "and".
    safetyFloorNotice: "Safety floor applied: the red flag {rules} requires at least {category}.",
    safetyFloorNoticeUnlabelled:
      "Safety floor applied: a red-flag rule requires at least {category}.",
    rationaleLabel: "Rationale.",
    confidenceLabel: "Confidence:",
    confidence: {
      HIGH: "High",
      MEDIUM: "Medium",
      LOW: "Low",
    },
    // FR-24. The codes are `backend/app/pipeline/safety.py`; the screen never
    // shows a code (IR-05).
    lowConfidenceReasons: {
      NO_VALID_CITATION:
        "No knowledge-base passage supports the recommendation, so it rests on the " +
        "model’s reading alone.",
      LOW_RETRIEVAL_SCORE:
        "The knowledge-base passages found were only loosely related to this case.",
      UNSUPPORTED_COMPLAINT_MANUAL_TRIAGE_RECOMMENDED:
        "The presenting complaint is outside the supported list. Triage this case by hand.",
    },
    lowConfidenceFallback: "The system flagged this recommendation as less reliable than usual.",

    referencesTitle: "References",
    referencesEmpty: "No knowledge-base passages were retrieved for this case.",
    citedMarker: "cited",
    citedTitle: "Quoted in the rationale",
    openSource: "Open source ↗",
    showMore: "Show more",
    showLess: "Show less",

    // FR-26, NFR-23. {model}, {prompt}, {kb}, {time} and {latency}.
    configurationFootnote: "Model: {model} · Prompt {prompt} · KB version {kb} · generated {time}",
    configurationLatency: " in {latency} s",
    configurationKbUnknown: "—",

    // The suggested-actions checklist (FR-71..FR-79, IR-23, ADR-18).
    actions: {
      title: "Suggested actions",
      // {category} is the category the actions are for.
      intro:
        "For {category}. Tick what applies, edit or remove any row, then finalise with your decision.",
      introReadOnly: "For {category}.",
      // FR-75, the label that stays until a reviewer finalizes the list.
      aiHeading: "AI-suggested actions – require staff approval",
      sources: {
        BASELINE: "Baseline",
        AI: "AI",
        REVIEWER: "Added by reviewer",
      },
      sourceTitles: {
        BASELINE: "From the knowledge base for this urgency category",
        AI: "Written by the model for this case, pending staff approval",
        REVIEWER: "Added by a reviewer",
      },
      pending: "Preparing case-specific suggestions…",
      // FR-77. One quiet line, never an error dialog: nothing about the case is
      // wrong, and the baseline actions are the ones that matter.
      failed: "Case-specific suggestions unavailable – baseline actions shown",
      // FR-78. Rows suggested for a category the case no longer has stay on
      // screen, greyed, and are never part of what a decision records.
      // {category} is the category they were suggested for.
      outdatedNote: "Suggested for {category} – review before keeping",
      outdatedTitle: "Suggested for a category this case no longer has",
      regenerate: "Regenerate suggestions",
      // {category} is the category the new suggestions are for.
      regenerateLabel: "Regenerate suggestions for {category}",
      regenerating: "Requesting…",
      // {count} is how many the deterministic validator dropped (FR-74).
      rejectedOne: "1 suggestion was withheld by the safety check.",
      rejectedMany: "{count} suggestions were withheld by the safety check.",
      // {ranks} is a list like "[1], [2]".
      citationLabel: "Supported by {ranks}",
      keepLabel: "Keep this action",
      edit: "Edit",
      editLabel: "Edit this action",
      editSave: "Save",
      editCancel: "Cancel",
      remove: "Remove",
      removeLabel: "Remove this action",
      restore: "Restore",
      restoreLabel: "Restore this action",
      addLabel: "Add an action",
      addPlaceholder: "Add an action for this case…",
      add: "+ Add action",
      // FR-73: a triage-level instruction, not a treatment (BR-09).
      addHelper:
        "Triage handling only: what to prepare, watch, or ask the owner. " +
        "Never a medication, dose, or treatment.",
      empty: "No suggested actions for this category.",
    },

    // The fixed decision bar (FR-32, FR-34, FR-37, IR-06, BR-10).
    decisionBar: {
      // {category} is the recommended category's name.
      confirm: "Confirm {category}",
      adjust: "Adjust category…",
      manual: "Mark for manual triage",
      addNote: "Add note",
      close: "Close case",
      viewAudit: "View audit",
      // IR-06, BR-10. On screen whenever a decision can be made.
      disclaimer:
        "Decision support only – this is not a diagnosis. The final urgency category " +
        "and actions are decided by veterinary staff.",
      // Shown in place of the buttons for a user without `can_decide` (BR-01).
      readOnly:
        "This case is read-only for your role. Only a Veterinary Reviewer can confirm, " +
        "adjust, or manually triage a case.",
      // A case that has already been decided. {decision} is the sentence below.
      decided: "Decision recorded.",
      // {category} is the final category, {name} the reviewer, {time} the time.
      decidedBy: "{category} · {name} · {time}",
      decidedByUnknown: "{category} · {time}",
    },

    // The confirmation dialog (IR-08).
    confirmDialog: {
      // {category} is the category being confirmed.
      title: "Confirm {category}?",
      body:
        "This records {category} as the final urgency category for this case, " +
        "together with the action list shown.",
      // {count} is the number of actions being finalized.
      actionsSummaryOne: "1 action will be recorded.",
      actionsSummaryMany: "{count} actions will be recorded.",
      actionsSummaryNone: "No actions will be recorded.",
      permanentNotice:
        "Your name, the time, and this decision are recorded in the audit trail " +
        "and cannot be edited later.",
      submit: "Confirm decision",
      submitting: "Saving…",
      cancel: "Cancel",
    },

    // W-05 Adjust dialog (FR-33, BR-03).
    adjustDialog: {
      title: "Adjust urgency category",
      // {category} is the recommended category's name.
      intro: "AI recommendation: {category}. Select the category you have decided on.",
      // The right-hand marker on the recommendation's own row.
      currentMarker: "current",
      upTriage: "Up-triage",
      downTriage: "Down-triage",
      categoryLegend: "Urgency category",

      reasonLabel: "Reason for change (required)",
      reasonPlaceholder: "Choose a reason…",
      detailsLabel: "Details",
      // Required only for the "Other" reason, which carries no meaning on its own.
      detailsLabelRequired: "Details (required)",

      // The live summary. {from} and {to} are category names, {direction} one of
      // the two words above, lowercased by the screen.
      summary: "Change: {from} → {to} ({direction}).",
      permanentNotice:
        "Your name, the time, and the reason are recorded in the audit trail " +
        "and cannot be edited later.",
      // The checklist on screen was prepared for the recommended category, so a
      // change of category means the action list is prepared again (FR-78).
      actionsNotice:
        "The action list for the new category is recorded with this decision. " +
        "The suggestions shown for the recommended category are not carried over.",

      submit: "Save decision",
      submitting: "Saving…",
      cancel: "Cancel",
    },

    // The fixed list behind an adjustment (FR-33). The codes are the API's; the
    // screen never shows one.
    adjustReasons: {
      CONDITION_DIFFERS_ON_ARRIVAL: "Patient’s condition on arrival differs from the description",
      SIGN_NOT_CAPTURED: "A sign was not captured in the description",
      RECOMMENDATION_TOO_LOW: "The recommendation was too low",
      RECOMMENDATION_TOO_HIGH: "The recommendation was too high",
      OTHER: "Other (describe below)",
    },

    // W-06 Manual triage (FR-34, NFR-09, ADR-15 §4).
    manualTriage: {
      // The banner for a case the pipeline gave up on.
      aiUnavailable: "AI unavailable – triage manually using the VTL.",
      safeToTriage: "The case is safe to triage; no data was lost.",
      // A reviewer who chose manual triage on a case that has a recommendation.
      // "AI unavailable" would be untrue, so this says what is actually happening.
      byChoice:
        "Manual triage. You are setting the category by hand; the AI recommendation " +
        "stays on the case for the record.",

      title: "Assign a category manually",
      categoryLegend: "Urgency category",
      noteLabel: "Note (required)",
      noteHelper: "Say what you based the category on. It is recorded with the decision.",
      // The baseline actions belong to the category being assigned, and the
      // server reads them when the decision is recorded (FR-72).
      actionsNotice:
        "The baseline actions for the category you assign are recorded with this " +
        "decision. Case-specific AI suggestions are not available for this case.",

      submit: "Save manual triage",
      submitting: "Saving…",
      cancel: "Cancel manual triage",
      statusNotice: "Status will change to “Manually triaged”.",
      retry: "Retry AI processing",
      retrying: "Retrying…",
    },

    // The note under the recommendation once it has been regenerated (FR-27). The
    // placeholders are filled in by the panel: {version} is this version, and
    // {kept} names the versions that remain viewable.
    regenerated: "Version {version} – regenerated after correction ({kept} kept in audit).",
    keptOne: "version {n}",
    keptMany: "versions 1–{n}",
    versions: {
      label: "Recommendation versions",
      // {version} is the number, {category} the VTL name.
      option: "Version {version} · {category}",
      current: "current",
      viewingOlder:
        "You are viewing version {version}, which is read-only. Decisions always apply " +
        "to the latest version.",
      madeFrom: "Made from extraction version {version}.",
      backToCurrent: "Back to the current version",
      loading: "Loading that version…",
    },
    // Why a regeneration did not produce a new version. The sentence itself comes
    // from the server (`backend/app/pipeline/messages.py`).
    regenerationFailedTitle: "The new recommendation could not be made.",

    // The banner while a run is in progress — after a case is entered, and after
    // Retry on W-06 (IR-22, P07 §7.1). The stages are the orchestrator's steps.
    processing: {
      title: "AI processing is running for this case. This screen updates by itself.",
      stages: {
        queued: "Waiting to start…",
        deidentify: "Removing identifying details…",
        screen: "Checking for red flags…",
        extract: "Reading the description…",
        retrieve: "Searching the knowledge base…",
        generate: "Preparing the recommendation…",
        done: "Finishing up…",
        failed: "Stopped. This screen is updating…",
      },
      // The same banner for a regeneration after a correction (P07 §7.2). It skips
      // reading the description, so only the stages it runs have their own wording.
      regeneratingTitle:
        "A new recommendation is being made from your correction. This screen updates by itself.",
      regeneratingStages: {
        queued: "Waiting to start…",
        retrieve: "Searching the knowledge base…",
        generate: "Preparing the recommendation…",
        done: "Finishing up…",
        failed: "Stopped. This screen is updating…",
      },
    },

    // The Add note dialog (FR-37).
    noteDialog: {
      title: "Add a clinical note",
      label: "Note",
      helper:
        "Notes are kept with the case and appear on its audit timeline. They cannot be edited later.",
      submit: "Save note",
      submitting: "Saving…",
      cancel: "Cancel",
    },

    // The Close case dialog (FR-38, IR-08).
    closeDialog: {
      // {caseNo} is the case number.
      title: "Close case {caseNo}?",
      body:
        "Closing records that the patient has been seen and removes the case from " +
        "the triage queue. The decision and the whole record are kept.",
      permanentNotice: "A closed case cannot be reopened or decided again.",
      submit: "Close case",
      submitting: "Closing…",
      cancel: "Cancel",
    },

    // {caseNo} and {category}; shown on the queue after the decision is saved.
    confirmedToast: "Case {caseNo} confirmed as {category}",
    // {caseNo}, {from} and {to} are category names.
    adjustedToast: "Case {caseNo} adjusted from {from} to {to}",
    // {caseNo} and {category}.
    manuallyTriagedToast: "Case {caseNo} triaged manually as {category}",
    // Shown in place, not on the queue: a note does not end the review.
    noteAddedToast: "Note added",
    // {caseNo}.
    closedToast: "Case {caseNo} closed",

    notes: {
      title: "Notes",
      // {name} and {time} head each note.
      byline: "{name} · {time}",
      bylineUnknown: "{time}",
    },

    loading: "Loading the case…",
    errors: {
      notFound: "That case could not be found. It may have been removed.",
      forbidden: "You do not have access to this case.",
      unexpected: "The case could not be loaded right now. Please try again.",
      // A 409 on the decision: the screen is out of date, so the answer is to
      // re-read the case rather than to re-send (FR-32, FR-48).
      conflict:
        "This case has already been decided by someone else. The screen has been " +
        "refreshed with the current decision.",
      decisionFailed: "The decision could not be saved right now. Please try again.",
      noteFailed: "The note could not be saved right now. Please try again.",
      closeFailed: "The case could not be closed right now. Please try again.",
      retryFailed: "AI processing could not be restarted right now. Please try again.",
      // A 409 on retry: someone else retried, or decided, first.
      correctionFailed: "The correction could not be saved right now. Please try again.",
      // A 409 on a correction: someone decided, or another correction started, first.
      correctionConflict:
        "This case can no longer be corrected: it has been decided, or a new " +
        "recommendation is already being made. The screen has been refreshed.",
      versionFailed: "That version could not be loaded right now. Please try again.",
      regenerateActionsFailed:
        "New suggestions could not be requested right now. Please try again.",
      // A 409 on regenerate: another request is already running, or the case moved on.
      regenerateActionsConflict:
        "Suggestions cannot be regenerated for this case right now. The screen has " +
        "been refreshed with the current state.",
      retryConflict:
        "This case is no longer waiting for a retry. The screen has been refreshed " +
        "with the current state.",
      // A 409 on close: the case was closed by someone else while this screen
      // was open, which is not a failure to report as one (FR-38).
      closeConflict:
        "This case has already been closed. The screen has been refreshed with " +
        "the current state.",
    },
  },

  // W-07's right panel: the audit timeline for one case (FR-42, FR-43, FR-45,
  // FR-46, ADR-12 · UC-10).
  caseAudit: {
    backToCase: "← Back to case",
    // {caseNo} is the case number, as W-07 writes it: "Audit timeline – C-0137".
    title: "Audit timeline – {caseNo}",
    // Shown while the case number is still being read, or if that read failed.
    titleFallback: "Audit timeline",

    // The two FR-46 intervals, in W-07's own wording.
    submissionToRecommendation: "Submission → recommendation",
    recommendationToDecision: "Recommendation → decision",
    // An interval the case has not reached yet. Shown rather than hidden, so a
    // missing figure reads as "not yet" and not as "zero".
    intervalNotAvailable: "—",
    intervalsLabel: "Timing for this case",

    eventsLabel: "Audit entries",
    // {name} is the actor's full name, {role} their role from `strings.roles`.
    actor: "{name} ({role})",
    // An entry the pipeline wrote: there is no person to name (ADR-12).
    actorSystem: "System",

    // FR-43 and ADR-12, word for word from W-07.
    appendOnly: "Entries are append-only and cannot be edited or deleted.",

    loading: "Loading the audit timeline…",
    // A case always has at least a "case created" entry, so this is a guard
    // rather than an expected state.
    empty: "No audit entries for this case.",
    errors: {
      notFound: "That case could not be found. It may have been removed.",
      forbidden: "You do not have access to this case.",
      unexpected: "The audit timeline could not be loaded right now. Please try again.",
    },
  },

  // W-07 Case History (FR-44, FR-45, FR-46 · UC-11). Open to all three roles; it
  // only reads, so nothing here assumes the viewer may decide a case.
  caseHistory: {
    title: "Case History",
    filtersLabel: "Search cases",

    caseNoLabel: "Case ID",
    caseNoPlaceholder: "e.g. C-0137",
    dateFromLabel: "From",
    dateToLabel: "To",
    speciesLabel: "Species",
    complaintLabel: "Complaint",
    aiCategoryLabel: "AI category",
    finalCategoryLabel: "Final category",
    statusLabel: "Status",
    filterAll: "All",
    disagreementLabel: "AI ≠ final",
    search: "Search",
    clear: "Clear",

    species: {
      DOG: "Dog",
      CAT: "Cat",
    },
    status: {
      SUBMITTED: "Submitted",
      PROCESSING: "Processing",
      AWAITING_REVIEW: "Awaiting review",
      MANUAL_TRIAGE_REQUIRED: "Manual triage required",
      CONFIRMED: "Confirmed",
      ADJUSTED: "Adjusted",
      MANUALLY_TRIAGED: "Manually triaged",
      CLOSED: "Closed",
    },

    resultsLabel: "Matching cases",
    columns: {
      case: "Case",
      date: "Date",
      patient: "Patient",
      ai: "AI",
      final: "Final",
      status: "Status",
    },
    // The AI category is a recommendation, never a settled one (IR-04), so the
    // column header says what it is wherever there is room for it.
    aiColumnHint: "AI recommendation",
    finalColumnHint: "Reviewer's decision",
    // {date} and {time} are the case's arrival in the clinic's timezone.
    arrived: "{date} {time}",
    patient: "{species} · {name}",
    // Read out in place of the dash when a category has not been set.
    noAiCategory: "No AI category",
    notDecided: "Not decided yet",
    disagreementMarker: "AI ≠ final",
    // {caseNo} names the row for a screen reader; the row is otherwise a button.
    selectRow: "Show the audit timeline for {caseNo}",
    openCase: "Open case",

    caption: "AI and final categories are shown side by side so disagreements are easy to review.",
    colorNote: "Colors are always shown with the category name and target waiting time.",

    // {from}–{to} is the rows on this page, {total} the matches.
    range: "{from}–{to} of {total}",
    // {page} and {pages} are 1-based.
    pageOf: "Page {page} of {pages}",
    previous: "Previous",
    next: "Next",
    paginationLabel: "Pages of results",

    loading: "Loading cases…",
    empty: "No cases have been recorded yet.",
    emptyFiltered: "No cases match these filters.",
    selectPrompt: "Select a case to see its audit timeline.",
    errors: {
      unexpected: "Case history could not be loaded right now. Please try again.",
      badRange: "The end date cannot be before the start date.",
    },
  },

  // W-08 Knowledge Base (FR-49..FR-56, NFR-08, BR-04, ADR-14, ADR-18 · UC-13,
  // UC-14). One screen for two jobs: an administrator curates entries, and a
  // Veterinary Reviewer holding `can_approve_kb` approves them (BR-04). Both
  // read the same catalogue, so the wording never assumes which one is looking.
  knowledgeBase: {
    title: "Knowledge Base",

    // The W-08 header line. {version} is the published version number and
    // {count} the number of ACTIVE entries in it.
    publishedVersion: "Published version: v{version} · {count} active entries",
    // Before the first approval there is no version to name, and saying so is
    // more honest than "v0" (FR-54).
    publishedVersionNone: "No published version yet · {count} active entries",

    viewsLabel: "Knowledge base section",
    viewEntries: "Entries",
    viewRules: "Red-flag rules",

    tabsLabel: "Entry status",
    // {label} is one of `tabs`, {count} the server's count for that status. The
    // counts describe the whole knowledge base, so a filter never moves them.
    tabLabel: "{label} ({count})",
    tabs: {
      DRAFT: "Draft",
      PENDING_REVIEW: "Pending review",
      ACTIVE: "Active",
      RETIRED: "Retired",
    },

    kindFilterLabel: "Entry kind",
    kindAll: "All kinds",
    // The two kinds of entry (ADR-18). A baseline action set is not clinical
    // prose and is never retrieved by similarity, so the list marks it.
    kinds: {
      COMPLAINT: "Clinical entry",
      URGENCY_ACTIONS: "Urgency actions",
    },

    columns: {
      entry: "Entry",
      filedUnder: "Filed under",
      species: "Species",
      source: "Source",
      words: "Words",
    },
    // {count} is the entry's word count, or its number of baseline actions.
    wordCount: "{count} words",
    actionCount: "{count} actions",

    species: {
      DOG: "Dog",
      CAT: "Cat",
    },
    notAvailable: "—",

    loading: "Loading the knowledge base…",
    empty: "No entries in the knowledge base yet.",
    emptyFiltered: "No entries match this tab and filter.",
    selectPrompt: "Select an entry to read it.",

    // The detail panel.
    detail: {
      contentHeading: "Content",
      citationHeading: "Source citation",
      redFlagsHeading: "Red flags and minimum category",
      noRedFlags: "No red-flag rules cite this entry.",
      // {category} is the VTL code; the badge beside it carries the target time.
      minimumSuffix: "minimum",
      publisherLabel: "Publisher",
      urlLabel: "URL",
      accessDateLabel: "Accessed",
      createdByLabel: "Written by",
      approvedByLabel: "Approved by",
      slugLabel: "Imported from",
      // A draft written to replace an entry that is live (ADR-14).
      revisesNote: "This draft replaces an entry that is currently active.",
      rejectionHeading: "Returned for revision",
      citationIncomplete: "The citation is incomplete. An entry cannot be submitted without it.",
    },

    // Indexing after an approval (FR-53). The entry is not active until it
    // succeeds, so these states are about the job, not the entry.
    indexing: {
      heading: "Indexing",
      QUEUED: "Indexing queued…",
      RUNNING: "Indexing…",
      DONE: "Indexed",
      FAILED: "Indexing failed",
      // {reason} is the job's reason code. Never a model response (CLAUDE.md §9).
      reason: "Reason: {reason}",
      stillPending:
        "The entry is still awaiting review and no version was published. " +
        "Approve it again once the problem is fixed.",
    },

    editor: {
      headingNew: "New entry",
      headingEdit: "Edit draft",
      newEntry: "+ New entry",
      newActionSet: "+ New urgency-action set",
      kindLabel: "Entry kind",
      titleLabel: "Title",
      complaintLabel: "Presenting complaint",
      complaintPlaceholder: "Choose a complaint",
      urgencyCategoryLabel: "Urgency category",
      urgencyCategoryPlaceholder: "Choose a category",
      speciesLabel: "Species",
      contentLabel: "Content",
      // FR-49, word for word from W-08: the entry is written, not copied.
      contentHelper: "Write in your own words from the cited source; do not copy text",
      // {count} is the live count, {min} and {max} the bounds the server applies.
      contentCounter: "{count} words (needs {min}–{max})",
      actionsCounter: "{count} actions, one per line (needs {min}–{max})",
      actionsHelper:
        "One action per line: escalate, prepare, monitor, what to ask the owner, " +
        "transport precautions. No medication, dose or diagnosis.",
      redFlagsLabel: "Red-flag rules explained by this entry",
      redFlagsHint: "A rule belongs to one entry; choosing it here moves it to this entry.",
      redFlagsEmpty: "No red-flag rules exist yet.",
      citationLegend: "Source citation (all fields required)",
      sourceTitleLabel: "Source title",
      sourcePublisherLabel: "Publisher",
      sourceUrlLabel: "Source URL",
      accessDateLabel: "Access date",
      saveDraft: "Save draft",
      submitForReview: "Submit for review",
      cancel: "Cancel",
      edit: "Edit draft",
      // Shown instead of the editor for an entry that is not a draft (ADR-14).
      notEditable: "Only a draft can be edited. Active content is replaced by a new draft.",
    },

    // The approver's controls (FR-52, BR-04).
    approve: "Approve and publish (v{version})",
    reject: "Reject with comments",
    retire: "Retire entry",
    approverOnlyNote: "Visible only to licensed veterinarians with approval permission.",

    rejectDialog: {
      title: "Reject with comments",
      commentsLabel: "What needs to change",
      commentsHint: "The author sees these comments on the draft. Comments are required.",
      submit: "Send back to the author",
      cancel: "Cancel",
    },

    retireDialog: {
      title: "Retire this entry?",
      body:
        "Retiring removes the entry from retrieval and publishes a new knowledge-base " +
        "version. The entry itself is kept, so past recommendations stay explainable.",
      confirm: "Retire and publish",
      cancel: "Cancel",
    },

    toasts: {
      draftSaved: "Draft saved.",
      submitted: "Submitted for review.",
      // Approval enqueues indexing; the entry goes live when that finishes.
      approved: "Approved. Indexing has started.",
      rejected: "Sent back to the author.",
      // {version} is the version the action published.
      retired: "Entry retired. Knowledge-base version v{version} published.",
      ruleApproved: "Rule approved. Knowledge-base version v{version} published.",
      ruleRetired: "Rule retired. Knowledge-base version v{version} published.",
    },

    // The red-flag rules tab (FR-12, FR-23, NFR-08). Retiring a rule lowers the
    // safety floor, so both actions here are the approver's.
    rules: {
      heading: "Red-flag rules",
      note:
        "A rule sets the minimum urgency category for a case its phrases match. " +
        "Changes take effect only after veterinary approval.",
      columns: {
        rule: "Rule",
        minCategory: "Minimum category",
        species: "Species",
        status: "Status",
        approval: "Approval",
        actions: "",
      },
      placeholderBadge: "Placeholder",
      placeholderHint: "Seeded for development; screens cases only outside production.",
      screening: "Screening cases",
      notScreening: "Not screening",
      retiredStatus: "Retired",
      // {name} is the approver's full name.
      approvedBy: "Approved by {name}",
      notApproved: "Not approved",
      approve: "Approve",
      retire: "Retire",
      empty: "No red-flag rules yet.",
      loading: "Loading the red-flag rules…",
    },

    versions: {
      open: "Version history",
      close: "Close",
      heading: "Published versions",
      label: "v{version}",
      // {count} is how many entries that version contains.
      entryCount: "{count} entries",
      publishedBy: "Published by {name}",
      publishedBySystem: "Published by the system",
      empty: "No versions have been published yet.",
      loading: "Loading the version history…",
    },

    errors: {
      // The editor's field-level messages (IR-05). They mirror the sentences
      // `app/schemas/kb.py` and `app/core/validation_messages.py` return.
      titleMissing: "Enter a title for this entry.",
      titleTooLong: "The title is too long.",
      complaintMissing: "Choose the presenting complaint this entry is filed under.",
      urgencyCategoryMissing: "Choose the urgency category these actions are for.",
      speciesMissing: "Choose at least one species.",
      contentMissing: "Write the content of this entry.",
      // {min}, {max} and {count} are word counts.
      contentWordCount:
        "The content must be between {min} and {max} words; this entry has {count}.",
      // {min}, {max} and {count} are numbers of actions.
      actionLineCount:
        "A baseline action set holds between {min} and {max} actions, one per line; " +
        "this entry has {count}.",
      sourceTitleMissing: "Enter the title of the source.",
      sourceTitleTooLong: "The source title is too long.",
      sourcePublisherMissing: "Enter the publisher of the source.",
      sourcePublisherTooLong: "The publisher is too long.",
      sourceUrlMissing: "Enter the URL of the source.",
      sourceUrlTooLong: "The URL is too long.",
      accessDateMissing: "Enter the date the source was accessed.",
      rejectCommentsMissing: "Write what needs to change before sending the draft back.",

      // Request failures.
      unexpected: "The knowledge base could not be loaded right now. Please try again.",
      saveFailed: "That entry could not be saved. Please try again.",
      actionFailed: "That action could not be completed. Please try again.",
      conflict: "The entry has changed since this screen loaded. Reload and try again.",
      notFound: "That entry could not be found. It may have been removed.",
      forbidden: "You do not have permission to do that.",
    },
  },

  // W-09 User Management (FR-60, FR-63, SR-03, BR-04, BR-05).
  users: {
    title: "User Management",
    searchLabel: "Search users",
    searchPlaceholder: "Name or e-mail",
    searchButton: "Search",
    clearSearch: "Clear",
    loading: "Loading users…",
    empty: "No users match that search.",
    columns: {
      name: "Name",
      email: "E-mail",
      role: "Role",
      kbApproval: "KB approval",
      status: "Status",
      lastLogin: "Last login",
      actions: "Actions",
    },
    kbApprovalYes: "Yes",
    kbApprovalNo: "—",
    statusActive: "Active",
    statusDeactivated: "Deactivated",
    // {time} is the unlock time in the clinic's timezone, HH:MM.
    statusLockedUntil: "Locked until {time}",
    neverSignedIn: "Never",
    edit: "Edit",
    unlock: "Unlock",
    reactivate: "Reactivate",

    add: {
      title: "Add user",
      fullName: "Full name",
      email: "E-mail",
      role: "Role",
      kbApproval: "Grant knowledge base approval permission",
      kbApprovalHelp: "Only for licensed veterinarians with the Veterinary Reviewer role (BR-04).",
      temporaryPasswordNote:
        "A temporary password is generated and must be changed at first login.",
      submit: "Create account",
      submitting: "Creating…",
      fullNameMissing: "Enter the person's full name.",
      emailInvalid: "Enter a valid e-mail address, e.g. name@clinic.example.",
    },

    editDialog: {
      title: "Edit user",
      fullName: "Full name",
      email: "E-mail",
      emailFixed: "The e-mail address cannot be changed.",
      role: "Role",
      kbApproval: "Grant knowledge base approval permission",
      kbApprovalHelp: "Only for licensed veterinarians with the Veterinary Reviewer role (BR-04).",
      active: "Account is active",
      activeHelp: "A deactivated account cannot sign in.",
      resetPassword: "Reset password",
      resetPasswordHelp:
        "Issues a new temporary password. Their current password stops working at once.",
      resetPasswordConfirm: "Confirm reset",
      save: "Save changes",
      saving: "Saving…",
      cancel: "Cancel",
      fullNameMissing: "Enter the person's full name.",
    },

    temporaryPassword: {
      title: "Temporary password",
      // {name} is the account the password belongs to.
      intro: "Give this temporary password to {name}. They must change it when they first sign in.",
      label: "Temporary password",
      warning: "This password is shown only once.",
      copy: "Copy",
      copied: "Password copied.",
      copyFailed: "The password could not be copied. Select it and copy it by hand.",
      done: "Done",
    },

    toasts: {
      created: "Account created.",
      updated: "Changes saved.",
      unlocked: "Account unlocked.",
      reactivated: "Account reactivated.",
    },

    errors: {
      unexpected: "The users could not be loaded right now. Please try again.",
      actionFailed: "That change could not be saved. Please try again.",
      lastAdministrator:
        "This is the only active administrator. Add or reactivate another administrator first.",
      emailInUse: "Another account already uses that e-mail address.",
      notFound: "That account could not be found. It may have been removed.",
      forbidden: "You do not have permission to do that.",
    },
  },

  // W-10 Evaluation Console (FR-64..FR-69, NFR-01, NFR-14, NFR-16, NFR-17, BR-05).
  evaluation: {
    title: "Evaluation Console",
    loading: "Loading…",

    // ADR-17: a number from the mock stages must never pass for a model result.
    mockBanner: "MOCK MODE – results are not model results",

    setLabel: "Vignette set",
    // {name} is the set's name, {count} how many vignettes it holds.
    setOption: "{name} – {count} vignettes",
    noSets: "No vignette sets yet. Upload a CSV file to begin.",
    upload: "Upload vignettes (CSV)",
    start: "Start evaluation run",
    starting: "Starting…",
    startBlockedRunning: "A run is still in progress.",

    // {model}, {prompt}, {kb}, {temperature} and {topK} come from the run's own
    // configuration snapshot (NFR-23); {kb} is the first characters of its id.
    configLine:
      "Model: {model} · Prompt {prompt} · KB {kb} · temperature {temperature} · top-k {topK}",
    configPending: "Start a run to record the configuration.",
    configUnknown: "—",
    temperatureDefault: "provider default",

    runs: {
      title: "Runs",
      empty: "No evaluation runs yet.",
      // {number} counts runs from the oldest.
      name: "Run #{number}",
      select: "Show run #{number}",
      columns: {
        run: "Run",
        set: "Set",
        status: "Status",
        progress: "Vignettes",
        started: "Created",
      },
      // {number}, {status}, {done} and {total}; W-10's "Run #3 · completed · 80 of 80".
      heading: "Run #{number} · {status} · {done} of {total} vignettes",
      status: {
        QUEUED: "queued",
        RUNNING: "running",
        DONE: "completed",
        FAILED: "failed",
      },
      progressLabel: "Evaluation progress",
      progress: "{done} of {total} vignettes",
      failedRun: "This run did not finish, so it has no metrics.",
      noMetrics: "Metrics appear when the run completes.",
      // {count} vignettes failed in the pipeline and are left out of every metric.
      failedVignettes: "{count} vignette(s) failed and are excluded from the metrics.",
    },

    metrics: {
      title: "Metrics against the SRS targets",
      // The measure's name as the API reports it is shown; these are the words
      // around a value.
      target: "target {comparison} {threshold}",
      atLeast: "≥",
      atMost: "≤",
      latencyTitle: "Latency p50 / p95",
      // A target reads as data, not as a verdict: a miss is a valid result (NFR-16).
      pass: "✓ target met",
      fail: "✗ target not met",
      notAvailable: "n/a – not computed",
      valueUnavailable: "n/a",
    },

    matrix: {
      title: "Confusion matrix (rows: reference, columns: predicted)",
      reference: "Reference",
      predicted: "Predicted",
      note: "Cells to the right of the diagonal are under-triaged.",
    },

    underTriaged: {
      title: "Under-triaged vignettes – forward to the veterinary reviewer (NFR-14)",
      columns: {
        vignette: "Vignette",
        reference: "Reference",
        predicted: "Predicted",
        complaint: "Primary complaint",
      },
      none: "No under-triaged vignettes in this run.",
      noComplaint: "—",
      // {count} rows are folded away until asked for.
      more: "+ {count} more",
      showAll: "Show all",
      showFewer: "Show fewer",
    },

    export: {
      csv: "Export CSV",
      json: "Export JSON",
      exporting: "Exporting…",
      unavailable: "The export is available once the run has finished.",
      // {id} is the first characters of the run id; {format} is csv or json.
      fileName: "evaluation-run-{id}.{format}",
      failed: "The export could not be downloaded. Please try again.",
    },

    uploadDialog: {
      title: "Upload vignettes",
      nameLabel: "Set name",
      fileLabel: "Vignette file (CSV)",
      fileHelp:
        "Columns: external_id, species, description, reference_category, relevant_entry_slugs.",
      nameMissing: "Enter a name for the set.",
      fileMissing: "Choose a CSV file.",
      submit: "Upload",
      submitting: "Uploading…",
      cancel: "Cancel",
      close: "Close",
      nameInUse: "Another vignette set already has that name.",
      rowsHeading: "Fix these rows and upload the file again:",
      // {row} is the line in the file, counting the header as line 1.
      row: "Row {row}: {message}",
      rowField: "Row {row} ({field}): {message}",
      // A problem with the whole file or the name carries row 0.
      file: "{message}",
      // {count} vignettes were stored.
      imported: "{count} vignettes imported.",
      warningsHeading: "The set was imported, but some knowledge-base entries were not found:",
      toast: "Vignette set imported.",
    },

    toasts: {
      started: "Evaluation run started.",
    },

    errors: {
      unexpected: "The evaluation data could not be loaded right now. Please try again.",
      startFailed: "The run could not be started. Please try again.",
      uploadFailed: "The file could not be uploaded. Please try again.",
      notFound: "That item could not be found. It may have been removed.",
      forbidden: "You do not have permission to do that.",
    },
  },

  placeholder: {
    body: "Coming in a later phase.",
  },

  notFound: {
    title: "Page not found",
    body: "That page does not exist. Use the navigation above to continue.",
  },
} as const;
