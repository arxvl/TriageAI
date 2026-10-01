/**
 * IR-03's acceptance criterion, as a test: "a colour-only badge fails the
 * component test". Every category must put its name *and* its target waiting
 * time on screen as text.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { strings } from "../i18n/strings";
import { URGENCY_ORDER } from "../lib/vtl";
import { VtlBadge } from "./VtlBadge";

const copy = strings.vtl;

describe("VtlBadge", () => {
  it.each(URGENCY_ORDER)("renders the name and the target time for %s", (category) => {
    render(<VtlBadge category={category} />);

    expect(screen.getByText(copy.codes[category])).toBeInTheDocument();
    expect(screen.getByText(copy.targets[category])).toBeInTheDocument();
  });

  it("names MANUAL, which has no category and so no target time", () => {
    render(<VtlBadge category="MANUAL" />);

    expect(screen.getByText(copy.codes.MANUAL)).toBeInTheDocument();
    for (const category of URGENCY_ORDER) {
      expect(screen.queryByText(copy.targets[category])).not.toBeInTheDocument();
    }
  });

  it("explains an empty category instead of showing a bare dash", () => {
    render(<VtlBadge category={null} />);

    expect(screen.getByText(strings.queue.notAvailable)).toBeInTheDocument();
    expect(screen.getByText(copy.noCategory)).toBeInTheDocument();
  });

  // Yellow is the one fill that cannot carry white text at 4.5:1 (NFR-21).
  it("gives YELLOW its own class, so its text can be darkened", () => {
    const { container } = render(<VtlBadge category="YELLOW" />);
    const badge = container.firstElementChild;

    expect(badge?.className).toContain("yellow");
  });

  it("renders the same text at the larger size", () => {
    render(<VtlBadge category="RED" size="md" />);

    expect(screen.getByText(copy.codes.RED)).toBeInTheDocument();
    expect(screen.getByText(copy.targets.RED)).toBeInTheDocument();
  });
});
