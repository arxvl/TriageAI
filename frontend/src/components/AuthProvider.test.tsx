import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useAuth } from "../hooks/useAuth";
import { errorBody, makeUser, renderWithProviders, stubFetch } from "../test/testUtils";

/** Renders whatever the provider resolved to, so a test can assert on it. */
function SessionProbe() {
  const { user, isLoading } = useAuth();
  if (isLoading) {
    return <p>loading</p>;
  }
  return <p>{user === null ? "signed out" : user.full_name}</p>;
}

describe("AuthProvider session restore (FR-57)", () => {
  it("restores the session from the cookie via /auth/me", async () => {
    stubFetch({ "/auth/me": { body: { user: makeUser({ full_name: "Dr. M. Santos" }) } } });

    renderWithProviders(<SessionProbe />);

    expect(await screen.findByText("Dr. M. Santos")).toBeInTheDocument();
  });

  it("treats a 401 as 'nobody is signed in' rather than an error", async () => {
    stubFetch({
      "/auth/me": {
        status: 401,
        body: errorBody("NOT_AUTHENTICATED", "Please sign in to continue."),
      },
    });

    renderWithProviders(<SessionProbe />);

    expect(await screen.findByText("signed out")).toBeInTheDocument();
  });

  it("asks the server once, without retrying a 401", async () => {
    const fetchMock = stubFetch({
      "/auth/me": {
        status: 401,
        body: errorBody("NOT_AUTHENTICATED", "Please sign in to continue."),
      },
    });

    renderWithProviders(<SessionProbe />);

    await screen.findByText("signed out");
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
  });

  it("reports loading before the probe settles, so guards do not bounce early", () => {
    stubFetch({ "/auth/me": { body: { user: makeUser() } } });

    renderWithProviders(<SessionProbe />);

    expect(screen.getByText("loading")).toBeInTheDocument();
  });
});
