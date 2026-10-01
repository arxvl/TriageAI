import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { THEME_STORAGE_KEY } from "../lib/theme";
import { stubMatchMedia } from "../test/setup";
import { ThemeProvider } from "./ThemeProvider";

function GoTo({ path, label }: { path: string; label: string }) {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => void navigate(path)}>
      {label}
    </button>
  );
}

function renderAt(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ThemeProvider>
        <Routes>
          <Route path="/login" element={<GoTo path="/queue" label="Sign in" />} />
          <Route path="/queue" element={<GoTo path="/login" label="Log out" />} />
        </Routes>
      </ThemeProvider>
    </MemoryRouter>,
  );
}

function appliedTheme(): string | null {
  return document.documentElement.getAttribute("data-theme");
}

describe("ThemeProvider: where the stored preference applies", () => {
  it("applies the stored choice inside the signed-in shell", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");

    renderAt("/queue");

    expect(appliedTheme()).toBe("dark");
  });

  it("ignores the stored choice on the sign-in screen, which has no control", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");

    renderAt("/login");

    expect(appliedTheme()).toBeNull();
  });

  it("does not pin light on the sign-in screen of a device set to dark", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    stubMatchMedia(true);

    renderAt("/login");

    // No attribute at all: the stylesheet follows `prefers-color-scheme`.
    expect(appliedTheme()).toBeNull();
  });

  it("brings the stored choice back on signing in, and drops it on signing out", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    renderAt("/login");
    expect(appliedTheme()).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(appliedTheme()).toBe("dark");

    fireEvent.click(screen.getByRole("button", { name: "Log out" }));
    expect(appliedTheme()).toBeNull();
  });

  it("keeps the preference stored while the sign-in screen is showing", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");

    renderAt("/login");

    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });
});
