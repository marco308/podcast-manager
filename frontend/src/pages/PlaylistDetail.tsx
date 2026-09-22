import { useState } from 'react';
import {
  Alert,
  App,
  Avatar,
  Button,
  Card,
  Descriptions,
  Grid,
  InputNumber,
  List,
  Popover,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  ArrowLeftOutlined,
  CloseOutlined,
  EditOutlined,
  ExportOutlined,
  HolderOutlined,
  PlayCircleOutlined,
  SettingOutlined,
  UndoOutlined,
} from '@ant-design/icons';
import { Link, useParams } from 'react-router';
import dayjs from 'dayjs';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useQueryClient } from '@tanstack/react-query';
import {
  playlistKeys,
  usePlaylist,
  usePlaylistPodcasts,
  usePodcasts,
  useRunPlaylist,
  useAddPodcastsToPlaylist,
  useRemovePodcastFromPlaylist,
  useReorderPlaylistPodcasts,
  useUpdatePlaylistPodcast,
} from '../hooks';
import { LoadingSpinner, PlaylistFormModal } from '../components';
import { getErrorMessage } from '../api';
import {
  arrangementLabel,
  dateDirectionLabel,
  episodeLimitLabel,
  pickFromLabel,
  ruleSourceLabel,
  ruleSummary,
} from '../utils/playlistLabels';
import type { AssignmentOverrideUpdate, PickFrom, Playlist, PlaylistPodcast } from '../types';
import { EPISODE_LIMIT_MAX } from '../types';

const { Title, Text } = Typography;
const { useBreakpoint } = Grid;

// ---------------------------------------------------------------------------
// Per-row rule editor
// ---------------------------------------------------------------------------

type LimitChoice = 'inherit' | 'all' | 'latest' | 'custom';
type PickChoice = 'inherit' | PickFrom;

function limitChoiceFor(override: number | null): LimitChoice {
  if (override === null) return 'inherit';
  if (override === 0) return 'all';
  if (override === 1) return 'latest';
  return 'custom';
}

function hasOverride(podcast: PlaylistPodcast): boolean {
  return podcast.override.episode_limit !== null || podcast.override.pick_from !== null;
}

interface RuleEditorProps {
  podcast: PlaylistPodcast;
  playlist: Playlist;
  saving: boolean;
  onSave: (data: AssignmentOverrideUpdate) => Promise<boolean>;
}

