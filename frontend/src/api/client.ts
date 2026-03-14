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
  (error: AxiosError<ApiError>) => {
    // Handle 401 Unauthorized - redirect to login
    if (error.response?.status === 401) {
      clearCsrfToken();
      // Only redirect if not already on login page
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    // Handle 403 Forbidden (CSRF failure) - clear cached token and retry
    if (error.response?.status === 403 && error.response?.data?.detail?.includes('CSRF')) {
      // Clear cached token so next request reads fresh from cookie
      csrfToken = null;
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
