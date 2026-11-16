import { useState } from 'react';
import { Card, Select, Space, Table, Tag, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { useJobRuns } from '../../hooks';
import type { JobRun } from '../../types';

const { Text, Paragraph } = Typography;

// Run History (issue #246): the recent SyncLog rows — every scheduled
// rebuild, library sync, cleanup and manual run, with how each one ended.

const JOB_TYPE_LABELS: Record<string, string> = {
  playlist_update: 'Playlist rebuild',
  library_sync: 'Library sync',
  cleanup: 'Played-episode cleanup',
  manual_playlist_update: 'Manual run',
};

const FAILURE_LABELS: Record<string, string> = {
  interrupted: 'Interrupted by a restart',
  credentials_unreadable: 'Sign in again',
  rate_limit: 'Spotify rate limit',
  token_expired: 'Spotify sign-in expired',
  playlist_write_failed: 'Spotify refused a write',
  partial: 'Incomplete data',
  unknown: 'Unknown error',
  not_found: 'Playlist gone',
};

const STATUS_COLORS: Record<JobRun['status'], string> = {
  success: 'success',
  failed: 'error',
  running: 'processing',
};

function duration(run: JobRun): string {
  if (!run.started_at || !run.completed_at) return '—';
  const seconds = dayjs(run.completed_at).diff(dayjs(run.started_at), 'second');
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

const columns: ColumnsType<JobRun> = [
  {
    title: 'Status',
    dataIndex: 'status',
    key: 'status',
    render: (status: JobRun['status']) => <Tag color={STATUS_COLORS[status]}>{status}</Tag>,
  },
  {
    title: 'Job',
    dataIndex: 'job_type',
    key: 'job_type',
    render: (jobType: string) => JOB_TYPE_LABELS[jobType] ?? jobType,
  },
  {
    title: 'Started',
    dataIndex: 'started_at',
    key: 'started_at',
    render: (startedAt: string | null) =>
      startedAt ? (
        <Tooltip title={dayjs(startedAt).format('YYYY-MM-DD HH:mm:ss')}>
          {dayjs(startedAt).fromNow()}
        </Tooltip>
      ) : (
        '—'
      ),
  },
  {
    title: 'Duration',
    key: 'duration',
    responsive: ['md'] as const,
    render: (_, run) => duration(run),
  },
  {
    title: 'Playlists',
    key: 'playlists',
    responsive: ['md'] as const,
    render: (_, run) =>
      run.playlists_attempted ? (
        <Text type={run.playlists_failed ? 'danger' : undefined}>
          {run.playlists_failed ?? 0} of {run.playlists_attempted} failed
        </Text>
      ) : (
        '—'
      ),
  },
  {
    title: 'Failure',
    dataIndex: 'failure_code',
    key: 'failure_code',
    render: (code: string | null) =>
      code ? (
        <Tooltip title={code}>
          <Text type="secondary">{FAILURE_LABELS[code] ?? code}</Text>
        </Tooltip>
      ) : (
        '—'
      ),
  },
];

function RunDetails({ run }: { run: JobRun }) {
  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      {run.message && <Text>{run.message}</Text>}
      {run.results && run.results.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 20 }}>
          {run.results.map((r) => (
            <li key={r.playlist_id}>
              <Text strong>{r.playlist_name}</Text>{' '}
              {r.skipped
                ? 'skipped (disabled)'
                : r.partial
                  ? `updated with warnings: ${r.error ?? ''}`
                  : r.success
                    ? `${r.episode_count} episodes`
                    : (r.error ?? 'failed')}
            </li>
          ))}
        </ul>
      )}
      {run.details && (
        <Paragraph
          style={{ marginBottom: 0, whiteSpace: 'pre-wrap', fontSize: 12 }}
          type="secondary"
        >
          {run.details}
        </Paragraph>
      )}
    </Space>
  );
}

export function RunHistoryCard({ style }: { style?: React.CSSProperties }) {
  const [jobType, setJobType] = useState<string | undefined>(undefined);
  const { data: runs, isLoading } = useJobRuns(jobType);

  return (
    <Card
      title="Run History"
      style={style}
      extra={
        <Select
          size="small"
          style={{ width: 200 }}
          value={jobType ?? 'all'}
          onChange={(value) => setJobType(value === 'all' ? undefined : value)}
          options={[
            { value: 'all', label: 'All jobs' },
            ...Object.entries(JOB_TYPE_LABELS).map(([value, label]) => ({ value, label })),
          ]}
          aria-label="Filter runs by job"
        />
      }
    >
      <Table<JobRun>
        dataSource={runs ?? []}
        columns={columns}
        rowKey="id"
        loading={isLoading}
        pagination={false}
        size="small"
        expandable={{
          expandedRowRender: (run) => <RunDetails run={run} />,
          rowExpandable: (run) => Boolean(run.details || run.message || run.results?.length),
        }}
        locale={{ emptyText: 'No runs recorded yet' }}
      />
    </Card>
  );
}
