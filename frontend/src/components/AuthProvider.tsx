/**
 * Holds the session for the app (FR-57).
 *
 * `GET /auth/me` is the source of truth, so a reload restores the session from
 * the cookie rather than from anything the client stored. A 401 is a normal
 * answer — "nobody is signed in" — not an error to retry or surface.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import {
  changePassword as changePasswordRequest,
  fetchCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
  type AuthenticatedUser,
} from "../api/auth";
import { setSessionEndedHandler } from "../api/client";
import { ApiErrorCode, isApiError } from "../api/errors";
import { AuthContext, type AuthContextValue } from "../hooks/useAuth";

const CURRENT_USER_KEY = ["auth", "me"] as const;

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const { data, isPending } = useQuery<AuthenticatedUser | null>({
    queryKey: CURRENT_USER_KEY,
    queryFn: async () => {
      try {
        return await fetchCurrentUser();
      } catch (error) {
        if (isApiError(error) && error.code === ApiErrorCode.notAuthenticated) {
          return null;
        }
        throw error;
      }
    },
    retry: false,
    // The cookie slides on every request, so the server stays authoritative;
    // re-probing on every window focus would add nothing.
    refetchOnWindowFocus: false,
  });

  const forgetSession = useCallback(() => {
    queryClient.setQueryData(CURRENT_USER_KEY, null);
    // Everything else in the cache was fetched as that user.
    void queryClient.removeQueries({ predicate: (query) => query.queryKey !== CURRENT_USER_KEY });
  }, [queryClient]);

  // A session that expires mid-visit should land on the login screen rather
  // than leave a half-broken page behind.
  useEffect(() => {
    setSessionEndedHandler(() => {
      forgetSession();
      void navigate("/login", { replace: true });
    });
    return () => setSessionEndedHandler(null);
  }, [forgetSession, navigate]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user: data ?? null,
      isLoading: isPending,
      login: async (email, password) => {
        const user = await loginRequest(email, password);
        queryClient.setQueryData(CURRENT_USER_KEY, user);
        return user;
      },
      logout: async () => {
        try {
          await logoutRequest();
        } finally {
          // Whatever the server said, this browser is done with the session.
          forgetSession();
        }
      },
      changePassword: async (currentPassword, newPassword) => {
        const user = await changePasswordRequest(currentPassword, newPassword);
        queryClient.setQueryData(CURRENT_USER_KEY, user);
        return user;
      },
    }),
    [data, isPending, queryClient, forgetSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
