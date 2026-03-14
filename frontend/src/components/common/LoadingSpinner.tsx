import { Spin } from 'antd';
import { LoadingOutlined } from '@ant-design/icons';

interface LoadingSpinnerProps {
  size?: 'small' | 'default' | 'large';
  tip?: string;
  fullScreen?: boolean;
}

export function LoadingSpinner({ size = 'large', tip, fullScreen = false }: LoadingSpinnerProps) {
  const spinnerContent = (
    <Spin
      indicator={<LoadingOutlined style={{ fontSize: size === 'large' ? 48 : 24 }} spin />}
      tip={tip}
      size={size}
    />
  );

  if (fullScreen) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          minHeight: '100vh',
          background: '#f5f5f5',
        }}
      >
        {spinnerContent}
      </div>
    );
  }

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        padding: 48,
      }}
    >
      {spinnerContent}
    </div>
  );
}
