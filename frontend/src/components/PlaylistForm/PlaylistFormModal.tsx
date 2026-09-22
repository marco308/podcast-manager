import { useState } from 'react';
import {
  Alert,
  App,
  Divider,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Spin,
  Switch,
  Typography,
} from 'antd';
import { ExportOutlined } from '@ant-design/icons';
import {
  useAddPodcastsToPlaylist,
  useCreatePlaylist,
  usePlaylistPodcasts,
  usePodcasts,
  useRemovePodcastFromPlaylist,
  useReorderPlaylistPodcasts,
  useSpotifyPlaylists,
  useUpdatePlaylist,
  useUpdatePlaylistPodcast,
} from '../../hooks';
import type {
  Arrangement,
  DateDirection,
  PickFrom,
  Playlist,
  PlaylistCreate,
  PlaylistPodcast,
  PlaylistUpdate,
  Podcast,
} from '../../types';
import { isAxiosError } from 'axios';
import { getErrorMessage } from '../../api';
import { EPISODE_LIMIT_MAX } from '../../types';
import { spotifyPlaylistUrl } from '../../utils/playlistLabels';
import { PlaylistPodcastsEditor, type EditorRow } from './PlaylistPodcastsEditor';

const { Text } = Typography;

// Save failures whose server message is worth showing verbatim.
const EXPLAINED_SAVE_ERRORS = [400, 409, 502];

// The form keeps the episode limit as a mode plus an optional custom count so
// the Select can offer "All / Latest only / Up to…" while the API sees a single
// integer (0 = all, 1 = latest, n = up to n).
type EpisodeLimitMode = 'all' | 'latest' | 'custom';

interface PlaylistFormValues {
  name: string;
  spotify_playlist_id?: string | null;
  arrangement: Arrangement;
  date_direction: DateDirection;
  episode_limit_mode: EpisodeLimitMode;
  custom_episode_limit?: number;
  default_pick_from: PickFrom;
  is_weekend_only: boolean;
  is_enabled: boolean;
}

function limitToMode(limit: number): EpisodeLimitMode {
  if (limit === 0) return 'all';
  if (limit === 1) return 'latest';
  return 'custom';
}

function modeToLimit(mode: EpisodeLimitMode, custom: number | undefined): number {
  if (mode === 'all') return 0;
  if (mode === 'latest') return 1;
  return custom ?? 2;
}

const NEW_PLAYLIST_VALUES: PlaylistFormValues = {
  name: '',
  arrangement: 'by_position',
  date_direction: 'oldest_first',
  episode_limit_mode: 'all',
  custom_episode_limit: undefined,
  default_pick_from: 'newest',
  is_weekend_only: false,
  is_enabled: true,
};

function valuesFor(playlist: Playlist | null): PlaylistFormValues {
  if (!playlist) return NEW_PLAYLIST_VALUES;
  const mode = limitToMode(playlist.default_episode_limit);
  return {
    name: playlist.name,
    spotify_playlist_id: playlist.spotify_playlist_id ?? undefined,
    arrangement: playlist.arrangement,
    date_direction: playlist.date_direction,
    episode_limit_mode: mode,
    custom_episode_limit: mode === 'custom' ? playlist.default_episode_limit : undefined,
    default_pick_from: playlist.default_pick_from,
    is_weekend_only: playlist.is_weekend_only,
    is_enabled: playlist.is_enabled,
  };
}

function rowsFor(members: PlaylistPodcast[]): EditorRow[] {
  return members.map((m) => ({
    id: m.id,
    name: m.name,
    publisher: m.publisher,
    image_url: m.image_url,
    is_sequential: m.is_sequential,
    episode_limit: m.override.episode_limit,
    pick_from: m.override.pick_from,
  }));
}

