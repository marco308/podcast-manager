import { theme, type ThemeConfig } from 'antd';

const commonTokens = {
  colorPrimary: '#1DB954', // Spotify green
  borderRadius: 8,
};

export const lightTheme: ThemeConfig = {
  token: {
    ...commonTokens,
  },
};

export const darkTheme: ThemeConfig = {
  token: {
    ...commonTokens,
  },
  algorithm: theme.darkAlgorithm,
};
