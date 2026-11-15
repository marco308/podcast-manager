import apiClient from './client';
import type {
  JobRun,
  JobRunListResponse,
  JobSchedule,
  JobsStatusResponse,
  UpdateScheduleResponse,
} from '../types';

// How often an async manual run is polled, and for how long. A run that is
// still going after the cap keeps going on the server; Run History in
// Settings shows how it ended.
const RUN_POLL_INTERVAL_MS = 2000;
const RUN_POLL_MAX_MS = 30 * 60 * 1000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export const jobsApi = {
  async getStatus(): Promise<JobsStatusResponse> {
    const response = await apiClient.get<JobsStatusResponse>('/jobs/status');
    return response.data;
  },

  async updateSchedule(times: JobSchedule[]): Promise<UpdateScheduleResponse> {
    const response = await apiClient.put<UpdateScheduleResponse>('/jobs/schedule', { times });
    return response.data;
  },

  // Recent job runs, newest first (issue #246).
  async listRuns(params: { jobType?: string; limit?: number } = {}): Promise<JobRun[]> {
    const response = await apiClient.get<JobRunListResponse>('/jobs/runs', {
      params: { job_type: params.jobType || undefined, limit: params.limit },
    });
    return response.data.runs;
  },

  async getRun(id: number): Promise<JobRun> {
    const response = await apiClient.get<JobRun>(`/jobs/runs/${id}`);
    return response.data;
  },

  // Poll an async manual run until it has finished (issue #242).
  async waitForRun(id: number): Promise<JobRun> {
    const deadline = Date.now() + RUN_POLL_MAX_MS;
    for (;;) {
      const run = await jobsApi.getRun(id);
      if (run.status !== 'running') return run;
      if (Date.now() > deadline) {
        throw new Error(
          'The update is still running. Check Run History in Settings for how it ends.'
        );
      }
      await sleep(RUN_POLL_INTERVAL_MS);
    }
  },
};
