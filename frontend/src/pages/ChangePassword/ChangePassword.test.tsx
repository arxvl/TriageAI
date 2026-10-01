import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/errors";
import { makeUser, renderWithAuth } from "../../test/testUtils";
import { ChangePassword } from "./ChangePassword";

function fill(current: string, next: string, confirm: string) {
  fireEvent.change(screen.getByLabelText("Current password"), { target: { value: current } });
  fireEvent.change(screen.getByLabelText("New password"), { target: { value: next } });
  fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: confirm } });
  fireEvent.click(screen.getByRole("button", { name: "Change password" }));
}

const forcedUser = makeUser({ must_change_password: true });

describe("ChangePassword content (SR-02, FR-61)", () => {
  it("states the password policy", () => {
    renderWithAuth(<ChangePassword />, { user: forcedUser, route: "/change-password" });

    expect(
      screen.getByText("Use at least 12 characters, including at least one letter and one number."),
    ).toBeInTheDocument();
  });

  it("ties the policy hint to the new-password field for screen readers (IR-07)", () => {
    renderWithAuth(<ChangePassword />, { user: forcedUser, route: "/change-password" });

    const field = screen.getByLabelText("New password");
    const hintId = field.getAttribute("aria-describedby");
    expect(hintId).not.toBeNull();
    expect(document.getElementById(hintId!)).toHaveTextContent("at least 12 characters");
  });

  it("explains why the screen appeared when the password is temporary", () => {
    renderWithAuth(<ChangePassword />, { user: forcedUser, route: "/change-password" });

    expect(screen.getByText(/Your account uses a temporary password/)).toBeInTheDocument();
  });
});

describe("ChangePassword client-side checks (IR-05)", () => {
  it("refuses a mismatch without calling the API", () => {
    const changePassword = vi.fn();
    renderWithAuth(<ChangePassword />, {
      user: forcedUser,
      route: "/change-password",
      changePassword,
    });

    fill("ChangeMe!2026", "NewPassword2026", "NewPassword2027");

    expect(screen.getByRole("alert")).toHaveTextContent("do not match");
    expect(changePassword).not.toHaveBeenCalled();
  });

  it("refuses a password that is too short without calling the API", () => {
    const changePassword = vi.fn();
    renderWithAuth(<ChangePassword />, {
      user: forcedUser,
      route: "/change-password",
      changePassword,
    });

    fill("ChangeMe!2026", "short1", "short1");

    expect(screen.getByRole("alert")).toHaveTextContent("at least 12 characters");
    expect(changePassword).not.toHaveBeenCalled();
  });

  it("refuses a long password with no digit, matching the server policy", () => {
    const changePassword = vi.fn();
    renderWithAuth(<ChangePassword />, {
      user: forcedUser,
      route: "/change-password",
      changePassword,
    });

    fill("ChangeMe!2026", "NoDigitsHereAtAll", "NoDigitsHereAtAll");

    expect(screen.getByRole("alert")).toHaveTextContent("at least 12 characters");
    expect(changePassword).not.toHaveBeenCalled();
  });

  it("asks for the current password first", () => {
    const changePassword = vi.fn();
    renderWithAuth(<ChangePassword />, {
      user: forcedUser,
      route: "/change-password",
      changePassword,
    });

    fill("", "NewPassword2026", "NewPassword2026");

    expect(screen.getByRole("alert")).toHaveTextContent("Enter your current password.");
    expect(changePassword).not.toHaveBeenCalled();
  });
});

describe("ChangePassword server responses (IR-05)", () => {
  it("sends both passwords when the form is valid", async () => {
    const changePassword = vi.fn().mockResolvedValue(makeUser({ must_change_password: false }));
    renderWithAuth(<ChangePassword />, {
      user: forcedUser,
      route: "/change-password",
      changePassword,
    });

    fill("ChangeMe!2026", "NewPassword2026", "NewPassword2026");

    await waitFor(() => {
      expect(changePassword).toHaveBeenCalledWith("ChangeMe!2026", "NewPassword2026");
    });
  });

  it("shows the server's reason when it rejects the new password", async () => {
    const changePassword = vi
      .fn()
      .mockRejectedValue(
        new ApiError(
          400,
          "WEAK_PASSWORD",
          "Choose a password you have not used for this account before.",
        ),
      );
    renderWithAuth(<ChangePassword />, {
      user: forcedUser,
      route: "/change-password",
      changePassword,
    });

    fill("ChangeMe!2026", "ChangeMe!2026", "ChangeMe!2026");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Choose a password you have not used for this account before.",
    );
  });

  it("shows the server's reason when the current password is wrong", async () => {
    const changePassword = vi
      .fn()
      .mockRejectedValue(
        new ApiError(400, "CURRENT_PASSWORD_INCORRECT", "The current password is incorrect."),
      );
    renderWithAuth(<ChangePassword />, {
      user: forcedUser,
      route: "/change-password",
      changePassword,
    });

    fill("WrongPassword123", "NewPassword2026", "NewPassword2026");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The current password is incorrect.",
    );
  });

  it("keeps an unexpected failure generic", async () => {
    const changePassword = vi
      .fn()
      .mockRejectedValue(new ApiError(500, "INTERNAL_ERROR", "sqlalchemy.exc.DBAPIError"));
    renderWithAuth(<ChangePassword />, {
      user: forcedUser,
      route: "/change-password",
      changePassword,
    });

    fill("ChangeMe!2026", "NewPassword2026", "NewPassword2026");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The password could not be changed right now.");
    expect(alert).not.toHaveTextContent("sqlalchemy");
  });
});
