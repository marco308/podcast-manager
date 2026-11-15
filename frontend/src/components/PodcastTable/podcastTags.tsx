import type { CSSProperties } from 'react';
import { Tag, Tooltip } from 'antd';
import dayjs from 'dayjs';
import type { Podcast } from '../../types';

// The count is only known once a playlist build has read the whole show
// (issue #155); until then say so rather than showing a made-up number.
// Limited rules never refresh it, so show its age too and grey it out once
// it's old enough that it shouldn't be read as current (issue #241).
const UNPLAYED_STALE_DAYS = 7;

export function UnplayedTag({ podcast, style }: { podcast: Podcast; style?: CSSProperties }) {
  const { unplayed_episodes: count, unplayed_counted_at: countedAt } = podcast;
  if (count === null || !countedAt) {
    return (
      <Tag
        color="default"
        style={style}
        title="Counted when a playlist build reads this podcast's full episode list"
      >
        unplayed: not counted
      </Tag>
    );
  }
  const counted = dayjs(countedAt);
  const stale = dayjs().diff(counted, 'day') >= UNPLAYED_STALE_DAYS;
  return (
    <Tag
      color={stale ? 'default' : 'blue'}
      style={style}
      title={`Counted ${counted.format('D MMM YYYY, HH:mm')} by a playlist build that read the full episode list`}
    >
      {count} unplayed · {counted.fromNow()}
    </Tag>
  );
}

// Marked by the sync when the show left the Spotify library (issue #155).
// It contributes no episodes from that moment, and the row is deleted after
// the grace period — say so rather than letting a playlist quietly shrink
// and a podcast later vanish (issue #240).
export function MissingTag({ podcast, style = {} }: { podcast: Podcast; style?: CSSProperties }) {
  return podcast.missing_since ? (
    <Tooltip
      title={`Not in your Spotify library since ${dayjs(podcast.missing_since).format('D MMM YYYY')}. It contributes no episodes to playlists, and will be removed from this app if it stays away. Follow it again on Spotify to restore it.`}
    >
      <Tag color="warning" style={style}>
        Not on Spotify
      </Tag>
    </Tooltip>
  ) : null;
}
