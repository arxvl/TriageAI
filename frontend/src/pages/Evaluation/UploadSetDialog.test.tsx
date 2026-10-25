/**
 * Uploading a vignette set (FR-64 · W-10).
 *
 * What the dialog must not lose: the file goes as multipart with the set name,
 * a refused file is reported by row number so it can be fixed, and an unknown
 * knowledge-base slug is a warning to read, not a failure.
 *
 * All data here is fictitious (CLAUDE.md §9).
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { strings } from "../../i18n/strings";
import { makeSet } from "../../test/evalFixtures";
import { errorBody, makeUser, renderWithAuth } from "../../test/testUtils";
import { UploadSetDialog } from "./UploadSetDialog";

const copy = strings.evaluation.uploadDialog;

function stubUpload(status: number, body: unknown) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    void input;
    void init;
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    } as Response;
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function renderDialog() {
  const onUploaded = vi.fn();
  const onClose = vi.fn();
  renderWithAuth(<UploadSetDialog onUploaded={onUploaded} onClose={onClose} />, {
    user: makeUser({ role: "ADMINISTRATOR" }),
  });
  return { onUploaded, onClose };
}

function fillForm(name = "Set v2") {
  fireEvent.change(screen.getByLabelText(copy.nameLabel), { target: { value: name } });
  const file = new File(["external_id,species\nV-001,CAT\n"], "vignettes.csv", {
    type: "text/csv",
  });
  fireEvent.change(screen.getByLabelText(copy.fileLabel), { target: { files: [file] } });
  return file;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("sending the file", () => {
  it("posts the name and the file as multipart form data, with no JSON content type", async () => {
    const mock = stubUpload(201, makeSet({ name: "Set v2", vignette_count: 10 }));
    const { onUploaded, onClose } = renderDialog();
    const file = fillForm();

    fireEvent.click(screen.getByRole("button", { name: copy.submit }));

    await waitFor(() => expect(onUploaded).toHaveBeenCalledOnce());
    const [url, init] = mock.mock.calls[0];
    expect(String(url)).toContain("/eval/sets");
    expect(init?.method).toBe("POST");
    const body = init?.body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect(body.get("name")).toBe("Set v2");
    expect((body.get("file") as File).name).toBe(file.name);
    expect(new Headers(init?.headers).has("Content-Type")).toBe(false);
    // Clean import: nothing to read, so the dialog closes itself.
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("asks for a name and a file before sending anything", () => {
    const mock = stubUpload(201, makeSet());
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: copy.submit }));

    expect(screen.getByText(copy.nameMissing)).toBeTruthy();
    expect(screen.getByText(copy.fileMissing)).toBeTruthy();
    expect(mock).not.toHaveBeenCalled();
  });
});

describe("a refused file", () => {
  it("lists the problem rows by line number so the file can be fixed", async () => {
    stubUpload(422, {
      error: {
        code: "VALIDATION_ERROR",
        message: "The vignette file has errors.",
        rows: [
          { row: 3, field: "reference_category", message: "Unknown category PURPLE." },
          { row: 7, field: null, message: "Duplicate external_id V-002." },
          { row: 0, field: null, message: "The file is empty." },
        ],
      },
    });
    const { onUploaded, onClose } = renderDialog();
    fillForm();

    fireEvent.click(screen.getByRole("button", { name: copy.submit }));

    expect(
      await screen.findByText("Row 3 (reference_category): Unknown category PURPLE."),
    ).toBeTruthy();
    expect(screen.getByText("Row 7: Duplicate external_id V-002.")).toBeTruthy();
    expect(screen.getByText("The file is empty.")).toBeTruthy();
    expect(screen.getByText(copy.rowsHeading)).toBeTruthy();
    // Still open, so the person can pick the corrected file.
    expect(onUploaded).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("puts a duplicate set name beside the name field", async () => {
    stubUpload(409, errorBody("EVALUATION_NAME_IN_USE", "Name in use.", "name"));
    renderDialog();
    fillForm("Set v1");

    fireEvent.click(screen.getByRole("button", { name: copy.submit }));

    expect(await screen.findByText(copy.nameInUse)).toBeTruthy();
    expect(screen.getByLabelText(copy.nameLabel).getAttribute("aria-invalid")).toBe("true");
  });

  it("reports an unexpected failure in plain language", async () => {
    stubUpload(500, errorBody("INTERNAL_ERROR", "boom"));
    renderDialog();
    fillForm();

    fireEvent.click(screen.getByRole("button", { name: copy.submit }));

    expect(await screen.findByText(strings.evaluation.errors.uploadFailed)).toBeTruthy();
  });
});

describe("unknown knowledge-base entries", () => {
  it("imports the set and keeps the dialog open on the warnings", async () => {
    stubUpload(
      201,
      makeSet({
        vignette_count: 10,
        warnings: ["Unknown knowledge-base entry slug: made-up-entry"],
      }),
    );
    const { onUploaded, onClose } = renderDialog();
    fillForm();

    fireEvent.click(screen.getByRole("button", { name: copy.submit }));

    expect(
      await screen.findByText("Unknown knowledge-base entry slug: made-up-entry"),
    ).toBeTruthy();
    expect(screen.getByText("10 vignettes imported.")).toBeTruthy();
    expect(onUploaded).toHaveBeenCalledOnce();
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: copy.close }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
