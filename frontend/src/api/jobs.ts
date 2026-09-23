import apiClient from './client';
import type { JobSchedule, JobsStatusResponse, UpdateScheduleResponse } from '../types';

export const jobsApi = {
  async getStatus(): Promise<JobsStatusResponse> {
    const response = await apiClient.get<JobsStatusResponse>('/jobs/status');
    return response.data;
  },

  async updateSchedule(times: JobSchedule[]): Promise<UpdateScheduleResponse> {
    const response = await apiClient.put<UpdateScheduleResponse>('/jobs/schedule', { times });
    return response.data;
  },
};
