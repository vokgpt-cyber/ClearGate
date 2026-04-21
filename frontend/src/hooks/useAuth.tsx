'use client';

/**
 * AuthContext / AuthProvider — authenticated-user state for the pilot.
 *
 * Sprint B.4: we don't keep JWTs or tokens in JS; the backend drops an
 * HttpOnly `cg_session` cookie on login and we just remember "who is
 * logged in" in React state. On mount we call `GET /api/auth/me` to
 * recover from a page reload — if the cookie is still valid the user
 * is seamlessly restored; if it expired the fetch returns 401 and we
 * fall through to the login page.
 *
 * We intentionally return a *concrete* `user: AuthUser | null` rather
 * than `undefined` once loading is finished, so consumers (the protected
 * route gate, the Header pill) can branch with a single boolean check.
 */

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  useEffect,
} from 'react';
import type { ReactNode } from 'react';
import {
  getCurrentUser,
  login as apiLogin,
  logout as apiLogout,
  type AuthUser,
} from '@/lib/api';

interface AuthContextValue {
  /** `null` once the initial check has run and nobody is logged in. */
  user: AuthUser | null;
  /** `true` only during the first /api/auth/me probe after mount. */
  isLoading: boolean;
  /** Attempt login; throws on 401 so the form can surface the message. */
  login: (username: string, password: string) => Promise<void>;
  /** Clear the server cookie and forget the local user. Best effort. */
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue>({
  user: null,
  isLoading: true,
  login: async () => {
    throw new Error('AuthProvider missing');
  },
  logout: async () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  // Start as loading so the protected-route gate can show a spinner
  // instead of flashing the login screen during the initial /me probe.
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Resolve the current user from the cookie exactly once on mount.
    // If the network is unreachable or the backend is down we still
    // fall through to "not logged in" — the login form will surface
    // a clearer error on the next submit attempt.
    let cancelled = false;
    getCurrentUser()
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    // Let API errors propagate — the login form needs the message.
    const u = await apiLogin(username, password);
    setUser(u);
  }, []);

  const logout = useCallback(async () => {
    // Clear local state FIRST so the UI immediately drops back to the
    // login screen even if the network call is slow. The cookie is
    // HttpOnly so we can't delete it from JS; the backend does that.
    setUser(null);
    try {
      await apiLogout();
    } catch {
      // Ignore — we've already forgotten the user locally.
    }
  }, []);

  const value = useMemo(
    () => ({ user, isLoading, login, logout }),
    [user, isLoading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
