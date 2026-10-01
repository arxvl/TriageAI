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
    mainNavLabel: "Main",
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

  placeholder: {
    body: "Coming in a later phase.",
  },

  notFound: {
    title: "Page not found",
    body: "That page does not exist. Use the navigation above to continue.",
  },
} as const;
