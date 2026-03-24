import { useState } from 'react';
import {
  Typography,
  Card,
  Descriptions,
  Button,
  Space,
  Divider,
  message,
  Tag,
  Segmented,
  TimePicker,
  Spin,
  Table,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { LogoutOutlined, ClockCircleOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useAuth, useTheme, useJobs, useUpdateJobSchedule } from '../hooks';
import type { ThemePreference } from '../context';
import type { Job } from '../types';

dayjs.extend(relativeTime);

const { Title, Text, Paragraph } = Typography;

const APP_VERSION = '1.0.0';

export function Settings() {
  const { user, logout } = useAuth();
  const { themePreference, setThemePreference } = useTheme();
  const { data: jobsData, isLoading: jobsLoading } = useJobs();
  const updateSchedule = useUpdateJobSchedule();
  const [editingTime, setEditingTime] = useState<dayjs.Dayjs | null>(null);

  const handleLogout = async () => {
    try {
      await logout();
      message.success('Logged out successfully');
    } catch {
      message.error('Failed to logout');
    }
  };

  const handleScheduleSave = (_job: Job) => {
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
      render: (last_run: string | null) =>
        last_run ? (
          <Tooltip title={dayjs(last_run).format('YYYY-MM-DD HH:mm:ss')}>
            {dayjs(last_run).fromNow()}
          </Tooltip>
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
              onClick={() => handleScheduleSave(record)}
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
        <Button icon={<LogoutOutlined />} danger onClick={handleLogout}>
          Logout
        </Button>
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
                  { label: 'Auto', value: 'auto' },
                ]}
              />
            </div>
            <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                <Text strong>System</Text> — Follows your device's appearance setting
                <br />
                <Text strong>Auto</Text> — Uses system preference, or switches to dark mode between
                7 PM and 7 AM
              </Text>
            </Paragraph>
          </div>
        </Space>
      </Card>

      <Card title="Scheduled Jobs" style={{ marginBottom: 24 }}>
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
            <Tag color="green" style={{ marginLeft: 8 }}>
              v{APP_VERSION}
            </Tag>
          </div>
          <Paragraph style={{ marginBottom: 0 }}>
            A powerful Spotify podcast organizer that automatically creates and maintains smart
            playlists based on your listening preferences and custom rules.
          </Paragraph>

          <Divider style={{ margin: '12px 0' }}>
            <Text strong>Features</Text>
          </Divider>

          <div>
            <Text strong style={{ fontSize: 14 }}>
              🎯 Smart Categorization
            </Text>
            <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
              <Text type="secondary">
                <Text strong>Primary</Text> — Your main podcasts, all unplayed episodes
                <br />
                <Text strong>News</Text> — Time-sensitive content, only the latest episode per show
                <br />
                <Text strong>Background</Text> — Casual listening content, all unplayed episodes
                <br />
                <Text strong>Morning</Text> — Custom morning routine playlists
              </Text>
            </Paragraph>
          </div>

          <div>
            <Text strong style={{ fontSize: 14 }}>
              ⚙️ Podcast Attributes
            </Text>
            <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
              <Text type="secondary">
                <Text strong>Sequential</Text> — Story-based podcasts always play oldest-to-newest
                to maintain narrative continuity
                <br />
                <Text strong>Weekend Only</Text> — Podcasts that only appear on Fri/Sat/Sun and UK
                public holidays
              </Text>
            </Paragraph>
          </div>

          <div>
            <Text strong style={{ fontSize: 14 }}>
              📋 Flexible Playlist Ordering
            </Text>
            <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
              <Text type="secondary">
                <Text strong>Default</Text> — Category-based automatic ordering
                <br />
                <Text strong>Custom Order</Text> — Drag-and-drop podcast ordering (respects
                sequential constraint)
                <br />
                <Text strong>Chronological</Text> — Sort by release date (oldest or newest first)
                <br />
                <em>
                  Note: Sequential podcasts always maintain oldest-first ordering regardless of mode
                </em>
              </Text>
            </Paragraph>
          </div>

          <div>
            <Text strong style={{ fontSize: 14 }}>
              🔄 Automation
            </Text>
            <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
              <Text type="secondary">
                Automatic daily syncs keep your Spotify library and playlists up to date. Manually
                trigger updates anytime for instant refresh.
              </Text>
            </Paragraph>
          </div>

          <Divider style={{ margin: '12px 0' }} />

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
