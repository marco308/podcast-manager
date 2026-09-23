import { createContext, useContext, useCallback, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import { authApi } from '../api';
import { clearCsrfToken } from '../api/client';
import type { User } from '../types';

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isError: boolean;
  login: () => void;
  logout: () => Promise<void>;
  deleteAccount: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

function isUnauthorizedError(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 401;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();

  // Check authentication status via cookie-based session. checkStatus only
  // resolves false on a confirmed 401; transient failures (network blip, 5xx)
  // reject and are retried so they don't bounce a valid session to /login.
  const {
    data: isAuthenticated,
    isLoading: isStatusLoading,
    isError: isStatusError,
  } = useQuery({
    queryKey: ['auth', 'status'],
    queryFn: authApi.checkStatus,
    retry: 2,
    staleTime: 30 * 1000, // 30 seconds
  });

  // Query current user - only if authenticated. A confirmed 401 is not
  // retried; transient failures are retried a couple of times.
  const {
    data: user,
    isLoading: isUserLoading,
    error: userError,
  } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: authApi.getMe,
    retry: (failureCount, error) => !isUnauthorizedError(error) && failureCount < 2,
    staleTime: 5 * 60 * 1000, // 5 minutes
    enabled: isAuthenticated === true,
  });

  // Initialized once the first status check has settled. React Query keeps
  // isStatusLoading true only until the initial fetch resolves (refetches use
  // isFetching instead), so this latches true and stays true.
  const isInitialized = !isStatusLoading;

  // Login redirects to Spotify OAuth
  const login = useCallback(() => {
    window.location.href = authApi.getLoginUrl();
  }, []);

  // Logout clears session and query cache
  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // Ignore logout errors
    }
    clearCsrfToken();
    queryClient.clear();
    window.location.href = '/login';
  }, [queryClient]);

  // Unlike logout, errors propagate: a failed delete must not look like one
  // that worked. The server clears the cookies on success.
  const deleteAccount = useCallback(async () => {
    await authApi.deleteAccount();
    clearCsrfToken();
    queryClient.clear();
    window.location.href = '/login';
  }, [queryClient]);

  const value: AuthContextType = {
    user: user ?? null,
    isLoading: !isInitialized || (isAuthenticated === true && isUserLoading),
    // Only a confirmed 401 from /auth/me flips this while the status check
    // says the session is valid — a transient failure keeps the session.
    isAuthenticated: isAuthenticated === true && !isUnauthorizedError(userError),
    // The status check itself failed (after retries): auth state is unknown,
    // so callers should show a neutral error state instead of redirecting.
    isError: isStatusError,
    login,
    logout,
    deleteAccount,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components -- hook co-located with its provider; only affects dev fast-refresh
export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
