import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/errors";
import { renderWithAuth } from "../../test/testUtils";
import { Login } from "./Login";

function fillAndSubmit(email = "intake@triageai.local", password = "ChangeMe!2026") {
  fireEvent.change(screen.getByLabelText("Username or e-mail"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Log In" }));
}

describe("Login screen content (W-01)", () => {
  it("matches the wireframe's standing notices", () => {
    renderWithAuth(<Login />, { route: "/login" });

    expect(
      screen.getByText("After 5 failed attempts your account is locked for 15 minutes."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Data Privacy Act of 2012 \(RA 10173\)/)).toBeInTheDocument();
    expect(screen.getByText("Forgot password? Ask your administrator.")).toBeInTheDocument();
    expect(screen.getByText("Sign in with your clinic account.")).toBeInTheDocument();
  });

  it("carries no theme control: the sign-in screen follows the device", () => {
    renderWithAuth(<Login />, { route: "/login" });

    expect(screen.queryByRole("group", { name: "Theme" })).not.toBeInTheDocument();
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("labels both inputs and marks the password field as a password (IR-07)", () => {
    renderWithAuth(<Login />, { route: "/login" });

    expect(screen.getByLabelText("Username or e-mail")).toHaveAttribute("type", "text");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
  });
});

describe("Login failures (SR-03, IR-05)", () => {
  it("shows the generic error on a 401, whatever the cause", async () => {
    const login = vi
      .fn()
      .mockRejectedValue(
        new ApiError(401, "INVALID_CREDENTIALS", "Incorrect username or password."),
      );
    renderWithAuth(<Login />, { route: "/login", login });

    fillAndSubmit();

    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect username or password.");
  });

  it("gives an unknown e-mail the same message as a wrong password", async () => {
    // A malformed address comes back as 422; the screen must not treat that as
    // a different outcome, or it would reveal the field was validated at all.
    const login = vi
      .fn()
      .mockRejectedValue(
        new ApiError(422, "VALIDATION_ERROR", "email: value is not a valid email"),
      );
    renderWithAuth(<Login />, { route: "/login", login });

    fillAndSubmit("not-an-address", "ChangeMe!2026");

    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect username or password.");
  });

  it("never leaks the API's wording or code into the form", async () => {
    const login = vi
      .fn()
      .mockRejectedValue(new ApiError(500, "INTERNAL_ERROR", "psycopg.OperationalError: boom"));
    renderWithAuth(<Login />, { route: "/login", login });

    fillAndSubmit();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Sign-in is unavailable right now.");
    expect(alert).not.toHaveTextContent("psycopg");
    expect(alert).not.toHaveTextContent("INTERNAL_ERROR");
  });

  it("asks for a missing field without calling the API", () => {
    const login = vi.fn();
    renderWithAuth(<Login />, { route: "/login", login });

    fireEvent.click(screen.getByRole("button", { name: "Log In" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Enter your username or e-mail address.");
    expect(login).not.toHaveBeenCalled();
  });
});

describe("Login lockout (SR-03)", () => {
  it("shows the unlock time from the 423 message in the clinic's timezone", async () => {
    // 01:15 UTC is 09:15 in Asia/Manila (UTC+8).
    const login = vi
      .fn()
      .mockRejectedValue(
        new ApiError(
          423,
          "ACCOUNT_LOCKED",
          "Too many failed sign-in attempts. This account is locked until " +
            "2026-10-01T01:15:42.123456+00:00 and will unlock automatically.",
        ),
      );
    renderWithAuth(<Login />, { route: "/login", login });

    fillAndSubmit();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("9:15");
    // The raw UTC timestamp must not reach the user.
    expect(alert).not.toHaveTextContent("2026-10-01T01:15:42");
  });

  it("falls back to the server's sentence when no timestamp can be read", async () => {
    const login = vi
      .fn()
      .mockRejectedValue(
        new ApiError(423, "ACCOUNT_LOCKED", "This account is temporarily locked."),
      );
    renderWithAuth(<Login />, { route: "/login", login });

    fillAndSubmit();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This account is temporarily locked.",
    );
  });
});

describe("Login success (FR-57, FR-61)", () => {
  it("submits on Enter, without a mouse (IR-07)", async () => {
    const login = vi.fn().mockResolvedValue({
      id: "1",
      full_name: "J. Cruz",
      email: "intake@triageai.local",
      role: "INTAKE_STAFF",
      can_approve_kb: false,
      must_change_password: false,
    });
    renderWithAuth(<Login />, { route: "/login", login });

    fireEvent.change(screen.getByLabelText("Username or e-mail"), {
      target: { value: "intake@triageai.local" },
    });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "ChangeMe!2026" } });
    fireEvent.submit(screen.getByLabelText("Password").closest("form")!);

    await waitFor(() => {
      expect(login).toHaveBeenCalledWith("intake@triageai.local", "ChangeMe!2026");
    });
  });

  it("trims surrounding whitespace from the address but never the password", async () => {
    const login = vi.fn().mockResolvedValue({
      id: "1",
      full_name: "J. Cruz",
      email: "intake@triageai.local",
      role: "INTAKE_STAFF",
      can_approve_kb: false,
      must_change_password: false,
    });
    renderWithAuth(<Login />, { route: "/login", login });

    fillAndSubmit("  intake@triageai.local  ", " ChangeMe!2026 ");

    await waitFor(() => {
      expect(login).toHaveBeenCalledWith("intake@triageai.local", " ChangeMe!2026 ");
    });
  });
});
