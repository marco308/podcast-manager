import { RightOutlined } from '@ant-design/icons';
import type { PlaylistKind, PlaylistPodcast, RuleSource } from '../../types';
import {
  episodeLimitLabel,
  pickFromLabel,
  ruleSourceLabel,
  ruleSummary,
} from '../../utils/playlistLabels';
import { Balloon } from './Parts';

function sourceWord(source: RuleSource): string {
  if (source === 'override') return 'set on this show';
  if (source === 'sequential') return 'sequential hint';
  return 'playlist default';
}

// One show in a playlist, as a part: balloon, name, spec, lamp. The row
// opens in place to show where each half of its rule comes from.
export function PartRow({
  part,
  index,
  kind,
  enabled = true,
  orderMatters = true,
}: {
  part: PlaylistPodcast;
  index: number;
  kind: PlaylistKind;
  enabled?: boolean;
  orderMatters?: boolean;
}) {
  const source = ruleSourceLabel(part.rule);
  const missing = Boolean(part.missing_since);
  const specClass =
    source === 'custom' ? ' is-custom' : source === 'sequential' ? ' is-sequential' : '';

  return (
    <li className="pm-part-item">
      <details className="pm-part-details">
        <summary className="pm-part">
          <span
            style={{ display: 'inline-grid' }}
            title={orderMatters ? undefined : 'Order not used by this arrangement'}
          >
            <Balloon n={index + 1} sequential={part.is_sequential} unordered={!orderMatters} />
          </span>
          <span className="pm-part-name">
            {part.name}
            {part.publisher && <small>{part.publisher}</small>}
          </span>
          <span className={`pm-label pm-spec${missing ? '' : specClass}`}>
            {missing
              ? 'Not on Spotify'
              : ruleSummary(part.rule.episode_limit, part.rule.pick_from, kind)}
            {!missing && source !== 'playlist default' ? ` · ${source}` : ''}
          </span>
          <span className="pm-part-end">
            <span
              className={`pm-lamp ${missing ? 'is-partial' : enabled ? 'is-ok' : 'is-off'}`}
              role="img"
              aria-label={
                missing
                  ? 'Not on Spotify: contributes nothing'
                  : enabled
                    ? 'Contributing'
                    : 'Playlist off'
              }
            />
            <RightOutlined className="pm-part-chevron" aria-hidden="true" />
          </span>
        </summary>
        <dl className="pm-part-more">
          <div>
            <dt className="pm-label">Episodes</dt>
            <dd>
              {episodeLimitLabel(part.rule.episode_limit, kind)}
              <span>{sourceWord(part.rule.episode_limit_source)}</span>
            </dd>
          </div>
          <div>
            <dt className="pm-label">Take from</dt>
            <dd>
              {pickFromLabel(part.rule.pick_from)}
              <span>{sourceWord(part.rule.pick_from_source)}</span>
            </dd>
          </div>
          {missing && (
            <div>
              <dt className="pm-label">Library</dt>
              <dd>
                Unfollowed on Spotify. It adds nothing now and is removed after 7 days unless you
                follow it again.
              </dd>
            </div>
          )}
        </dl>
      </details>
    </li>
  );
}
