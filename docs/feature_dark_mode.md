# Feature: Dark Mode for Frontend

## Overview

Add a dark mode toggle to the frontend that allows users to switch between light and dark themes. The implementation will leverage Ant Design 6's built-in theming system and CSS custom properties for custom styling.

## Goals

- Provide a comfortable viewing experience in low-light environments
- Respect user's system preference (`prefers-color-scheme`)
- Persist user's theme choice across sessions
- Maintain visual consistency with the Spotify-green brand identity
- Ensure all custom styles (category borders, card hovers) adapt to dark mode

## Technical Approach

### 1. Theme Configuration

**File:** `frontend/src/theme/themeConfig.ts` (new file)

Create centralized theme tokens for both light and dark modes:

```typescript
import { ThemeConfig } from 'antd';

const commonTokens = {
  colorPrimary: '#1DB954', // Spotify green
  borderRadius: 8,
};

export const lightTheme: ThemeConfig = {
  token: {
    ...commonTokens,
    colorBgContainer: '#ffffff',
    colorBgLayout: '#f5f5f5',
    colorText: 'rgba(0, 0, 0, 0.88)',
    colorTextSecondary: 'rgba(0, 0, 0, 0.65)',
  },
};

export const darkTheme: ThemeConfig = {
  token: {
    ...commonTokens,
    colorBgContainer: '#1f1f1f',
    colorBgLayout: '#141414',
    colorText: 'rgba(255, 255, 255, 0.88)',
    colorTextSecondary: 'rgba(255, 255, 255, 0.65)',
  },
  algorithm: theme.darkAlgorithm,
};
```

### 2. Theme Context

**File:** `frontend/src/context/ThemeContext.tsx` (new file)

Create a React context to manage theme state:

```typescript
interface ThemeContextType {
  isDarkMode: boolean;
  toggleTheme: () => void;
  setTheme: (dark: boolean) => void;
}
```

**Features:**
- Initialize from `localStorage` (key: `theme-preference`)
- Fall back to system preference via `matchMedia('(prefers-color-scheme: dark)')`
- Listen for system preference changes
- Expose toggle function for UI controls

### 3. App Integration

**File:** `frontend/src/App.tsx`

Wrap the app with `ThemeProvider` and pass the appropriate theme to `ConfigProvider`:

```typescript
<ThemeProvider>
  <ThemeConsumer>
    {({ isDarkMode }) => (
      <ConfigProvider theme={isDarkMode ? darkTheme : lightTheme}>
        {/* existing app content */}
      </ConfigProvider>
    )}
  </ThemeConsumer>
</ThemeProvider>
```

### 4. CSS Custom Properties

**File:** `frontend/src/index.css`

Add CSS variables for custom styling that Ant Design doesn't control:

```css
:root {
  --category-primary-border: #1890ff;
  --category-news-border: #52c41a;
  --category-background-border: #722ed1;
  --card-shadow: 0 2px 8px rgba(0, 0, 0, 0.09);
  --scrollbar-track: #f1f1f1;
  --scrollbar-thumb: #c1c1c1;
}

[data-theme='dark'] {
  --category-primary-border: #177ddc;
  --category-news-border: #49aa19;
  --category-background-border: #854eca;
  --card-shadow: 0 2px 8px rgba(0, 0, 0, 0.45);
  --scrollbar-track: #2a2a2a;
  --scrollbar-thumb: #4a4a4a;
}
```

### 5. CSS Updates

**File:** `frontend/src/App.css`

Update category row styles to use CSS variables:

```css
.category-primary {
  border-left: 3px solid var(--category-primary-border) !important;
}

.category-news {
  border-left: 3px solid var(--category-news-border) !important;
}

.category-background {
  border-left: 3px solid var(--category-background-border) !important;
}
```

### 6. Layout Updates

**File:** `frontend/src/components/Layout/MainLayout.tsx`

Remove hard-coded `background: '#fff'` and use Ant Design's design tokens:

```typescript
import { theme } from 'antd';

const { token } = theme.useToken();

// In Content component:
style={{
  background: token.colorBgContainer,
  padding: 24,
  borderRadius: 8,
}}
```

### 7. Theme Toggle UI

**File:** `frontend/src/components/Layout/Header.tsx`

Add a theme toggle button next to the user menu:

```typescript
import { SunOutlined, MoonOutlined } from '@ant-design/icons';
import { useTheme } from '../../context/ThemeContext';

const { isDarkMode, toggleTheme } = useTheme();

<Button
  type="text"
  icon={isDarkMode ? <SunOutlined /> : <MoonOutlined />}
  onClick={toggleTheme}
  aria-label={isDarkMode ? 'Switch to light mode' : 'Switch to dark mode'}
/>
```

### 8. Settings Page Integration

**File:** `frontend/src/pages/Settings.tsx`

Add a theme preference section:

```typescript
<Card title="Appearance">
  <Form.Item label="Theme">
    <Segmented
      options={[
        { label: 'Light', value: 'light' },
        { label: 'Dark', value: 'dark' },
        { label: 'System', value: 'system' },
      ]}
      value={themePreference}
      onChange={setThemePreference}
    />
  </Form.Item>
</Card>
```

## Files to Create

| File | Purpose |
|------|---------|
| `src/theme/themeConfig.ts` | Light/dark theme token definitions |
| `src/context/ThemeContext.tsx` | Theme state management |

## Files to Modify

| File | Changes |
|------|---------|
| `src/App.tsx` | Wrap with ThemeProvider, use dynamic theme |
| `src/index.css` | Add CSS custom properties for themes |
| `src/App.css` | Use CSS variables for category colors |
| `src/components/Layout/MainLayout.tsx` | Use design tokens instead of hard-coded colors |
| `src/components/Layout/Header.tsx` | Add theme toggle button |
| `src/pages/Settings.tsx` | Add appearance settings section |

## Implementation Steps

1. **Create theme configuration** - Define light/dark tokens in `themeConfig.ts`
2. **Create ThemeContext** - State management with localStorage persistence
3. **Update App.tsx** - Integrate ThemeProvider and dynamic ConfigProvider
4. **Add CSS variables** - Define custom properties for both themes in `index.css`
5. **Update App.css** - Replace hard-coded colors with CSS variables
6. **Update MainLayout** - Use Ant Design's `useToken` hook for backgrounds
7. **Add Header toggle** - Quick-access theme toggle button
8. **Update Settings page** - Full theme preference control with "System" option
9. **Test all pages** - Verify visual consistency across Dashboard, Podcasts, Playlists, Settings
10. **Test responsive** - Ensure dark mode works on mobile views

## User Preference Priority

1. User's explicit choice (stored in localStorage)
2. System preference (`prefers-color-scheme`)
3. Default to light mode

## Accessibility Considerations

- Maintain WCAG 2.1 AA contrast ratios in both themes
- Ensure focus indicators are visible in dark mode
- Provide clear aria-labels on toggle controls
- Test with screen readers

## Future Enhancements

- Sync theme preference to backend (user settings API)
- Add theme transition animations
- Support custom accent colors beyond Spotify green
- Add high-contrast mode option

## Testing Checklist

- [ ] Light mode displays correctly on all pages
- [ ] Dark mode displays correctly on all pages
- [ ] Toggle switches theme immediately
- [ ] Preference persists after page refresh
- [ ] System preference is respected on first visit
- [ ] Category row colors visible in both themes
- [ ] Card shadows appropriate for each theme
- [ ] Scrollbars styled for dark mode
- [ ] Mobile responsive views work in dark mode
- [ ] No flash of wrong theme on page load
