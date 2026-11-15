import { Tag, Tooltip } from 'antd';
import dayjs from 'dayjs';
import type { Playlist } from '../../types';

// Flags a playlist whose last build didn't go cleanly (issue #246): orange
// when it was written from incomplete data, red when it wasn't written at
// all. A clean build shows nothing — "Updated 3 hours ago" already says it.
export function LastRunTag({
  playlist,
  style,
}: {
  playlist: Pick<Playlist, 'last_run_status' | 'last_run_error' | 'last_run_at'>;
  style?: React.CSSProperties;
}) {
  const status = playlist.last_run_status;
  if (status !== 'partial' && status !== 'failed') return null;

  const when = playlist.last_run_at ? ` (${dayjs(playlist.last_run_at).fromNow()})` : '';
  const title =
    status === 'partial'
      ? `Last update was written from incomplete data${when}. ${playlist.last_run_error ?? ''}`
      : `Last update failed${when}; the playlist was left as it was. ${playlist.last_run_error ?? ''}`;

  return (
    <Tooltip title={title.trim()}>
      <Tag
        color={status === 'partial' ? 'orange' : 'red'}
        style={{ width: 'fit-content', ...style }}
      >
        {status === 'partial' ? 'Incomplete' : 'Last update failed'}
      </Tag>
    </Tooltip>
  );
}
