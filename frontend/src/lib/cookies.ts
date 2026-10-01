/**
 * The only place that reads `document.cookie`.
 *
 * Only `triageai_csrf` is readable here: `triageai_session` is HttpOnly by
 * design, so JavaScript — including injected JavaScript — cannot see it
 * (ADR-11).
 */
export function readCookie(name: string): string | null {
  // `document` is absent in a non-browser environment; fail soft rather than throw.
  if (typeof document === "undefined") {
    return null;
  }

  const prefix = `${name}=`;
  for (const entry of document.cookie.split(";")) {
    const candidate = entry.trim();
    if (candidate.startsWith(prefix)) {
      return decodeURIComponent(candidate.slice(prefix.length));
    }
  }

  return null;
}
