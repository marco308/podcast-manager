import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { jobsApi } from '../api';
import type { JobSchedule } from '../types';

export const jobKeys = {
  all: ['jobs'] as const,
  status: () => [...jobKeys.all, 'status'] as const,
  runs: (jobType?: string) => [...jobKeys.all, 'runs', jobType ?? 'all'] as const,
};

export function useJobs() {
  return useQuery({
    queryKey: jobKeys.status(),
    queryFn: jobsApi.getStatus,
    refetchInterval: 60000, // Refresh every minute to keep next_run accurate
  });
}

// Recent job runs, newest first (issue #246).
export function useJobRuns(jobType?: string, limit = 25) {
  return useQuery({
    queryKey: [...jobKeys.runs(jobType), limit],
    queryFn: () => jobsApi.listRuns({ jobType, limit }),
    refetchInterval: 60000,
  });
}

export function useUpdateJobSchedule() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (times: JobSchedule[]) => jobsApi.updateSchedule(times),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: jobKeys.status() });
    },
  });
}
