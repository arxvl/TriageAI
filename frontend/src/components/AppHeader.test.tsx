import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeUserWithRole, renderWithAuth } from "../test/testUtils";
import { AppHeader } from "./AppHeader";

/** Every nav label the shell can show, so a test can assert on absence too. */
const ALL_LINKS = [
  "Triage Queue",
  "New Case",
  "Case History",
  "KB Approvals",
  "Users",
  "Knowledge Base",
  "Evaluation",
  "Exports",
];

function visibleNavLabels(): string[] {
  const nav = screen.getByRole("navigation", { name: "Main" });
  return ALL_LINKS.filter((label) =>
    Array.from(nav.querySelectorAll("a")).some((link) => link.textContent === label),
  );
}

describe("AppHeader navigation per role (IR-02, FR-59)", () => {
  it("shows intake staff the three case links and nothing else", () => {
    renderWithAuth(<AppHeader user={makeUserWithRole("INTAKE_STAFF")} />);

    expect(visibleNavLabels()).toEqual(["Triage Queue", "New Case", "Case History"]);
  });

  it("does not show KB Approvals to a reviewer without the permission (BR-04)", () => {
    renderWithAuth(
      <AppHeader user={makeUserWithRole("VETERINARY_REVIEWER", { can_approve_kb: false })} />,
    );

    expect(visibleNavLabels()).toEqual(["Triage Queue", "New Case", "Case History"]);
  });

  it("shows KB Approvals to a reviewer who holds the permission", () => {
    renderWithAuth(
      <AppHeader user={makeUserWithRole("VETERINARY_REVIEWER", { can_approve_kb: true })} />,
    );

    expect(visibleNavLabels()).toEqual([
      "Triage Queue",
      "New Case",
      "Case History",
      "KB Approvals",
    ]);
  });

  it("shows an administrator only the administration links", () => {
    renderWithAuth(<AppHeader user={makeUserWithRole("ADMINISTRATOR")} />);

    expect(visibleNavLabels()).toEqual(["Users", "Knowledge Base", "Evaluation", "Exports"]);
  });

  it("hides navigation while a temporary password is still in force (FR-61)", () => {
    renderWithAuth(
      <AppHeader user={makeUserWithRole("INTAKE_STAFF", { must_change_password: true })} />,
    );

    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    // The account controls stay, so the user can still sign out.
    expect(screen.getByRole("button", { name: "Log out" })).toBeInTheDocument();
  });
});

describe("AppHeader account area (IR-02)", () => {
  it("shows the system name, user name, role, Help and Log out", () => {
    renderWithAuth(
      <AppHeader user={makeUserWithRole("VETERINARY_REVIEWER", { full_name: "Dr. M. Santos" })} />,
    );

    expect(screen.getByText("TriageAI")).toBeInTheDocument();
    expect(screen.getByText("Dr. M. Santos")).toBeInTheDocument();
    expect(screen.getByText(/Veterinary Reviewer/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Help" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log out" })).toBeInTheDocument();
  });

  it("labels the role in words, never by code", () => {
    renderWithAuth(<AppHeader user={makeUserWithRole("INTAKE_STAFF")} />);

    expect(screen.getByText(/Intake Staff/)).toBeInTheDocument();
    expect(screen.queryByText(/INTAKE_STAFF/)).not.toBeInTheDocument();
  });
});
