/**
 * W-09 User Management (FR-60, FR-63, SR-03, BR-04 · UC-12).
 *
 * What the screen must not lose:
 *
 * - the status column says Active, Deactivated or "Locked until HH:MM" in words,
 *   with the matching action (IR-03);
 * - the knowledge base approval checkbox is available for a Veterinary Reviewer
 *   only, and is cleared when the role changes away from it (BR-04);
 * - a temporary password is shown once, with the warning, and is gone from the
 *   page when the dialog closes (FR-60);
 * - a refusal to remove the last administrator is reported in plain language.
 *
 * All data here is fictitious (CLAUDE.md §9).
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AdminUser } from "../../api/users";
import { strings } from "../../i18n/strings";
import { errorBody, makeUser, renderWithAuth } from "../../test/testUtils";
import { Users } from "./Users";

const copy = strings.users;

const TEMPORARY_PASSWORD = "Xk7mQ2pRt9WvB4nZ";

const HOUR_MS = 60 * 60 * 1000;

function makeAdminUser(overrides: Partial<AdminUser> = {}): AdminUser {
  return {
    id: "00000000-0000-4000-8000-0000000000a1",
    full_name: "Reviewer Demo",
    email: "reviewer@triageai.invalid",
    role: "VETERINARY_REVIEWER",
    can_approve_kb: false,
    is_active: true,
    must_change_password: false,
    locked_until: null,
    last_login_at: "2026-10-12T01:30:00Z",
    ...overrides,
  };
}

const ACTIVE = makeAdminUser();
const APPROVER = makeAdminUser({
  id: "00000000-0000-4000-8000-0000000000a2",
  full_name: "KB Approver Demo",
  email: "approver@triageai.invalid",
  can_approve_kb: true,
});
const LOCKED = makeAdminUser({
  id: "00000000-0000-4000-8000-0000000000a3",
  full_name: "R. Dela Pena",
  email: "delapena@triageai.invalid",
  role: "INTAKE_STAFF",
  locked_until: new Date(Date.now() + HOUR_MS).toISOString(),
});
const DEACTIVATED = makeAdminUser({
  id: "00000000-0000-4000-8000-0000000000a4",
  full_name: "T. Garcia",
  email: "garcia@triageai.invalid",
  role: "INTAKE_STAFF",
  is_active: false,
  last_login_at: null,
});
const ADMIN = makeAdminUser({
  id: "00000000-0000-4000-8000-0000000000a5",
  full_name: "System Administrator",
  email: "admin@triageai.invalid",
  role: "ADMINISTRATOR",
});

interface Stubbed {
  status?: number;
  body?: unknown;
}

type Handler = (method: string, url: string) => Stubbed | undefined;

/** Answer by method and path, because `/users` is a prefix of every other route. */
function stubApi(handler: Handler, users: AdminUser[] = [ACTIVE, APPROVER, LOCKED, DEACTIVATED]) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    const stub =
      handler(method, url) ??
      (method === "GET" && url.includes("/users")
        ? { body: { items: users, total: users.length } }
        : { status: 404 });
    const status = stub.status ?? 200;
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => stub.body ?? {},
    } as Response;
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function callsTo(mock: ReturnType<typeof stubApi>, method: string, fragment: string) {
  return mock.mock.calls.filter(
    ([input, init]) => (init?.method ?? "GET") === method && String(input).includes(fragment),
  );
}

function bodyOf(call: Parameters<ReturnType<typeof stubApi>>) {
  return JSON.parse(String(call[1]?.body)) as Record<string, unknown>;
}

function renderUsers() {
  return renderWithAuth(<Users />, {
    user: makeUser({ role: "ADMINISTRATOR", full_name: "System Administrator" }),
    route: "/admin/users",
  });
}

