import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { PasswordField } from "./PasswordField";

/** A host for the field, because its value is controlled by the form around it. */
function Host({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <PasswordField
      id="test-password"
      label="Password"
      autoComplete="current-password"
      value={value}
      onChange={setValue}
    />
  );
}

function revealButton() {
  return screen.getByRole("button", { name: /password/ });
}

describe("PasswordField reveal (IR-07, NFR-21)", () => {
  it("starts hidden", () => {
    render(<Host />);

    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(revealButton()).toHaveAccessibleName("Show password");
    expect(revealButton()).toHaveAttribute("aria-pressed", "false");
  });

  it("shows the characters when the eye is clicked, and hides them again", () => {
    render(<Host initial="ChangeMe!2026" />);

    fireEvent.click(revealButton());

    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "text");
    expect(revealButton()).toHaveAccessibleName("Hide password");
    expect(revealButton()).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(revealButton());

    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(revealButton()).toHaveAccessibleName("Show password");
  });

  it("keeps the typed value across a reveal", () => {
    render(<Host />);

    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "ChangeMe!2026" } });
    fireEvent.click(revealButton());

    expect(screen.getByLabelText("Password")).toHaveValue("ChangeMe!2026");
  });

  it("does not submit the form it sits in", () => {
    let submits = 0;
    render(
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submits += 1;
        }}
      >
        <Host />
      </form>,
    );

    fireEvent.click(revealButton());

    expect(submits).toBe(0);
    expect(revealButton()).toHaveAttribute("type", "button");
  });

  it("points at the input it controls and keeps the field's own description", () => {
    render(
      <>
        <PasswordField
          id="new-password"
          label="New password"
          autoComplete="new-password"
          value=""
          describedBy="policy-hint"
          onChange={() => {}}
        />
        <p id="policy-hint">At least 12 characters.</p>
      </>,
    );

    const input = screen.getByLabelText("New password");
    expect(input).toHaveAttribute("aria-describedby", "policy-hint");
    expect(revealButton()).toHaveAttribute("aria-controls", "new-password");
  });

  it("never carries a revealed state over from a previous mount", () => {
    const first = render(<Host />);
    fireEvent.click(revealButton());
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "text");
    first.unmount();

    render(<Host />);

    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
  });
});
