import { Tag, Tooltip } from 'antd';
import { OrderedListOutlined, CalendarOutlined } from '@ant-design/icons';

interface AttributeTagsProps {
  isSequential: boolean;
  isWeekendOnly: boolean;
}

export function AttributeTags({ isSequential, isWeekendOnly }: AttributeTagsProps) {
  return (
    <span style={{ display: 'flex', gap: 4 }}>
      {isSequential && (
        <Tooltip title="Sequential - Episodes played in order (oldest first)">
          <Tag icon={<OrderedListOutlined />} color="blue">
            Sequential
          </Tag>
        </Tooltip>
      )}
      {isWeekendOnly && (
        <Tooltip title="Weekend Only - Only included on weekends and holidays">
          <Tag icon={<CalendarOutlined />} color="purple">
            Weekend
          </Tag>
        </Tooltip>
      )}
      {!isSequential && !isWeekendOnly && <Tag color="default">—</Tag>}
    </span>
  );
}
