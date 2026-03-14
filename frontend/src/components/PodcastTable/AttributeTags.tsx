import { Tag, Tooltip } from 'antd';
import { OrderedListOutlined } from '@ant-design/icons';

interface AttributeTagsProps {
  isSequential: boolean;
}

export function AttributeTags({ isSequential }: AttributeTagsProps) {
  return (
    <span style={{ display: 'flex', gap: 4 }}>
      {isSequential && (
        <Tooltip title="Sequential - Episodes played in order (oldest first)">
          <Tag icon={<OrderedListOutlined />} color="blue">
            Sequential
          </Tag>
        </Tooltip>
      )}
      {!isSequential && <Tag color="default">--</Tag>}
    </span>
  );
}
