import dayjs from 'dayjs';

/**
 * Format a date string to a readable format
 */
export function formatDate(date: string | null | undefined): string {
  if (!date) return '—';
  return dayjs(date).format('MMM D, YYYY');
}

/**
 * Format a date string to relative time (e.g., "2 hours ago")
 */
export function formatRelativeTime(date: string | null | undefined): string {
  if (!date) return 'Never';
  return dayjs(date).fromNow();
}

/**
 * Format a number with commas (e.g., 1,234,567)
 */
export function formatNumber(num: number): string {
  return num.toLocaleString();
}

/**
 * Truncate a string to a maximum length
 */
export function truncate(str: string, maxLength: number): string {
  if (str.length <= maxLength) return str;
  return str.slice(0, maxLength - 3) + '...';
}

/**
 * Capitalize the first letter of a string
 */
export function capitalize(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1);
}
