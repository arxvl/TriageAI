/**
 * The one way the SPA talks to the API (ADR-02).
 *
 * Three things every call needs and no caller should repeat:
 *
 * 1. `credentials: "include"`, because the session lives in a cookie and dev is
 *    genuinely cross-origin (5173 → 8000).
 * 2. The CSRF double-submit header on state-changing requests: the readable
 *    `triageai_csrf` cookie copied into `X-CSRF-Token` (SR-09, ADR-11).
 * 3. The error envelope turned into an `ApiError`, so pages branch on a code
 *    instead of parsing JSON themselves.
 */
import { readCookie } from "../lib/cookies";
import { ApiError, ApiErrorCode, isSessionEnded, type ApiErrorRow } from "./errors";

const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

const CSRF_COOKIE_NAME = "triageai_csrf";
const CSRF_HEADER_NAME = "X-CSRF-Token";

/** Mirrors the backend's `UNSAFE_METHODS` in `app/api/middleware.py`. */
const UNSAFE_METHODS = new Set(["POST", "PATCH", "PUT", "DELETE"]);

type SessionEndedHandler = () => void;

let sessionEndedHandler: SessionEndedHandler | null = null;

/**
 * Register what to do when a request shows the session is gone.
 *
 * `AuthProvider` sets this so an expired cookie drops the cached user and lands
 * on `/login`. Keeping it a callback rather than a `window.location` assignment
 * keeps routing inside React Router and keeps this module testable.
 */
export function setSessionEndedHandler(handler: SessionEndedHandler | null): void {
  sessionEndedHandler = handler;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await send(path, init);

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

/**
 * Fetch a file the API sends as an attachment (the evaluation export, FR-69).
 *
 * Same cookie, CSRF and error handling as `apiFetch`; only the success body
 * differs. The file name is not read from `Content-Disposition`: dev is
 * cross-origin and the API does not expose that header, so the caller names the
 * download itself.
 */
export async function apiFetchBlob(path: string, init?: RequestInit): Promise<Blob> {
  const response = await send(path, init);
  return response.blob();
}

/** The request half shared by both: credentials, CSRF, and the error envelope. */
async function send(path: string, init?: RequestInit): Promise<Response> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers = new Headers(init?.headers);

  // A multipart body carries its own `Content-Type`, with the boundary only the
  // browser knows. Setting JSON over it would make the server read no file.
  if (!headers.has("Content-Type") && !(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  if (UNSAFE_METHODS.has(method)) {
    const csrfToken = readCookie(CSRF_COOKIE_NAME);
    if (csrfToken !== null) {
      headers.set(CSRF_HEADER_NAME, csrfToken);
    }
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      method,
      credentials: "include",
      headers,
    });
  } catch {
    // A failed connection, DNS failure, or blocked request: the API was never
    // reached, so there is no envelope to read.
    throw new ApiError(0, ApiErrorCode.networkError, "The server could not be reached.");
  }

  if (!response.ok) {
    const error = await toApiError(response);
    // `/auth/*` is exempt: a 401 from the `/auth/me` probe is just "not signed
    // in", and a 401 from `/auth/login` is a wrong password. Neither is an
    // expiring session, and reacting to them would loop.
    if (!path.startsWith("/auth/") && isSessionEnded(error)) {
      sessionEndedHandler?.();
    }
    throw error;
  }

  return response;
}

/**
 * Read `{"error": {"code", "message", "field"?}}`, falling back when the body is
 * not that.
 *
 * `field` is present only on a validation error and is what lets a form put the
 * message beside the input it belongs to (IR-05, FR-04).
 */
async function toApiError(response: Response): Promise<ApiError> {
  let code = `HTTP_${response.status}`;
  let message = "Something went wrong. Please try again.";
  let field: string | null = null;
  let rows: ApiErrorRow[] = [];

  try {
    const body: unknown = await response.json();
    const envelope =
      typeof body === "object" && body !== null
        ? (
            body as {
              error?: { code?: unknown; message?: unknown; field?: unknown; rows?: unknown };
            }
          ).error
        : undefined;

    if (typeof envelope?.code === "string") {
      code = envelope.code;
    }
    if (typeof envelope?.message === "string") {
      message = envelope.message;
    }
    if (typeof envelope?.field === "string") {
      field = envelope.field;
    }
    if (Array.isArray(envelope?.rows)) {
      rows = envelope.rows
        .filter(isErrorRow)
        .map((entry) => ({ row: entry.row, field: entry.field ?? null, message: entry.message }));
    }
  } catch {
    // An empty or non-JSON error body: keep the fallbacks above.
  }

  return new ApiError(response.status, code, message, field, rows);
}

/** A row as the server sends it; `field` may be absent rather than null. */
type RawErrorRow = Omit<ApiErrorRow, "field"> & { field?: string | null };

function isErrorRow(value: unknown): value is RawErrorRow {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const row = value as Record<string, unknown>;
  return (
    typeof row.row === "number" &&
    typeof row.message === "string" &&
    (row.field === undefined || row.field === null || typeof row.field === "string")
  );
}
