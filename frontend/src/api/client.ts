import axios, { type AxiosError, type AxiosInstance } from 'axios';
import type { ApiError } from '../types';

// CSRF token storage (read from cookie)
let csrfToken: string | null = null;

// Get CSRF token from cookie
function getCsrfTokenFromCookie(): string | null {
  const match = document.cookie.match(/(?:^|; )csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

// Get CSRF token (from cookie or cached)
export function getCsrfToken(): string | null {
  if (!csrfToken) {
    csrfToken = getCsrfTokenFromCookie();
  }
  return csrfToken;
}

// Clear CSRF token (called on logout)
export function clearCsrfToken(): void {
  csrfToken = null;
}

// Create axios instance with base configuration
const apiClient: AxiosInstance = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
  // CRITICAL: Include cookies in requests
  withCredentials: true,
});

// Request interceptor to add CSRF token for state-changing requests
apiClient.interceptors.request.use((config) => {
  // Add CSRF token for POST, PUT, PATCH, DELETE requests
  const method = config.method?.toUpperCase();
  if (method && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    const token = getCsrfToken();
    if (token) {
      config.headers['X-CSRF-Token'] = token;
    }
  }
  return config;
});

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiError>) => {
    // Handle 401 Unauthorized - redirect to login
    if (error.response?.status === 401) {
      clearCsrfToken();
      // Only redirect if not already on login page
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    // Handle 403 Forbidden (CSRF failure) - clear cached token, refresh, and retry once
    if (
      error.response?.status === 403 &&
      error.response?.data?.detail?.includes('CSRF') &&
      error.config &&
      !(error.config as unknown as Record<string, unknown>)._csrfRetry
    ) {
      // Clear cached token and read fresh from cookie
      csrfToken = null;
      let freshToken = getCsrfTokenFromCookie();
      if (!freshToken) {
        // Cookie is gone (expired or cleared) — recover via the backend's
        // fallback endpoint, which returns the token for the current session.
        // Without this a lost cookie would permanently 403 all mutations.
        try {
          const { data } = await apiClient.get<{ csrf_token: string }>('/auth/csrf-token');
          freshToken = data.csrf_token;
        } catch {
          // Recovery failed (e.g. session gone too) — fall through and reject
        }
      }
      if (freshToken && error.config) {
        csrfToken = freshToken;
        error.config.headers['X-CSRF-Token'] = freshToken;
        (error.config as unknown as Record<string, unknown>)._csrfRetry = true;
        return apiClient.request(error.config);
      }
    }
    return Promise.reject(error);
  }
);

export default apiClient;

// Helper to extract error message
export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    return error.response?.data?.detail || error.message || 'An error occurred';
  }
  if (error instanceof Error) {
    return error.message;
  }
  return 'An unknown error occurred';
}
