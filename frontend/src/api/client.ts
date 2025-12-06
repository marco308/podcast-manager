import axios, { type AxiosError, type AxiosInstance } from 'axios';
import type { ApiError } from '../types';

// Session storage key
const SESSION_KEY = 'podcast_manager_session';

// Get session from localStorage
export function getSession(): string | null {
  return localStorage.getItem(SESSION_KEY);
}

// Set session in localStorage
export function setSession(sessionId: string): void {
  localStorage.setItem(SESSION_KEY, sessionId);
}

// Clear session from localStorage
export function clearSession(): void {
  localStorage.removeItem(SESSION_KEY);
}

// Create axios instance with base configuration
const apiClient: AxiosInstance = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to add session parameter
apiClient.interceptors.request.use((config) => {
  const session = getSession();
  if (session) {
    // Add session as query parameter
    config.params = {
      ...config.params,
      session,
    };
  }
  return config;
});

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiError>) => {
    // Handle 401 Unauthorized - redirect to login
    if (error.response?.status === 401) {
      clearSession();
      // Only redirect if not already on login page
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
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
