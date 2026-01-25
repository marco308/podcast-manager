import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { authApi } from '../api';
import { clearCsrfToken } from '../api/client';
import type { User } from '../types';

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: () => void;
  logout: () => Promise<void>;
  refetch: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [isInitialized, setIsInitialized] = useState(false);

  // Check authentication status via cookie-based session
  const { data: isAuthenticated, isLoading: isStatusLoading } = useQuery({
    queryKey: ['auth', 'status'],
    queryFn: authApi.checkStatus,
    retry: false,
    staleTime: 30 * 1000, // 30 seconds
  });

  // Query current user - only if authenticated
  const {
    data: user,
    isLoading: isUserLoading,
    refetch,
    isError,
  } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: authApi.getMe,
    retry: false,
    staleTime: 5 * 60 * 1000, // 5 minutes
    enabled: isAuthenticated === true,
  });

  // Mark as initialized after first status check
  useEffect(() => {
    if (!isStatusLoading) {
      setIsInitialized(true);
    }
  }, [isStatusLoading]);

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

  const value: AuthContextType = {
    user: user ?? null,
    isLoading: !isInitialized || (isAuthenticated === true && isUserLoading),
    isAuthenticated: isAuthenticated === true && !!user && !isError,
    login,
    logout,
    refetch,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
