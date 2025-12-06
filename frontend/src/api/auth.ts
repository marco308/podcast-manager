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

  // Logout current user
  async logout(): Promise<void> {
    await apiClient.post('/auth/logout');
  },
};
