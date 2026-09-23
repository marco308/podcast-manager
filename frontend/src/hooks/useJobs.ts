import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { jobsApi } from '../api';
import type { JobSchedule } from '../types';

export const jobKeys = {
  all: ['jobs'] as const,
  status: () => [...jobKeys.all, 'status'] as const,
};

export function useJobs() {
  return useQuery({
    queryKey: jobKeys.status(),
    queryFn: jobsApi.getStatus,
    refetchInterval: 60000, // Refresh every minute to keep next_run accurate
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