// Membership is edited as a draft and batched with the settings on Save, so
// reordering and per-row edits don't fire a request per click. The draft
// lives in this child so a re-render of the modal never resets it.
function MembershipDraft({
  initial,
  allPodcasts,
  defaultEpisodeLimit,
  defaultPickFrom,
  orderMatters,
  onDraft,
}: {
  initial: EditorRow[];
  allPodcasts: Podcast[];
  defaultEpisodeLimit: number;
  defaultPickFrom: PickFrom;
  orderMatters: boolean;
  onDraft: (rows: EditorRow[]) => void;
}) {
  const [rows, setRows] = useState<EditorRow[]>(initial);
  const handleChange = (next: EditorRow[]) => {
    setRows(next);
    onDraft(next);
  };
  return (
    <PlaylistPodcastsEditor
      rows={rows}
      onChange={handleChange}
      allPodcasts={allPodcasts}
      defaultEpisodeLimit={defaultEpisodeLimit}
      defaultPickFrom={defaultPickFrom}
      orderMatters={orderMatters}
    />
  );
}

export interface PlaylistFormModalProps {
  open: boolean;
  // null creates a new playlist; otherwise edits this one.
  playlist: Playlist | null;
  onClose: () => void;
  onSaved?: (playlist: Playlist) => void;
}

