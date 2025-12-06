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
import { getSession, clearSession } from '../api/client';
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
  
  // Check if we have a session (set in App.tsx or from previous login)
  const hasSession = !!getSession();

  // Query current user - only if we have a session
  const {
    data: user,
    isLoading,
    refetch,
    isError,
  } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: authApi.getMe,
    retry: false,
    staleTime: 5 * 60 * 1000, // 5 minutes
    enabled: hasSession, // Only fetch if we have a session
  });

  // Mark as initialized after first query or if no session
  useEffect(() => {
    if (!hasSession || !isLoading) {
      setIsInitialized(true);
    }
  }, [isLoading, hasSession]);

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
    clearSession();
    queryClient.clear();
    window.location.href = '/login';
  }, [queryClient]);

  const value: AuthContextType = {
    user: user ?? null,
    isLoading: !isInitialized || (hasSession && isLoading),
    isAuthenticated: hasSession && !!user && !isError,
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
