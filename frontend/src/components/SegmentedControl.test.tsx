import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SegmentedControl } from "./SegmentedControl";

const options = [
  { value: "DOG", label: "Dog" },
  { value: "CAT", label: "Cat" },
  { value: "OTHER", label: "Other species" },
] as const;

describe("SegmentedControl (IR-07, NFR-21)", () => {
  it("exposes the options as a named radio group", () => {
    render(
      <SegmentedControl
        name="species"
        legend="Species (required)"
        options={options}
        value={null}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("group", { name: "Species (required)" })).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(3);
  });

  it("marks only the chosen option as checked", () => {
    render(
      <SegmentedControl
        name="species"
        legend="Species (required)"
        options={options}
        value="CAT"
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("radio", { name: "Cat" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Dog" })).not.toBeChecked();
  });

  it("leaves every option unchecked when nothing is chosen yet", () => {
    render(
      <SegmentedControl
        name="species"
        legend="Species (required)"
        options={options}
        value={null}
        onChange={vi.fn()}
      />,
    );

    for (const radio of screen.getAllByRole("radio")) {
      expect(radio).not.toBeChecked();
    }
  });

  it("reports the value of the option that was chosen", () => {
    const onChange = vi.fn();
    render(
      <SegmentedControl
        name="species"
        legend="Species (required)"
        options={options}
        value="CAT"
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("radio", { name: "Other species" }));

    expect(onChange).toHaveBeenCalledWith("OTHER");
  });

  it("points the group at the text that explains it", () => {
    render(
      <>
        <SegmentedControl
          name="species"
          legend="Species (required)"
          options={options}
          value="OTHER"
          onChange={vi.fn()}
          describedBy="species-notice"
          invalid
        />
        <p id="species-notice">Other species are not processed by the AI.</p>
      </>,
    );

    const group = screen.getByRole("group", { name: "Species (required)" });
    expect(group).toHaveAttribute("aria-describedby", "species-notice");
    expect(group).toHaveAttribute("aria-invalid", "true");
  });
});
