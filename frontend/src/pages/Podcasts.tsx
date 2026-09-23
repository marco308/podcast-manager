import { useState } from 'react';
import { Typography, Button, Space, Alert, Switch } from 'antd';
import { SyncOutlined } from '@ant-design/icons';
import { usePodcasts, useSyncPodcastsWithFeedback } from '../hooks';
import { PodcastTable, LoadingSpinner } from '../components';

const { Title, Text } = Typography;

export function Podcasts() {
  // Archived podcasts (hidden, still followed on Spotify) only show on request
  const [showArchived, setShowArchived] = useState(false);
  const {
    data: podcasts,
    isLoading,
    isPlaceholderData,
    error,
  } = usePodcasts({ includeArchived: showArchived });
  const { sync: handleSync, isPending: syncPending } = useSyncPodcastsWithFeedback();

  // Only the first load replaces the page with a spinner; switching "Show
  // archived" keeps the table mounted with the previous list meanwhile.
  if (isLoading) {
    return <LoadingSpinner tip="Loading podcasts..." />;
  }

  if (error) {
    return (
      <Alert
        type="error"
        message="Failed to load podcasts"
        description="Please try refreshing the page or syncing your podcasts again."
        showIcon
      />
    );
  }

  const noPodcasts = !podcasts || podcasts.length === 0;

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 24,
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <Title level={4} style={{ marginBottom: 4 }}>
            Podcasts
          </Title>
          <Text type="secondary">Manage your podcast subscriptions and playlist assignments</Text>
        </div>
        <Space wrap>
          <Space size={8}>
            <Switch
              id="show-archived"
              checked={showArchived}
              onChange={setShowArchived}
              loading={isPlaceholderData}
              size="small"
              aria-labelledby="show-archived-label"
            />
            <label htmlFor="show-archived" id="show-archived-label">
              <Text>Show archived</Text>
            </label>
          </Space>
          <Button
            type="primary"
            icon={<SyncOutlined spin={syncPending} />}
            onClick={handleSync}
            loading={syncPending}
          >
            Sync from Spotify
          </Button>
        </Space>
      </div>

      {noPodcasts ? (
        <Alert
          message="No podcasts found"
          description={
            <Space direction="vertical">
              <Text>
                You don't have any podcasts synced yet. Click the button above to sync your podcast
                subscriptions from Spotify.
              </Text>
              <Button
                type="primary"
                icon={<SyncOutlined spin={syncPending} />}
                onClick={handleSync}
                loading={syncPending}
              >
                Sync Now
              </Button>
            </Space>
          }
          type="info"
          showIcon
        />
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <PodcastTable podcasts={podcasts} />
        </div>
      )}
    </div>
  );
}