function RuleEditor({ podcast, playlist, saving, onSave }: RuleEditorProps) {
  const [open, setOpen] = useState(false);
  const [limitChoice, setLimitChoice] = useState<LimitChoice>('inherit');
  const [customLimit, setCustomLimit] = useState<number | null>(null);
  const [pickChoice, setPickChoice] = useState<PickChoice>('inherit');

  const handleOpenChange = (next: boolean) => {
    if (next) {
      // Start from the row's current overrides each time the editor opens.
      const { episode_limit, pick_from } = podcast.override;
      setLimitChoice(limitChoiceFor(episode_limit));
      setCustomLimit(episode_limit !== null && episode_limit > 1 ? episode_limit : null);
      setPickChoice(pick_from ?? 'inherit');
    }
    setOpen(next);
  };

  const customInvalid = limitChoice === 'custom' && (customLimit === null || customLimit < 2);

  const handleApply = async () => {
    let episode_limit: number | null;
    if (limitChoice === 'inherit') episode_limit = null;
    else if (limitChoice === 'all') episode_limit = 0;
    else if (limitChoice === 'latest') episode_limit = 1;
    else episode_limit = customLimit ?? 2;

    const ok = await onSave({
      episode_limit,
      pick_from: pickChoice === 'inherit' ? null : pickChoice,
    });
    if (ok) setOpen(false);
  };

  const handleReset = async () => {
    const ok = await onSave({ episode_limit: null, pick_from: null });
    if (ok) setOpen(false);
  };

  // Show what "inherit" resolves to so the choice is informed.
  const inheritedLimit = episodeLimitLabel(playlist.default_episode_limit);
  const inheritedPick = podcast.is_sequential
    ? 'oldest (sequential)'
    : pickFromLabel(playlist.default_pick_from);

  const content = (
    <Space direction="vertical" size="small" style={{ width: 240 }}>
      <div>
        <Text strong style={{ fontSize: 12 }}>
          Episodes
        </Text>
        <Select<LimitChoice>
          value={limitChoice}
          onChange={setLimitChoice}
          style={{ width: '100%', marginTop: 4 }}
          size="small"
          options={[
            { value: 'inherit', label: `Inherit (${inheritedLimit})` },
            { value: 'all', label: 'All unplayed' },
            { value: 'latest', label: 'Latest only' },
            { value: 'custom', label: 'Up to…' },
          ]}
        />
        {limitChoice === 'custom' && (
          <InputNumber
            value={customLimit}
            onChange={setCustomLimit}
            min={2}
            max={EPISODE_LIMIT_MAX}
            precision={0}
            size="small"
            placeholder="Max episodes"
            status={customInvalid ? 'error' : undefined}
            style={{ width: '100%', marginTop: 4 }}
          />
        )}
      </div>
      <div>
        <Text strong style={{ fontSize: 12 }}>
          Take from
        </Text>
        <Select<PickChoice>
          value={pickChoice}
          onChange={setPickChoice}
          style={{ width: '100%', marginTop: 4 }}
          size="small"
          options={[
            { value: 'inherit', label: `Inherit (${inheritedPick})` },
            { value: 'newest', label: 'Newest' },
            { value: 'oldest', label: 'Oldest' },
          ]}
        />
      </div>
      <Space style={{ marginTop: 4 }}>
        <Button
          type="primary"
          size="small"
          onClick={handleApply}
          loading={saving}
          disabled={customInvalid}
        >
          Apply
        </Button>
        {hasOverride(podcast) && (
          <Button size="small" icon={<UndoOutlined />} onClick={handleReset} disabled={saving}>
            Reset to default
          </Button>
        )}
      </Space>
    </Space>
  );

  return (
    <Popover
      trigger="click"
      open={open}
      onOpenChange={handleOpenChange}
      title="Rule for this podcast"
      content={content}
      placement="bottomRight"
    >
      <Tooltip title="Edit rule">
        <Button size="small" type="text" icon={<SettingOutlined />} aria-label="Edit rule" />
      </Tooltip>
    </Popover>
  );
}

// ---------------------------------------------------------------------------
// Membership row
// ---------------------------------------------------------------------------

interface SortableItemProps {
  podcast: PlaylistPodcast;
  playlist: Playlist;
  onRemove: (podcastId: number) => void;
  removing: boolean;
  onUpdateRule: (podcastId: number, data: AssignmentOverrideUpdate) => Promise<boolean>;
  updating: boolean;
}

