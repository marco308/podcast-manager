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
import {
  LogoutOutlined,
  ClockCircleOutlined,
  CloseOutlined,
  DeleteOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useAuth, useTheme, useJobs, useUpdateJobSchedule, useHealth } from '../hooks';
import { getErrorMessage } from '../api';
import type { ThemePreference } from '../context';
import type { Job, JobSchedule } from '../types';

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

// Servers from before multiple run times only send `schedule`.
function scheduleTimes(job: Job): JobSchedule[] {
  return job.schedule_times ?? (job.schedule ? [job.schedule] : []);
}

function formatTime({ hour, minute }: JobSchedule): string {
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

// The run times are wall-clock times in the server's TIMEZONE, not the
// browser's, so they are labelled with it and never converted. Servers from
// before the setting don't send it.
function formatTimes(job: Job): string {
  const times = scheduleTimes(job).map(formatTime).join(', ');
  return job.schedule_timezone ? `${times} (${job.schedule_timezone})` : times;
}

// The TimePicker needs a dayjs value, but only its hour and minute are read
// back. Pin the date so a daylight-saving jump in the *browser's* zone can't
// shift the hour (dayjs().hour(1) on a spring-forward day comes out as 02:00).
const PICKER_DATE = '2000-01-01';

function pickerTime({ hour, minute }: JobSchedule): dayjs.Dayjs {
  return dayjs(PICKER_DATE).hour(hour).minute(minute);
}

// The hint under the switch describes whichever option is selected.
const THEME_OPTIONS: { value: ThemePreference; label: string; hint: string }[] = [
  { value: 'light', label: 'Light', hint: 'Always use the light theme' },
  { value: 'dark', label: 'Dark', hint: 'Always use the dark theme' },
  { value: 'system', label: 'System', hint: "Follows your device's appearance setting" },
];

export function Settings() {
  const { message, modal } = App.useApp();
  const { user, logout, deleteAccount } = useAuth();
  const { themePreference, setThemePreference } = useTheme();
  const { data: jobsData, isLoading: jobsLoading } = useJobs();
  const { data: health } = useHealth();
  const updateSchedule = useUpdateJobSchedule();
  // Unsaved edits to the run times; null while showing what the server has.
  const [editingTimes, setEditingTimes] = useState<dayjs.Dayjs[] | null>(null);

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
            This deletes your account and playlists from this server and signs you out. Your podcast
            library is deleted too, unless another account on this server still uses it. It
            can&apos;t be undone.
          </Paragraph>
          <Paragraph style={{ marginBottom: 0 }}>
            Playlists already on Spotify stay there. To remove this app&apos;s access to Spotify, go
            to your Spotify account&apos;s Apps page.
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
    if (!editingTimes) return;
    updateSchedule.mutate(
      editingTimes.map((time) => ({ hour: time.hour(), minute: time.minute() })),
      {
        onSuccess: (data) => {
          message.success(data.message);
          setEditingTimes(null);
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
          {record.type === 'cron' && scheduleTimes(record).length > 0 && (
            <Text type="secondary">{formatTimes(record)}</Text>
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

        const times = editingTimes ?? scheduleTimes(record).map(pickerTime);
        const maxTimes = record.max_schedule_times ?? 1;

        const setTimeAt = (index: number, time: dayjs.Dayjs) =>
          setEditingTimes(times.map((t, i) => (i === index ? time : t)));
        const removeTimeAt = (index: number) =>
          setEditingTimes(times.filter((_, i) => i !== index));
        // Start a new run eight hours after the last one, a sensible spread
        // for up to three a day; the user adjusts it before saving.
        const addTime = () =>
          setEditingTimes([
            ...times,
            (times[times.length - 1] ?? pickerTime({ hour: 0, minute: 0 })).add(8, 'hour'),
          ]);

        return (
          <Space wrap>
            {times.map((time, index) => (
              <Space.Compact key={index}>
                <TimePicker
                  value={time}
                  format="HH:mm"
                  onChange={(value) => value && setTimeAt(index, value)}
                  suffixIcon={<ClockCircleOutlined />}
                  allowClear={false}
                  style={{ width: 100 }}
                />
                {times.length > 1 && (
                  <Tooltip title="Remove this run time">
                    <Button icon={<CloseOutlined />} onClick={() => removeTimeAt(index)} />
                  </Tooltip>
                )}
              </Space.Compact>
            ))}
            {record.schedule_timezone && (
              <Tooltip title="Run times are in the server's time zone (its TIMEZONE setting), not your device's">
                <Text type="secondary">{record.schedule_timezone}</Text>
              </Tooltip>
            )}
            {times.length < maxTimes && (
              <Tooltip title={`Run up to ${maxTimes} times a day`}>
                <Button icon={<PlusOutlined />} onClick={addTime}>
                  Add time
                </Button>
              </Tooltip>
            )}
            <Button
              type="primary"
              size="small"
              loading={updateSchedule.isPending}
              disabled={!editingTimes}
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
                options={THEME_OPTIONS.map(({ value, label }) => ({ value, label }))}
              />
            </div>
            <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {THEME_OPTIONS.find((option) => option.value === themePreference)?.hint}
              </Text>
            </Paragraph>
          </div>
        </Space>
      </Card>

      <Card title="Scheduled Jobs" style={{ marginBottom: 24 }}>
        <Paragraph style={{ marginBottom: 16 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Each library sync &amp; playlist update refreshes your Spotify library first — new
            subscriptions appear, and shows you have unfollowed are flagged and stop contributing
            episodes — then rebuilds every enabled playlist. It runs once a day by default. You can
            add up to three run times so episodes released during the day turn up sooner; each run
            replaces the playlist, so pick times when you aren&apos;t usually listening.
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
