/**
 * What the Status column of W-09 says about an account (FR-60, SR-03).
 *
 * Deactivated wins over locked: a deactivated account cannot sign in whatever
 * its lock says, and "Unlock" would offer an action that changes nothing. A lock
 * whose time has passed is no lock at all — the server clears it at the next
 * sign-in attempt, but the row still holds the old instant until then.
 */
import type { AdminUser } from "../../api/users";
import { strings } from "../../i18n/strings";
import { formatArrivalTime } from "../../lib/datetime";

export type UserStatusKind = "ACTIVE" | "LOCKED" | "DEACTIVATED";

export interface UserStatus {
  kind: UserStatusKind;
  label: string;
}

const copy = strings.users;

export function userStatus(user: AdminUser, now: Date = new Date()): UserStatus {
  if (!user.is_active) {
    return { kind: "DEACTIVATED", label: copy.statusDeactivated };
  }

  if (user.locked_until !== null && new Date(user.locked_until) > now) {
    const time = formatArrivalTime(user.locked_until) ?? user.locked_until;
    return { kind: "LOCKED", label: copy.statusLockedUntil.replace("{time}", time) };
  }

  return { kind: "ACTIVE", label: copy.statusActive };
}
