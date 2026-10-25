/** The three roles in the order W-09's Role control lists them (FR-58). */
import type { UserRole } from "../../api/auth";
import { strings } from "../../i18n/strings";

export const ROLE_OPTIONS: readonly { value: UserRole; label: string }[] = [
  { value: "INTAKE_STAFF", label: strings.roles.INTAKE_STAFF },
  { value: "VETERINARY_REVIEWER", label: strings.roles.VETERINARY_REVIEWER },
  { value: "ADMINISTRATOR", label: strings.roles.ADMINISTRATOR },
];
