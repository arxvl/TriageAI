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

  placeholder: {
    body: "Coming in a later phase.",
  },

  notFound: {
    title: "Page not found",
    body: "That page does not exist. Use the navigation above to continue.",
  },
} as const;
