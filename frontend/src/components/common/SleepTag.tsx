import { Tag, Tooltip } from 'antd';
import { MoonOutlined } from '@ant-design/icons';

// Marks a sleep playlist (docs/design/sleep-playlists.md) wherever playlists
// are listed, so it is never mistaken for one that serves new episodes.
export function SleepTag({ style }: { style?: React.CSSProperties }) {
  return (
    <Tooltip title="Sleep playlist: only episodes you've already finished">
      <Tag icon={<MoonOutlined />} color="geekblue" style={{ width: 'fit-content', ...style }}>
        Sleep
      </Tag>
    </Tooltip>
  );
}
