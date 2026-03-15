import apiClient from './client';
import type { JobsStatusResponse, UpdateScheduleResponse } from '../types';

export const jobsApi = {
  async getStatus(): Promise<JobsStatusResponse> {
    const response = await apiClient.get<JobsStatusResponse>('/jobs/status');
    return response.data;
  },

  async updateSchedule(hour: number, minute: number): Promise<UpdateScheduleResponse> {
    const response = await apiClient.put<UpdateScheduleResponse>('/jobs/schedule', {
      hour,
      minute,
    });
    return response.data;
  },
};