export function PlaylistFormModal({ open, playlist, onClose, onSaved }: PlaylistFormModalProps) {
  const { message } = App.useApp();
  const createPlaylist = useCreatePlaylist();
  const updatePlaylist = useUpdatePlaylist();
  const addPodcasts = useAddPodcastsToPlaylist();
  const removePodcast = useRemovePodcastFromPlaylist();
  const updateOverride = useUpdatePlaylistPodcast();
  const reorderPodcasts = useReorderPlaylistPodcasts();
  const { data: allPodcasts } = usePodcasts();
  const spotifyPlaylists = useSpotifyPlaylists(open);
  // Current members, only needed when editing. The body is not rendered
  // until they arrive so the editor can start from them.
  const { data: members, isLoading: membersLoading } = usePlaylistPodcasts(playlist?.id ?? 0);
  const membersReady = !playlist || (!membersLoading && members !== undefined);
  const initialRows = playlist && members ? rowsFor(members) : [];
  const [draft, setDraft] = useState<EditorRow[] | null>(null);
  const [form] = Form.useForm<PlaylistFormValues>();

  const arrangement = Form.useWatch('arrangement', form);
  const episodeLimitMode = Form.useWatch('episode_limit_mode', form);
  const customLimit = Form.useWatch('custom_episode_limit', form);
  const watchedPick = Form.useWatch('default_pick_from', form);
  const linkedSpotifyId = Form.useWatch('spotify_playlist_id', form);

  const spotifyUrl = spotifyPlaylistUrl(playlist?.spotify_playlist_id);

  const handleClose = () => {
    setDraft(null);
    onClose();
  };

  const handleSubmit = async () => {
    let values: PlaylistFormValues;
    try {
      values = await form.validateFields();
    } catch {
      // Form validation error — Ant Design shows inline errors automatically
      return;
    }

    const shared = {
      name: values.name,
      // null, not undefined: the server reads a present-and-null as "unlink"
      // and an absent field as "leave the link alone".
      spotify_playlist_id: values.spotify_playlist_id ?? null,
      is_enabled: values.is_enabled,
      is_weekend_only: values.is_weekend_only,
      default_episode_limit: modeToLimit(values.episode_limit_mode, values.custom_episode_limit),
      default_pick_from: values.default_pick_from,
      arrangement: values.arrangement,
      date_direction: values.date_direction,
    };

    let saved: Playlist;
    try {
      if (playlist) {
        const updateData: PlaylistUpdate = shared;
        saved = await updatePlaylist.mutateAsync({ id: playlist.id, data: updateData });
      } else {
        const createData: PlaylistCreate = shared;
        saved = await createPlaylist.mutateAsync(createData);
      }
    } catch (err: unknown) {
      // The server says what it refused: a rename Spotify rejected (502,
      // nothing saved), or a Spotify link that isn't yours (400) or is
      // already linked elsewhere (409, issue #245). Surface those; anything
      // else stays generic.
      const status = isAxiosError(err) ? err.response?.status : undefined;
      message.error(
        status !== undefined && EXPLAINED_SAVE_ERRORS.includes(status)
          ? getErrorMessage(err)
          : 'Failed to save playlist'
      );
      return;
    }

    // Membership is applied after the settings save so a brand-new playlist
    // has an id to add to. A failure here leaves the settings saved and says
    // so, rather than reporting the whole save as failed.
    const rows = draft ?? initialRows;
    const before = new Map(initialRows.map((r) => [r.id, r]));
    const wanted = new Set(rows.map((r) => r.id));
    const toAdd = rows.filter((r) => !before.has(r.id));
    const toRemove = initialRows.filter((r) => !wanted.has(r.id));
    const toPatch = rows.filter((r) => {
      const prev = before.get(r.id);
      // A new row only needs a PATCH when it carries an override; an existing
      // row only when an override changed.
      if (!prev) return r.episode_limit !== null || r.pick_from !== null;
      return prev.episode_limit !== r.episode_limit || prev.pick_from !== r.pick_from;
    });
    const orderChanged =
      toAdd.length > 0 || toRemove.length > 0 || rows.some((r, i) => initialRows[i]?.id !== r.id);

    try {
      if (toAdd.length > 0) {
        await addPodcasts.mutateAsync({
          playlistId: saved.id,
          podcastIds: toAdd.map((r) => r.id),
        });
      }
      await Promise.all(
        toRemove.map((r) => removePodcast.mutateAsync({ playlistId: saved.id, podcastId: r.id }))
      );
      await Promise.all(
        toPatch.map((r) =>
          updateOverride.mutateAsync({
            playlistId: saved.id,
            podcastId: r.id,
            data: { episode_limit: r.episode_limit, pick_from: r.pick_from },
          })
        )
      );
      if (orderChanged && rows.length > 0) {
        await reorderPodcasts.mutateAsync({
          playlistId: saved.id,
          podcastIds: rows.map((r) => r.id),
        });
      }
    } catch {
      message.warning(
        `Playlist ${playlist ? 'updated' : 'created'}, but some podcast changes failed. Check the playlist page.`
      );
      onSaved?.(saved);
      handleClose();
      return;
    }

    message.success(playlist ? 'Playlist updated' : 'Playlist created');
    onSaved?.(saved);
    handleClose();
  };

  const saving =
    createPlaylist.isPending ||
    updatePlaylist.isPending ||
    addPodcasts.isPending ||
    removePodcast.isPending ||
    updateOverride.isPending ||
    reorderPodcasts.isPending;

  return (
    <Modal
      title={playlist ? 'Edit Playlist' : 'Add Playlist'}
      open={open}
      onOk={handleSubmit}
      onCancel={handleClose}
      confirmLoading={saving}
      okButtonProps={{ disabled: !membersReady }}
      width={880}
      // Remount the form on every open so `initialValues` reflects the
      // playlist being edited (or the defaults for a new one).
      destroyOnHidden
    >
      {!membersReady ? (
        <div style={{ textAlign: 'center', padding: 32 }}>
          <Spin />
        </div>
      ) : (
        <Form<PlaylistFormValues>
          form={form}
          layout="vertical"
          style={{ marginTop: 16 }}
          initialValues={valuesFor(playlist)}
        >
          <Form.Item
            name="name"
            label="Name"
            extra={
              playlist?.spotify_playlist_id
                ? 'Renaming here also renames the playlist on Spotify'
                : undefined
            }
            rules={[{ required: true, message: 'Please enter a name' }]}
          >
            <Input placeholder="e.g., Morning Podcasts" />
          </Form.Item>
          <Form.Item
            name="spotify_playlist_id"
            label="Spotify playlist"
            extra={
              spotifyUrl ? (
                <span>
                  Currently linked to{' '}
                  <a href={spotifyUrl} target="_blank" rel="noopener noreferrer">
                    this Spotify playlist <ExportOutlined />
                  </a>
                  . Clearing this leaves that playlist alone on Spotify and creates a new one on the
                  next run.
                </span>
              ) : (
                'Leave empty and a new Spotify playlist is created on the first run, or pick one of your own playlists to take it over'
              )
            }
          >
            <Select<string>
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="Create a new Spotify playlist on the first run"
              loading={spotifyPlaylists.isLoading}
              notFoundContent={
                spotifyPlaylists.isError
                  ? `Couldn't load your Spotify playlists: ${getErrorMessage(spotifyPlaylists.error)}`
                  : undefined
              }
              // Only playlists the user owns are listed; one already linked to
              // another managed playlist is shown but can't be picked.
              options={(spotifyPlaylists.data ?? []).map((sp) => {
                const linkedElsewhere =
                  sp.linked_playlist_id !== null && sp.linked_playlist_id !== playlist?.id;
                return {
                  value: sp.id,
                  label: sp.name || sp.id,
                  disabled: linkedElsewhere,
                  title: linkedElsewhere ? 'Already linked to another playlist' : undefined,
                };
              })}
              optionRender={(option) => {
                const sp = spotifyPlaylists.data?.find((p) => p.id === option.value);
                if (!sp) return option.label;
                const linkedElsewhere =
                  sp.linked_playlist_id !== null && sp.linked_playlist_id !== playlist?.id;
                return (
                  <span>
                    {sp.name || sp.id}{' '}
                    <Text type="secondary">
                      {linkedElsewhere
                        ? '· already linked to another playlist'
                        : `· ${sp.item_count} item${sp.item_count === 1 ? '' : 's'}`}
                    </Text>
                  </span>
                );
              }}
            />
          </Form.Item>
          {linkedSpotifyId && (
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: -8, marginBottom: 24 }}
              message="This Spotify playlist will be fully overwritten on every rebuild. Anything you add to it in Spotify will be removed."
            />
          )}

          <Form.Item
            name="arrangement"
            label="Arrangement"
            extra="Group each podcast's episodes in the order you drag them, or merge every episode by release date"
            rules={[{ required: true, message: 'Please choose an arrangement' }]}
          >
            <Select<Arrangement>
              options={[
                { value: 'by_position', label: 'In podcast order' },
                { value: 'by_date', label: 'By release date' },
              ]}
            />
          </Form.Item>
          {arrangement === 'by_date' && (
            <Form.Item
              name="date_direction"
              label="Direction"
              extra="Which end of the merged timeline the playlist starts from"
              rules={[{ required: true, message: 'Please choose a direction' }]}
            >
              <Select<DateDirection>
                options={[
                  { value: 'newest_first', label: 'Newest first' },
                  { value: 'oldest_first', label: 'Oldest first' },
                ]}
              />
            </Form.Item>
          )}

          <Form.Item
            name="episode_limit_mode"
            label="Episodes per podcast"
            extra="Default for every podcast in this playlist; individual podcasts can override it below"
            rules={[{ required: true, message: 'Please choose how many episodes to include' }]}
          >
            <Select<EpisodeLimitMode>
              options={[
                { value: 'all', label: 'All unplayed' },
                { value: 'latest', label: 'Latest only' },
                { value: 'custom', label: 'Up to…' },
              ]}
            />
          </Form.Item>
          {episodeLimitMode === 'custom' && (
            <Form.Item
              name="custom_episode_limit"
              label="Maximum episodes"
              extra={`Between 2 and ${EPISODE_LIMIT_MAX} unplayed episodes per podcast`}
              rules={[{ required: true, message: 'Please enter a maximum' }]}
            >
              <InputNumber min={2} max={EPISODE_LIMIT_MAX} precision={0} style={{ width: 160 }} />
            </Form.Item>
          )}

          <Form.Item
            name="default_pick_from"
            label="Take from"
            extra="Sequential podcasts always take from the oldest unfinished episode unless overridden below"
            rules={[{ required: true, message: 'Please choose where to take episodes from' }]}
          >
            <Select<PickFrom>
              options={[
                { value: 'newest', label: 'Newest' },
                { value: 'oldest', label: 'Oldest' },
              ]}
            />
          </Form.Item>

          <Form.Item
            name="is_weekend_only"
            label="Weekend Only"
            valuePropName="checked"
            extra="Only update this playlist on weekends and UK public holidays"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="is_enabled"
            label="Enabled"
            valuePropName="checked"
            extra="Disabled playlists are skipped by the daily update"
          >
            <Switch />
          </Form.Item>

          <Divider style={{ margin: '8px 0 16px' }}>
            <Text strong>Podcasts</Text>
          </Divider>
          <MembershipDraft
            initial={initialRows}
            allPodcasts={allPodcasts ?? []}
            defaultEpisodeLimit={modeToLimit(episodeLimitMode ?? 'all', customLimit)}
            defaultPickFrom={watchedPick ?? 'newest'}
            orderMatters={(arrangement ?? 'by_position') === 'by_position'}
            onDraft={setDraft}
          />
        </Form>
      )}
    </Modal>
  );
}
