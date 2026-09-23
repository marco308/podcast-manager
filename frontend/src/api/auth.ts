import axios from 'axios';
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
      const response = await apiClient.get<{ authenticated: boolean }>('/auth/status');
      return response.data.authenticated;
    } catch (error) {
      // A confirmed 401 means "not authenticated"; anything else (network
      // blip, 5xx) is transient — rethrow so React Query can retry instead
      // of bouncing a valid session to the login page.
      if (axios.isAxiosError(error) && error.response?.status === 401) {
        return false;
      }
      throw error;
    }
  },

  // Delete the account and everything the server stores for it (issue #266)
  async deleteAccount(): Promise<void> {
    await apiClient.delete('/auth/me');
  },

  // Logout current user
  async logout(): Promise<void> {
    await apiClient.post('/auth/logout');
  },
};