function fillAddForm(name = "Maria Santos", email = "maria.santos@triageai.invalid") {
  fireEvent.change(screen.getByLabelText(copy.add.fullName), { target: { value: name } });
  fireEvent.change(screen.getByLabelText(copy.add.email), { target: { value: email } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the account table (FR-60, SR-03)", () => {
  it("writes each status out and offers the matching action", async () => {
    stubApi(() => undefined);
    renderUsers();

    const row = async (name: string) =>
      (await screen.findByText(name)).closest("tr") as HTMLElement;

    const active = await row("Reviewer Demo");
    expect(within(active).getByText(copy.statusActive)).toBeTruthy();
    expect(within(active).queryByRole("button", { name: /Unlock/ })).toBeNull();

    const locked = await row("R. Dela Pena");
    expect(within(locked).getByText(/^Locked until \d{2}:\d{2}$/)).toBeTruthy();
    expect(
      within(locked).getByRole("button", { name: `${copy.unlock} R. Dela Pena` }),
    ).toBeTruthy();

    const deactivated = await row("T. Garcia");
    expect(within(deactivated).getByText(copy.statusDeactivated)).toBeTruthy();
    expect(within(deactivated).getByText(copy.neverSignedIn)).toBeTruthy();
    expect(
      within(deactivated).getByRole("button", { name: `${copy.reactivate} T. Garcia` }),
    ).toBeTruthy();
  });

  it("shows KB approval only for the account that holds it", async () => {
    stubApi(() => undefined);
    renderUsers();

    const approver = (await screen.findByText("KB Approver Demo")).closest("tr") as HTMLElement;
    const plain = (await screen.findByText("Reviewer Demo")).closest("tr") as HTMLElement;

    expect(within(approver).getByText(copy.kbApprovalYes)).toBeTruthy();
    expect(within(plain).queryByText(copy.kbApprovalYes)).toBeNull();
  });

  it("searches by the text typed", async () => {
    const mock = stubApi(() => undefined);
    renderUsers();
    await screen.findByText("Reviewer Demo");

    fireEvent.change(screen.getByLabelText(copy.searchLabel), { target: { value: "santos" } });
    fireEvent.click(screen.getByRole("button", { name: copy.searchButton }));

    await waitFor(() =>
      expect(mock.mock.calls.some(([url]) => String(url).includes("q=santos"))).toBe(true),
    );
  });

  it("unlocks a locked account", async () => {
    const mock = stubApi((method, url) =>
      method === "POST" && url.includes("/unlock")
        ? { body: { ...LOCKED, locked_until: null } }
        : undefined,
    );
    renderUsers();

    fireEvent.click(await screen.findByRole("button", { name: `${copy.unlock} R. Dela Pena` }));

    await waitFor(() => expect(callsTo(mock, "POST", `/users/${LOCKED.id}/unlock`).length).toBe(1));
  });

  it("reactivates a deactivated account", async () => {
    const mock = stubApi((method, url) =>
      method === "PATCH" && url.includes(DEACTIVATED.id)
        ? { body: { ...DEACTIVATED, is_active: true } }
        : undefined,
    );
    renderUsers();

    fireEvent.click(await screen.findByRole("button", { name: `${copy.reactivate} T. Garcia` }));

    await waitFor(() => expect(callsTo(mock, "PATCH", DEACTIVATED.id).length).toBe(1));
    expect(bodyOf(callsTo(mock, "PATCH", DEACTIVATED.id)[0])).toEqual({ is_active: true });
  });
});

describe("the add-user panel (BR-04)", () => {
  it("enables the KB approval checkbox for a Veterinary Reviewer only and clears it otherwise", async () => {
    stubApi(() => undefined);
    renderUsers();
    await screen.findByText("Reviewer Demo");

    const checkbox = screen.getByLabelText(copy.add.kbApproval) as HTMLInputElement;
    expect(checkbox.disabled).toBe(true);
    expect(screen.getByText(copy.add.kbApprovalHelp)).toBeTruthy();

    fireEvent.change(screen.getByLabelText(copy.add.role), {
      target: { value: "VETERINARY_REVIEWER" },
    });
    expect(checkbox.disabled).toBe(false);
    fireEvent.click(checkbox);
    expect(checkbox.checked).toBe(true);

    fireEvent.change(screen.getByLabelText(copy.add.role), { target: { value: "ADMINISTRATOR" } });
    expect(checkbox.disabled).toBe(true);
    expect(checkbox.checked).toBe(false);
  });

  it("checks the form before sending anything", async () => {
    const mock = stubApi(() => undefined);
    renderUsers();
    await screen.findByText("Reviewer Demo");

    fillAddForm("   ", "not-an-address");
    fireEvent.click(screen.getByRole("button", { name: copy.add.submit }));

    expect(await screen.findByText(copy.add.fullNameMissing)).toBeTruthy();
    expect(screen.getByText(copy.add.emailInvalid)).toBeTruthy();
    expect(callsTo(mock, "POST", "/users").length).toBe(0);
  });

  it("shows the temporary password once, with its warning, and drops it on close", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    const mock = stubApi((method) =>
      method === "POST"
        ? {
            status: 201,
            body: {
              user: makeAdminUser({ full_name: "Maria Santos", must_change_password: true }),
              temporary_password: TEMPORARY_PASSWORD,
            },
          }
        : undefined,
    );
    renderUsers();
    await screen.findByText("Reviewer Demo");

    fillAddForm();
    fireEvent.click(screen.getByRole("button", { name: copy.add.submit }));

    const dialog = await screen.findByRole("dialog");
    expect(bodyOf(callsTo(mock, "POST", "/users")[0])).toEqual({
      full_name: "Maria Santos",
      email: "maria.santos@triageai.invalid",
      role: "INTAKE_STAFF",
      can_approve_kb: false,
    });
    expect(
      (within(dialog).getByLabelText(copy.temporaryPassword.label) as HTMLInputElement).value,
    ).toBe(TEMPORARY_PASSWORD);
    expect(within(dialog).getByText(copy.temporaryPassword.warning)).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: copy.temporaryPassword.copy }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(TEMPORARY_PASSWORD));

    fireEvent.click(within(dialog).getByRole("button", { name: copy.temporaryPassword.done }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.body.innerHTML).not.toContain(TEMPORARY_PASSWORD);

    // The form is empty again for the next account.
    expect((screen.getByLabelText(copy.add.fullName) as HTMLInputElement).value).toBe("");
  });

  it("puts a duplicate e-mail beside the e-mail field", async () => {
    stubApi((method) =>
      method === "POST"
        ? {
            status: 409,
            body: errorBody(
              "EMAIL_ALREADY_IN_USE",
              "Another account already uses that e-mail address.",
              "email",
            ),
          }
        : undefined,
    );
    renderUsers();
    await screen.findByText("Reviewer Demo");

    fillAddForm();
    fireEvent.click(screen.getByRole("button", { name: copy.add.submit }));

    expect(await screen.findByText(copy.errors.emailInUse)).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("editing an account (FR-60)", () => {
  it("sends only what changed", async () => {
    const mock = stubApi((method) =>
      method === "PATCH" ? { body: { ...ACTIVE, full_name: "Reviewer Renamed" } } : undefined,
    );
    renderUsers();

    fireEvent.click(await screen.findByRole("button", { name: `${copy.edit} Reviewer Demo` }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(copy.editDialog.fullName), {
      target: { value: "Reviewer Renamed" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: copy.editDialog.save }));

    await waitFor(() => expect(callsTo(mock, "PATCH", ACTIVE.id).length).toBe(1));
    expect(bodyOf(callsTo(mock, "PATCH", ACTIVE.id)[0])).toEqual({ full_name: "Reviewer Renamed" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("clears KB approval when the role moves away from Veterinary Reviewer", async () => {
    const mock = stubApi((method) => (method === "PATCH" ? { body: ACTIVE } : undefined));
    renderUsers();

    fireEvent.click(await screen.findByRole("button", { name: `${copy.edit} KB Approver Demo` }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(copy.editDialog.role), {
      target: { value: "INTAKE_STAFF" },
    });
    expect(
      (within(dialog).getByLabelText(copy.editDialog.kbApproval) as HTMLInputElement).disabled,
    ).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: copy.editDialog.save }));

    await waitFor(() => expect(callsTo(mock, "PATCH", APPROVER.id).length).toBe(1));
    expect(bodyOf(callsTo(mock, "PATCH", APPROVER.id)[0])).toEqual({
      role: "INTAKE_STAFF",
      can_approve_kb: false,
    });
  });

  it("reports the last-administrator refusal in plain language and keeps the dialog open", async () => {
    stubApi(
      (method) =>
        method === "PATCH"
          ? { status: 409, body: errorBody("LAST_ADMINISTRATOR", "server wording") }
          : undefined,
      [ADMIN],
    );
    renderUsers();

    fireEvent.click(
      await screen.findByRole("button", { name: `${copy.edit} System Administrator` }),
    );
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByLabelText(copy.editDialog.active));
    fireEvent.click(within(dialog).getByRole("button", { name: copy.editDialog.save }));

    expect(await within(dialog).findByText(copy.errors.lastAdministrator)).toBeTruthy();
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("asks twice before resetting a password, then shows the new one once", async () => {
    const mock = stubApi((method, url) =>
      method === "POST" && url.includes("/reset-password")
        ? { body: { user: ACTIVE, temporary_password: TEMPORARY_PASSWORD } }
        : undefined,
    );
    renderUsers();

    fireEvent.click(await screen.findByRole("button", { name: `${copy.edit} Reviewer Demo` }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: copy.editDialog.resetPassword }));
    expect(callsTo(mock, "POST", "/reset-password").length).toBe(0);

    fireEvent.click(
      within(dialog).getByRole("button", { name: copy.editDialog.resetPasswordConfirm }),
    );

    await waitFor(() =>
      expect(callsTo(mock, "POST", `/users/${ACTIVE.id}/reset-password`).length).toBe(1),
    );
    const shown = await screen.findByLabelText(copy.temporaryPassword.label);
    expect((shown as HTMLInputElement).value).toBe(TEMPORARY_PASSWORD);
    expect(screen.getByText(copy.temporaryPassword.warning)).toBeTruthy();
  });
});
