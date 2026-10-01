import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { THEME_STORAGE_KEY } from "../lib/theme";
import { stubMatchMedia } from "../test/setup";
import { ThemeProvider } from "./ThemeProvider";
import { ThemeToggle } from "./ThemeToggle";

/** On a signed-in route: the sign-in screen has no toggle (ThemeProvider.test). */
function renderToggle() {
  return render(
    <MemoryRouter initialEntries={["/queue"]}>
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    </MemoryRouter>,
  );
}

function option(name: "System" | "Light" | "Dark") {
  return screen.getByRole("radio", { name: new RegExp(name) });
}

describe("ThemeToggle (NFR-21)", () => {
  it("follows the device by default, with no attribute on the document", () => {
    renderToggle();

    expect(option("System")).toBeChecked();
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("names the three choices in words, not by icon alone", () => {
    renderToggle();

    expect(screen.getByRole("group", { name: "Theme" })).toBeInTheDocument();
    for (const name of ["System", "Light", "Dark"] as const) {
      expect(option(name)).toBeInTheDocument();
    }
  });

  it("puts the chosen theme on the document and remembers it", () => {
    renderToggle();

    fireEvent.click(option("Dark"));

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(option("Dark")).toBeChecked();
  });

  it("lets light be pinned on a device that prefers dark", () => {
    stubMatchMedia(true);
    renderToggle();

    fireEvent.click(option("Light"));

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });

  it("goes back to the device setting, and forgets the choice", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    renderToggle();
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");

    fireEvent.click(option("System"));

    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });

  it("starts from the stored choice rather than the device", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    stubMatchMedia(true);

    renderToggle();

    expect(option("Light")).toBeChecked();
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
  });

  it("says what System currently means on this device", () => {
    const emitChange = stubMatchMedia(true);
    renderToggle();

    expect(option("System").closest("label")).toHaveAttribute(
      "title",
      "Follow the device setting (currently Dark)",
    );

    // The browser would fire this when the OS setting flips mid-session.
    act(() => emitChange(false));

    expect(option("System").closest("label")).toHaveAttribute(
      "title",
      "Follow the device setting (currently Light)",
    );
  });
});
