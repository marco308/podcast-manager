import { useState } from 'react';
import {
  App,
  Typography,
  Card,
  Descriptions,
  Button,
  Space,
  Divider,
  Tag,
  Segmented,
  TimePicker,
  Spin,
  Table,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { LogoutOutlined, ClockCircleOutlined, DeleteOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useAuth, useTheme, useJobs, useUpdateJobSchedule, useHealth } from '../hooks';
import { getErrorMessage } from '../api';
import type { ThemePreference } from '../context';
import type { Job } from '../types';

dayjs.extend(relativeTime);

const { Title, Text, Paragraph } = Typography;

// A job's run can span more than one SyncLog-backed step — the daily run syncs
// the library and then rebuilds — and the table shows one line per job. Name
// the step that failed so a failed sync under a successful rebuild is legible
// rather than just a red tag (issue #240).
const STEP_LABELS: Record<string, string> = {
  library_sync: 'library sync',
  playlist_update: 'playlist rebuild',
  cleanup: 'played-episode cleanup',
};

function failedStepsLabel(job: Job): string {
  const steps = job.last_run_failed_steps ?? [];
  if (steps.length === 0) return 'The last run failed';
  const names = steps.map((step) => STEP_LABELS[step] ?? step);
  return `The last run failed: ${names.join(', ')}`;
}

export function Settings() {
  const { message, modal } = App.useApp();
  const { user, logout, deleteAccount } = useAuth();
  const { themePreference, setThemePreference } = useTheme();
  const { data: jobsData, isLoading: jobsLoading } = useJobs();
  const { data: health } = useHealth();
  const updateSchedule = useUpdateJobSchedule();
  const [editingTime, setEditingTime] = useState<dayjs.Dayjs | null>(null);

  const handleLogout = () => {
    // logout() swallows its own errors and always redirects to /login
    void logout();
  };

  const handleDeleteAccount = () => {
    modal.confirm({
      title: 'Delete your account?',
      content: (
        <>
          <Paragraph>
            This deletes your account, playlists and podcast library from this server and signs you out. It
            can&apos;t be undone.
          </Paragraph>
          <Paragraph style={{ marginBottom: 0 }}>
            Playlists already on Spotify stay there. To remove this app&apos;s access to Spotify, go to your
            Spotify account&apos;s Apps page.
          </Paragraph>
        </>
      ),
      okText: 'Delete account',
      okButtonProps: { danger: true },
      // Returning the promise keeps the dialog open with a spinner until the
      // delete finishes; on failure it closes and the error is shown.
      onOk: () =>
        deleteAccount().catch((error: unknown) => {
          message.error(getErrorMessage(error));
        }),
    });
  };

  const handleScheduleSave = () => {
    const time = editingTime;
    if (!time) return;
    updateSchedule.mutate(
      { hour: time.hour(), minute: time.minute() },
      {
        onSuccess: (data) => {
          message.success(data.message);
          setEditingTime(null);
        },
        onError: () => {
          message.error('Failed to update schedule');
        },
      }
    );
  };

  const jobColumns: ColumnsType<Job> = [
    {
      title: 'Job',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: 'Status',
      key: 'status',
      render: (_, record) => (
        <Space>
          <Tag color={record.type === 'cron' ? 'blue' : 'purple'}>{record.type}</Tag>
          {record.type === 'interval' && record.interval_minutes && (
            <Text type="secondary">every {record.interval_minutes} min</Text>
          )}
          {record.type === 'cron' && record.schedule && (
            <Text type="secondary">
              {String(record.schedule.hour).padStart(2, '0')}:
              {String(record.schedule.minute).padStart(2, '0')}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: 'Next Run',
      dataIndex: 'next_run',
      key: 'next_run',
      render: (next_run: string | null) =>
        next_run ? (
          <Tooltip title={dayjs(next_run).format('YYYY-MM-DD HH:mm:ss')}>
            {dayjs(next_run).fromNow()}
          </Tooltip>
        ) : (
          '—'
        ),
    },
    {
      title: 'Last Run',
      dataIndex: 'last_run',
      key: 'last_run',
      render: (last_run: string | null, record) =>
        last_run ? (
          <Space size={4}>
            <Tooltip title={dayjs(last_run).format('YYYY-MM-DD HH:mm:ss')}>
              {dayjs(last_run).fromNow()}
            </Tooltip>
            {record.last_run_status === 'failed' && (
              <Tooltip title={failedStepsLabel(record)}>
                <Tag color="red">failed</Tag>
              </Tooltip>
            )}
            {record.last_run_status === 'running' && <Tag color="processing">running</Tag>}
          </Space>
        ) : (
          '—'
        ),
    },
    {
      title: 'Schedule',
      key: 'schedule',
      render: (_, record) => {
        if (!record.is_configurable) {
          if (record.type === 'interval' && record.interval_minutes) {
            return <Text type="secondary">Every {record.interval_minutes} minutes</Text>;
          }
          return <Text type="secondary">Not configurable</Text>;
        }

        const currentTime =
          editingTime ??
          (record.schedule
            ? dayjs().hour(record.schedule.hour).minute(record.schedule.minute)
            : null);

        return (
          <Space>
            <TimePicker
              value={currentTime}
              format="HH:mm"
              onChange={(time) => setEditingTime(time)}
              suffixIcon={<ClockCircleOutlined />}
              allowClear={false}
              style={{ width: 100 }}
            />
            <Button
              type="primary"
              size="small"
              loading={updateSchedule.isPending}
              disabled={!editingTime}
              onClick={() => handleScheduleSave()}
            >
              Save
            </Button>
          </Space>
        );
      },
    },
  ];

  return (
    <div>
      <Title level={4}>Settings</Title>

      <Card title="Account" style={{ marginBottom: 24 }}>
        <Descriptions column={1}>
          <Descriptions.Item label="Spotify Username">{user?.spotify_id || '—'}</Descriptions.Item>
          <Descriptions.Item label="Display Name">{user?.display_name || '—'}</Descriptions.Item>
          <Descriptions.Item label="Email">{user?.email || '—'}</Descriptions.Item>
          <Descriptions.Item label="Account Created">
            {user?.created_at ? dayjs(user.created_at).format('MMMM D, YYYY') : '—'}
          </Descriptions.Item>
        </Descriptions>
        <Divider />
        <Space wrap>
          <Button icon={<LogoutOutlined />} danger onClick={handleLogout}>
            Logout
          </Button>
          <Button icon={<DeleteOutlined />} danger type="text" onClick={handleDeleteAccount}>
            Delete account
          </Button>
        </Space>
      </Card>

      <Card title="Appearance" style={{ marginBottom: 24 }}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div>
            <Text strong>Theme</Text>
            <div style={{ marginTop: 8 }}>
              <Segmented
                value={themePreference}
                onChange={(value) => setThemePreference(value as ThemePreference)}
                options={[
                  { label: 'Light', value: 'light' },
                  { label: 'Dark', value: 'dark' },
                  { label: 'System', value: 'system' },
                ]}
              />
            </div>
            <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                <Text strong>System</Text> — Follows your device's appearance setting
              </Text>
            </Paragraph>
          </div>
        </Space>
      </Card>

      <Card title="Scheduled Jobs" style={{ marginBottom: 24 }}>
        <Paragraph style={{ marginBottom: 16 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            The daily run refreshes your Spotify library first — new subscriptions appear, and shows
            you have unfollowed are flagged and stop contributing episodes — then rebuilds every
            enabled playlist.
          </Text>
        </Paragraph>
        {jobsLoading ? (
          <div style={{ textAlign: 'center', padding: 24 }}>
            <Spin />
          </div>
        ) : (
          <Table<Job>
            dataSource={jobsData?.jobs ?? []}
            columns={jobColumns}
            rowKey="id"
            pagination={false}
            size="small"
          />
        )}
      </Card>

      <Card title="About">
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div>
            <Text strong style={{ fontSize: 16 }}>
              Podcast Manager
            </Text>
            {health?.version && (
              <Tag color="green" style={{ marginLeft: 8 }}>
                v{health.version}
              </Tag>
            )}
          </div>
          <Paragraph style={{ marginBottom: 0 }}>
            A powerful Spotify podcast organizer that automatically creates and maintains smart
            playlists based on your listening preferences and custom rules.
          </Paragraph>

          <Paragraph style={{ marginBottom: 0 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              Built with FastAPI, React, and Spotify Web API
            </Text>
          </Paragraph>
        </Space>
      </Card>
    </div>
  );
}
