import { BrowserRouter, Routes, Route } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigProvider, App as AntApp } from 'antd';
import { AuthProvider, ThemeProvider, useTheme } from './context';
import { MainLayout, ErrorBoundary } from './components';
import { Login, Dashboard, Podcasts, Playlists, PlaylistDetail, Settings } from './pages';
import { lightTheme, darkTheme } from './theme/themeConfig';
import './App.css';

// Create React Query client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function ThemedApp() {
  const { isDarkMode } = useTheme();

  return (
    <ConfigProvider theme={isDarkMode ? darkTheme : lightTheme}>
      <AntApp>
        <BrowserRouter>
          <AuthProvider>
            <Routes>
              {/* Public routes */}
              <Route path="/login" element={<Login />} />

              {/* Protected routes with layout */}
              <Route element={<MainLayout />}>
                <Route path="/" element={<Dashboard />} />
                <Route path="/podcasts" element={<Podcasts />} />
                <Route path="/playlists" element={<Playlists />} />
                <Route path="/playlists/:id" element={<PlaylistDetail />} />
                <Route path="/settings" element={<Settings />} />
              </Route>
            </Routes>
          </AuthProvider>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <ThemedApp />
        </ThemeProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
