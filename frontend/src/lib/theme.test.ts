import { describe, expect, it } from "vitest";

import { stubMatchMedia } from "../test/setup";
import {
  applyPreference,
  readStoredPreference,
  resolveTheme,
  storePreference,
  systemTheme,
  THEME_STORAGE_KEY,
  watchSystemTheme,
} from "./theme";

describe("theme preference storage", () => {
  it("defaults to following the device", () => {
    expect(readStoredPreference()).toBe("system");
  });

  it("reads back a stored choice", () => {
    storePreference("dark");
    expect(readStoredPreference()).toBe("dark");
  });

  it("ignores a value that is not a theme", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "midnight");
    expect(readStoredPreference()).toBe("system");
  });

  it("clears the key when the choice goes back to the device", () => {
    storePreference("light");
    storePreference("system");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });
});

describe("resolving a preference", () => {
  it("takes an explicit choice as given", () => {
    stubMatchMedia(true);
    expect(resolveTheme("light")).toBe("light");
    expect(resolveTheme("dark")).toBe("dark");
  });

  it("asks the device for 'system'", () => {
    stubMatchMedia(true);
    expect(resolveTheme("system")).toBe("dark");

    stubMatchMedia(false);
    expect(resolveTheme("system")).toBe("light");
  });

  it("falls back to light where the browser cannot be asked", () => {
    // @ts-expect-error — removing it is the condition under test.
    delete window.matchMedia;

    expect(systemTheme()).toBe("light");
    expect(watchSystemTheme(() => {})).toBeTypeOf("function");
  });
});

describe("applying a preference to the document", () => {
  it("writes the attribute for an explicit choice", () => {
    applyPreference("dark");
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");

    applyPreference("light");
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
  });

  it("removes the attribute for 'system', so the stylesheet follows the device", () => {
    applyPreference("dark");
    applyPreference("system");

    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });
});
