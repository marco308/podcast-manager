import { Select } from 'antd';
import type { PodcastCategory } from '../../types';

interface CategorySelectProps {
  value: PodcastCategory;
  onChange: (value: PodcastCategory) => void;
  loading?: boolean;
}

const categoryOptions: { value: PodcastCategory; label: string; color: string }[] = [
  { value: 'primary', label: 'Primary', color: '#1890ff' },
  { value: 'news', label: 'News', color: '#52c41a' },
  { value: 'background', label: 'Background', color: '#722ed1' },
  { value: 'none', label: 'None', color: '#d9d9d9' },
];

export function CategorySelect({ value, onChange, loading }: CategorySelectProps) {
  return (
    <Select
      value={value}
      onChange={onChange}
      loading={loading}
      style={{ width: 120 }}
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
