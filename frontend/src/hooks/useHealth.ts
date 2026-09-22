import { useQuery } from '@tanstack/react-query';
import { healthApi } from '../api';

export const healthKeys = {
  all: ['health'] as const,
};

// App name/version come from the backend so they are defined in one place
// (backend/app/config.py) instead of drifting between frontend and backend.
export function useHealth() {
  return useQuery({
    queryKey: healthKeys.all,
    queryFn: healthApi.get,
    staleTime: Infinity,
  });
}
