import apiClient from './client';
import type { User } from '../types';

export const authApi = {
  // Get current authenticated user
  async getMe(): Promise<User> {
    const response = await apiClient.get<User>('/auth/me');
    return response.data;
  },

  // Get login URL - redirects to Spotify OAuth
  getLoginUrl(): string {
    return '/api/auth/login';
  },

  // Check authentication status
  async checkStatus(): Promise<boolean> {
    try {
      const response = await apiClient.get<{ authenticated: boolean }>(
        '/auth/status'
      );
      return response.data.authenticated;
    } catch {
      return false;
    }
  },

  // Logout current user
  async logout(): Promise<void> {
    await apiClient.post('/auth/logout');
  },
};
