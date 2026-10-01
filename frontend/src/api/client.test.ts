import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch, setSessionEndedHandler } from "./client";
import { ApiError } from "./errors";

/** Build the minimal `Response` shape `apiFetch` touches. */
function response(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function stub(status: number, body: unknown) {
  // Typed as `fetch` so `mock.calls` keeps that signature's tuple shape and a
  // test can read the init argument back out.
  const mock = vi.fn<typeof fetch>(async () => response(status, body));
  vi.stubGlobal("fetch", mock);
  return mock;
}

function headersOf(mock: ReturnType<typeof stub>): Headers {
  return new Headers(mock.mock.calls[0]?.[1]?.headers);
}

describe("apiFetch CSRF double-submit (SR-09, ADR-11)", () => {
  beforeEach(() => {
    document.cookie = "triageai_csrf=csrf-token-value; path=/";
  });

  it("sends the CSRF cookie back as X-CSRF-Token on a POST", async () => {
    const mock = stub(200, { ok: true });

    await apiFetch("/cases", { method: "POST", body: "{}" });

    expect(headersOf(mock).get("X-CSRF-Token")).toBe("csrf-token-value");
  });

  it.each(["PATCH", "PUT", "DELETE"])("sends the header on %s too", async (method) => {
    const mock = stub(200, { ok: true });

    await apiFetch("/cases/1", { method });

    expect(headersOf(mock).get("X-CSRF-Token")).toBe("csrf-token-value");
  });

  it("omits the header on a GET, which the server never checks", async () => {
    const mock = stub(200, { ok: true });

    await apiFetch("/cases");

    expect(headersOf(mock).has("X-CSRF-Token")).toBe(false);
  });

  it("omits the header when no CSRF cookie has been issued yet", async () => {
    document.cookie = "triageai_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
    const mock = stub(200, { ok: true });

    await apiFetch("/auth/login", { method: "POST", body: "{}" });

    expect(headersOf(mock).has("X-CSRF-Token")).toBe(false);
  });

  it("always sends cookies, because the session is one (ADR-11)", async () => {
    const mock = stub(200, { ok: true });

    await apiFetch("/auth/me");

    const init = mock.mock.calls[0]?.[1];
    expect(init?.credentials).toBe("include");
  });
});

describe("apiFetch error mapping (IR-05)", () => {
  it("turns the error envelope into a typed ApiError", async () => {
    stub(401, {
      error: { code: "INVALID_CREDENTIALS", message: "Incorrect username or password." },
    });

    const error = await apiFetch("/auth/login", { method: "POST" }).catch(
      (caught: unknown) => caught,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 401,
      code: "INVALID_CREDENTIALS",
      message: "Incorrect username or password.",
    });
  });

  it("keeps the field a validation error names, so a form can place it (FR-04)", async () => {
    stub(422, {
      error: {
        code: "VALIDATION_ERROR",
        message: "Enter the weight as a number, e.g. 4.2.",
        field: "weight_kg",
      },
    });

    const error = (await apiFetch("/cases", { method: "POST" }).catch(
      (caught: unknown) => caught,
    )) as ApiError;

    expect(error.code).toBe("VALIDATION_ERROR");
    expect(error.field).toBe("weight_kg");
  });

  it("leaves the field null when the envelope names none", async () => {
    stub(422, {
      error: {
        code: "SPECIES_OUT_OF_SCOPE",
        message: "Other species are not processed by the AI and must be triaged manually.",
      },
    });

    const error = (await apiFetch("/cases", { method: "POST" }).catch(
      (caught: unknown) => caught,
    )) as ApiError;

    expect(error.code).toBe("SPECIES_OUT_OF_SCOPE");
    expect(error.field).toBeNull();
  });

  it("falls back to a plain sentence when the body is not the envelope", async () => {
    stub(500, "<html>gateway error</html>");

    const error = (await apiFetch("/cases").catch((caught: unknown) => caught)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(500);
    expect(error.code).toBe("HTTP_500");
    // No stack trace or technical code reaches the message (IR-05).
    expect(error.message).toBe("Something went wrong. Please try again.");
  });

  it("reports an unreachable server rather than throwing a raw fetch failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );

    const error = (await apiFetch("/cases").catch((caught: unknown) => caught)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("NETWORK_ERROR");
  });

  it("returns undefined for a 204 instead of parsing an empty body", async () => {
    stub(204, undefined);

    await expect(apiFetch("/cases/1", { method: "DELETE" })).resolves.toBeUndefined();
  });
});

describe("apiFetch session-ended handling (SR-04)", () => {
  it("notifies the handler when a protected call reports no session", async () => {
    const onSessionEnded = vi.fn();
    setSessionEndedHandler(onSessionEnded);
    stub(401, { error: { code: "NOT_AUTHENTICATED", message: "Please sign in to continue." } });

    await apiFetch("/cases").catch(() => undefined);

    expect(onSessionEnded).toHaveBeenCalledOnce();
    setSessionEndedHandler(null);
  });

  it("treats a failed CSRF check as a dead session", async () => {
    const onSessionEnded = vi.fn();
    setSessionEndedHandler(onSessionEnded);
    stub(403, { error: { code: "CSRF_FAILED", message: "Your session could not be verified." } });

    await apiFetch("/cases", { method: "POST" }).catch(() => undefined);

    expect(onSessionEnded).toHaveBeenCalledOnce();
    setSessionEndedHandler(null);
  });

  it("stays quiet for /auth/me, where a 401 only means nobody is signed in", async () => {
    const onSessionEnded = vi.fn();
    setSessionEndedHandler(onSessionEnded);
    stub(401, { error: { code: "NOT_AUTHENTICATED", message: "Please sign in to continue." } });

    await apiFetch("/auth/me").catch(() => undefined);

    expect(onSessionEnded).not.toHaveBeenCalled();
    setSessionEndedHandler(null);
  });

  it("stays quiet for a wrong-role 403, which is not a session problem", async () => {
    const onSessionEnded = vi.fn();
    setSessionEndedHandler(onSessionEnded);
    stub(403, { error: { code: "FORBIDDEN", message: "You do not have permission to do that." } });

    await apiFetch("/cases", { method: "POST" }).catch(() => undefined);

    expect(onSessionEnded).not.toHaveBeenCalled();
    setSessionEndedHandler(null);
  });
});
