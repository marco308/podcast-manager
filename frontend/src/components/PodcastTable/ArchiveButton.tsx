import { Button, Popconfirm } from 'antd';
import { InboxOutlined, UndoOutlined } from '@ant-design/icons';
import type { Podcast } from '../../types';
import { archiveDescription } from './podcastCopy';

interface ArchiveButtonProps {
  podcast: Podcast;
  // The drawer's full-width labelled button rather than the table's icon.
  block?: boolean;
  loading: boolean;
  onArchiveChange: (podcast: Podcast, archived: boolean) => void;
}

export function ArchiveButton({
  podcast,
  block = false,
  loading,
  onArchiveChange,
}: ArchiveButtonProps) {
  return podcast.is_archived ? (
    <Button
      icon={<UndoOutlined />}
      onClick={() => onArchiveChange(podcast, false)}
      loading={loading}
      size={block ? 'middle' : 'small'}
      block={block}
      aria-label="Restore podcast"
    >
      {block && 'Restore to App'}
    </Button>
  ) : (
    <Popconfirm
      title="Archive podcast"
      description={archiveDescription(podcast)}
      onConfirm={() => onArchiveChange(podcast, true)}
      okText="Archive"
      cancelText="Cancel"
    >
      <Button
        icon={<InboxOutlined />}
        loading={loading}
        size={block ? 'middle' : 'small'}
        block={block}
        aria-label="Archive podcast"
      >
        {block && 'Archive (keep following on Spotify)'}
      </Button>
    </Popconfirm>
  );
}
