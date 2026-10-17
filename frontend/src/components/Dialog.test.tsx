import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Dialog, DialogActions } from "./Dialog";

function renderDialog(props: { onClose?: () => void; isBusy?: boolean } = {}) {
  return render(
    <Dialog title="Confirm Orange?" onClose={props.onClose ?? vi.fn()} isBusy={props.isBusy}>
      <p>This records Orange as the final urgency category.</p>
      <DialogActions>
        <button type="button">Cancel</button>
        <button type="button">Confirm decision</button>
      </DialogActions>
    </Dialog>,
  );
}

/** A dialog opened from a button, so focus has somewhere to return to. */
function Harness() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <button type="button" onClick={() => setIsOpen(true)}>
        Adjust category…
      </button>
      {isOpen && (
        <Dialog title="Adjust urgency category" onClose={() => setIsOpen(false)}>
          <button type="button">Save decision</button>
        </Dialog>
      )}
    </>
  );
}

describe("Dialog", () => {
  it("is a modal dialog named by its heading", () => {
    renderDialog();

    const dialog = screen.getByRole("dialog", { name: "Confirm Orange?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  // A keyboard user must land inside the dialog, not behind the overlay.
  it("focuses the first control on open", () => {
    renderDialog();

    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("keeps Tab inside the dialog", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog");
    const cancel = screen.getByRole("button", { name: "Cancel" });
    const confirm = screen.getByRole("button", { name: "Confirm decision" });

    confirm.focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(cancel).toHaveFocus();

    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(confirm).toHaveFocus();
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    renderDialog({ onClose });

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });

    expect(onClose).toHaveBeenCalledOnce();
  });

  it("closes on a click outside the panel", () => {
    const onClose = vi.fn();
    const { container } = renderDialog({ onClose });

    fireEvent.mouseDown(container.firstElementChild as Element);

    expect(onClose).toHaveBeenCalledOnce();
  });

  it("does not close on a click inside the panel", () => {
    const onClose = vi.fn();
    renderDialog({ onClose });

    fireEvent.mouseDown(screen.getByRole("dialog"));

    expect(onClose).not.toHaveBeenCalled();
  });

  // A decision already in flight must not be dismissed out from under itself.
  it("ignores Escape and the overlay while busy", () => {
    const onClose = vi.fn();
    const { container } = renderDialog({ onClose, isBusy: true });

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    fireEvent.mouseDown(container.firstElementChild as Element);

    expect(onClose).not.toHaveBeenCalled();
  });

  it("returns focus to whatever opened it", () => {
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Adjust category…" });

    // A real click focuses the button first; `fireEvent.click` does not, and the
    // element focus returns to is whatever had it when the dialog opened.
    opener.focus();
    fireEvent.click(opener);
    expect(screen.getByRole("button", { name: "Save decision" })).toHaveFocus();

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(opener).toHaveFocus();
  });
});