function SortableItem({
  podcast,
  playlist,
  onRemove,
  removing,
  onUpdateRule,
  updating,
}: SortableItemProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: podcast.id,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const source = ruleSourceLabel(podcast.rule);
  const overridden = hasOverride(podcast);

  return (
    <div ref={setNodeRef} style={style}>
      <List.Item style={{ padding: '12px 0' }}>
        <div
          {...attributes}
          {...listeners}
          role="button"
          tabIndex={0}
          aria-label="Drag to reorder"
          style={{
            cursor: 'grab',
            marginRight: 12,
            display: 'flex',
            alignItems: 'center',
            padding: '8px',
            touchAction: 'none',
          }}
        >
          <HolderOutlined style={{ fontSize: 20, color: '#999' }} />
        </div>
        <List.Item.Meta
          avatar={
            podcast.image_url ? (
              <Avatar src={podcast.image_url} size={36} shape="square" style={{ borderRadius: 6 }}>
                {podcast.name[0]}
              </Avatar>
            ) : undefined
          }
          title={
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <Text ellipsis style={{ maxWidth: 220 }}>
                {podcast.name}
              </Text>
              {podcast.is_sequential && (
                <Tooltip title="Sequential podcast - episodes always play oldest-first">
                  <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>
                    SEQUENTIAL
                  </Tag>
                </Tooltip>
              )}
            </div>
          }
          description={
            <Space direction="vertical" size={2}>
              {podcast.publisher && (
                <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                  {podcast.publisher}
                </Text>
              )}
              <Space size={6} wrap>
                <Tag color={overridden ? 'purple' : 'default'} style={{ margin: 0 }}>
                  {ruleSummary(podcast.rule.episode_limit, podcast.rule.pick_from)}
                </Tag>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {source}
                </Text>
              </Space>
            </Space>
          }
        />
        <Space size={4}>
          <RuleEditor
            podcast={podcast}
            playlist={playlist}
            saving={updating}
            onSave={(data) => onUpdateRule(podcast.id, data)}
          />
          {overridden && (
            <Tooltip title="Reset to playlist default">
              <Button
                size="small"
                type="text"
                icon={<UndoOutlined />}
                onClick={() => onUpdateRule(podcast.id, { episode_limit: null, pick_from: null })}
                loading={updating}
                aria-label="Reset rule to playlist default"
              />
            </Tooltip>
          )}
          <Tooltip title="Remove from playlist">
            <Button
              size="small"
              icon={<CloseOutlined />}
              onClick={() => onRemove(podcast.id)}
              loading={removing}
              danger
              type="text"
              aria-label="Remove from playlist"
            />
          </Tooltip>
        </Space>
      </List.Item>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Membership section (add, drag-to-reorder, per-row rules, remove)
// ---------------------------------------------------------------------------

function sortByPosition(podcasts: PlaylistPodcast[]): PlaylistPodcast[] {
  return [...podcasts].sort((a, b) => {
    if (a.position === null && b.position === null) {
      return a.name.localeCompare(b.name);
    }
    if (a.position === null) return 1;
    if (b.position === null) return -1;
    return a.position - b.position;
  });
}

interface MembershipSectionProps {
  playlist: Playlist;
}

function MembershipSection({ playlist }: MembershipSectionProps) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { data: playlistPodcasts, isLoading, error } = usePlaylistPodcasts(playlist.id);
  const { data: allPodcasts } = usePodcasts();
  const addPodcasts = useAddPodcastsToPlaylist();
  const removePodcast = useRemovePodcastFromPlaylist();
  const reorderPodcasts = useReorderPlaylistPodcasts();
  const updateRule = useUpdatePlaylistPodcast();
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [localPodcasts, setLocalPodcasts] = useState<PlaylistPodcast[]>([]);
  const [syncedPodcasts, setSyncedPodcasts] = useState<PlaylistPodcast[] | undefined>(undefined);

  // Sync the local (drag-reorderable) copy whenever the server data changes.
  // Adjusting state during render is React's recommended alternative to a
  // state-setting effect (the query keeps a stable reference between refetches).
  if (playlistPodcasts && playlistPodcasts !== syncedPodcasts) {
    setSyncedPodcasts(playlistPodcasts);
    setLocalPodcasts(sortByPosition(playlistPodcasts));
  }

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(TouchSensor, {
      activationConstraint: {
        delay: 200,
        tolerance: 5,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;

    if (!over || active.id === over.id) {
      return;
    }

    const oldIndex = localPodcasts.findIndex((p) => p.id === active.id);
    const newIndex = localPodcasts.findIndex((p) => p.id === over.id);

    const newOrder = arrayMove(localPodcasts, oldIndex, newIndex);
    setLocalPodcasts(newOrder);

    try {
      await reorderPodcasts.mutateAsync({
        playlistId: playlist.id,
        podcastIds: newOrder.map((p) => p.id),
      });
      message.success('Order updated');
    } catch {
      message.error('Failed to update order');
      // Refetch the authoritative order rather than snapping back to the last
      // fetched snapshot, which may predate a reorder that already committed.
      // Clearing the sync marker makes the render-time sync block re-run even
      // if the refetch returns referentially identical data.
      setSyncedPodcasts(undefined);
      queryClient.invalidateQueries({ queryKey: playlistKeys.podcasts(playlist.id) });
    }
  };

  const handleRemove = async (podcastId: number) => {
    setRemovingId(podcastId);
    try {
      await removePodcast.mutateAsync({ playlistId: playlist.id, podcastId });
      message.success('Podcast removed from playlist');
    } catch {
      message.error('Failed to remove podcast');
    } finally {
      setRemovingId(null);
    }
  };

  const handleAddPodcast = async (podcastId: number) => {
    try {
      await addPodcasts.mutateAsync({
        playlistId: playlist.id,
        podcastIds: [podcastId],
      });
      message.success('Podcast added to playlist');
    } catch {
      message.error('Failed to add podcast');
    }
  };

  // Returns whether the save succeeded so the editor can close only on success.
  const handleUpdateRule = async (
    podcastId: number,
    data: AssignmentOverrideUpdate
  ): Promise<boolean> => {
    setUpdatingId(podcastId);
    try {
      await updateRule.mutateAsync({ playlistId: playlist.id, podcastId, data });
      message.success('Rule updated');
      return true;
    } catch (err: unknown) {
      message.error(getErrorMessage(err));
      return false;
    } finally {
      setUpdatingId(null);
    }
  };

  if (isLoading) {
    return <LoadingSpinner tip="Loading podcasts..." />;
  }

  if (error) {
    return (
      <Alert
        type="error"
        message="Failed to load the playlist's podcasts"
        description="Please try refreshing the page."
        showIcon
      />
    );
  }

  const assignedIds = new Set(localPodcasts.map((p) => p.id));
  const availablePodcasts = (allPodcasts || []).filter((p) => !assignedIds.has(p.id));

  return (
    <Card
      title="Podcasts"
      extra={
        <Text type="secondary" style={{ fontSize: 12 }}>
          Drag to reorder
        </Text>
      }
    >
      {availablePodcasts.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Select<number>
            showSearch
            style={{ width: '100%', maxWidth: 400 }}
            placeholder="Add a podcast to this playlist..."
            filterOption={(input, option) =>
              String(option?.label ?? '')
                .toLowerCase()
                .includes(input.toLowerCase())
            }
            onSelect={(value: number) => handleAddPodcast(value)}
            value={undefined}
            loading={addPodcasts.isPending}
            options={availablePodcasts.map((p) => ({
              value: p.id,
              label: p.name,
            }))}
          />
        </div>
      )}

      {playlist.arrangement === 'by_date' && (
        <Alert
          type="info"
          message="Order is only used when the arrangement is 'In podcast order'"
          description="This playlist merges every episode by release date, so the drag order below is kept but has no effect until the arrangement changes."
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      {localPodcasts.length === 0 ? (
        <Text type="secondary">
          No podcasts assigned to this playlist yet. Use the selector above to add podcasts.
        </Text>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext
            items={localPodcasts.map((p) => p.id)}
            strategy={verticalListSortingStrategy}
          >
            <List
              dataSource={localPodcasts}
              renderItem={(podcast) => (
                <SortableItem
                  key={podcast.id}
                  podcast={podcast}
                  playlist={playlist}
                  onRemove={handleRemove}
                  removing={removingId === podcast.id}
                  onUpdateRule={handleUpdateRule}
                  updating={updatingId === podcast.id}
                />
              )}
            />
          </SortableContext>
        </DndContext>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function PlaylistDetail() {
  const { message } = App.useApp();
  const { id } = useParams();
  const playlistId = Number(id);
  const validId = Number.isInteger(playlistId) && playlistId > 0;
  const { data: playlist, isLoading, error } = usePlaylist(validId ? playlistId : 0);
  const runPlaylist = useRunPlaylist();
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [isEditOpen, setIsEditOpen] = useState(false);

  const handleRun = async () => {
    if (!playlist) return;
    try {
      const result = await runPlaylist.mutateAsync(playlist.id);
      // A skipped weekend-only playlist and a partial rebuild both come back
      // 200, but neither is a clean success — don't report them as one.
      if (result.skipped || result.partial) {
        message.warning(result.message);
      } else {
        message.success(result.message);
      }
    } catch (err: unknown) {
      message.error(getErrorMessage(err));
    }
  };

  const backLink = (
    <Link to="/playlists">
      <ArrowLeftOutlined /> Playlists
    </Link>
  );

  if (!validId) {
    return (
      <Alert
        type="error"
        message="Playlist not found"
        description={<Space direction="vertical">{backLink}</Space>}
        showIcon
      />
    );
  }

  if (isLoading) {
    return <LoadingSpinner tip="Loading playlist..." />;
  }

  if (error || !playlist) {
    return (
      <Alert
        type="error"
        message="Failed to load playlist"
        description={
          <Space direction="vertical">
            <Text>{error ? getErrorMessage(error) : 'This playlist does not exist.'}</Text>
            {backLink}
          </Space>
        }
        showIcon
      />
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 8 }}>{backLink}</div>
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
            {playlist.name}
          </Title>
          <Text type="secondary">
            {playlist.podcast_count} podcast{playlist.podcast_count !== 1 ? 's' : ''} ·{' '}
            {arrangementLabel(playlist)}
          </Text>
        </div>
        <Space wrap>
          <Button icon={<PlayCircleOutlined />} onClick={handleRun} loading={runPlaylist.isPending}>
            Run
          </Button>
          <Button icon={<EditOutlined />} onClick={() => setIsEditOpen(true)}>
            Edit
          </Button>
          {playlist.spotify_playlist_id && (
            <Button
              icon={<ExportOutlined />}
              href={`https://open.spotify.com/playlist/${playlist.spotify_playlist_id}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open in Spotify
            </Button>
          )}
        </Space>
      </div>

      <Card title="Settings" style={{ marginBottom: 24 }}>
        <Descriptions column={isMobile ? 1 : 2} size="small">
          <Descriptions.Item label="Arrangement">
            {playlist.arrangement === 'by_position' ? 'In podcast order' : 'By release date'}
          </Descriptions.Item>
          {playlist.arrangement === 'by_date' && (
            <Descriptions.Item label="Direction">
              {dateDirectionLabel(playlist.date_direction)}
            </Descriptions.Item>
          )}
          <Descriptions.Item label="Default episodes">
            {episodeLimitLabel(playlist.default_episode_limit)}
          </Descriptions.Item>
          <Descriptions.Item label="Take from">
            {pickFromLabel(playlist.default_pick_from)}
          </Descriptions.Item>
          <Descriptions.Item label="Enabled">
            {playlist.is_enabled ? (
              <Tag color="success">Enabled</Tag>
            ) : (
              <Tag color="default">Disabled</Tag>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Weekend only">
            {playlist.is_weekend_only ? <Tag color="orange">Weekend</Tag> : 'No'}
          </Descriptions.Item>
          <Descriptions.Item label="Last updated">
            {playlist.last_updated_at ? (
              <Tooltip title={dayjs(playlist.last_updated_at).format('YYYY-MM-DD HH:mm:ss')}>
                {dayjs(playlist.last_updated_at).fromNow()}
              </Tooltip>
            ) : (
              'Never'
            )}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <MembershipSection playlist={playlist} />

      <PlaylistFormModal
        open={isEditOpen}
        playlist={playlist}
        onClose={() => setIsEditOpen(false)}
      />
    </div>
  );
}
