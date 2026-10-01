import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useToast } from "../hooks/useToast";
import { ToastProvider } from "./ToastProvider";

function Submitter() {
  const { showToast } = useToast();
  return (
    <button type="button" onClick={() => showToast("Case C-0007 submitted")}>
      Submit
    </button>
  );
}

describe("ToastProvider (IR-05)", () => {
  it("keeps the live region in the DOM before any message arrives", () => {
    render(
      <ToastProvider>
        <Submitter />
      </ToastProvider>,
    );

    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("announces the message a page asks for", () => {
    render(
      <ToastProvider>
        <Submitter />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(screen.getByRole("status")).toHaveTextContent("Case C-0007 submitted");
  });

  it("can be dismissed before it times out", () => {
    render(
      <ToastProvider>
        <Submitter />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(screen.getByRole("status")).not.toHaveTextContent("Case C-0007 submitted");
  });
});
