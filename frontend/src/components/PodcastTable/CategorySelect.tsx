import { Select } from 'antd';
import type { SizeType } from 'antd/es/config-provider/SizeContext';
import type { PodcastCategory } from '../../types';

interface CategorySelectProps {
  value: PodcastCategory[];
  onChange: (value: PodcastCategory[]) => void;
  loading?: boolean;
  size?: SizeType;
}

const categoryOptions: { value: PodcastCategory; label: string; color: string }[] = [
  { value: 'primary', label: 'Primary', color: '#1890ff' },
  { value: 'news', label: 'News', color: '#52c41a' },
  { value: 'background', label: 'Background', color: '#722ed1' },
  { value: 'weekend', label: 'Weekend', color: '#fa8c16' },
];

export function CategorySelect({ value, onChange, loading, size }: CategorySelectProps) {
  return (
    <Select
      mode="multiple"
      value={value}
      onChange={onChange}
      loading={loading}
      size={size}
      style={{ width: size === 'small' ? 140 : 180 }}
      placeholder="Uncategorized"
      allowClear
      maxTagCount="responsive"
      options={categoryOptions.map((opt) => ({
        value: opt.value,
        label: (
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                backgroundColor: opt.color,
              }}
            />
            {opt.label}
          </span>
        ),
      }))}
    />
  );
}

// Helper to get category color
export function getCategoryColor(category: PodcastCategory): string {
  const option = categoryOptions.find((opt) => opt.value === category);
  return option?.color || '#d9d9d9';
}
