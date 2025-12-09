import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigProvider, App as AntApp } from 'antd';
import { AuthProvider } from './context';
import { MainLayout, ErrorBoundary } from './components';
import { Login, Dashboard, Podcasts, Playlists, Settings } from './pages';
import { setSession } from './api/client';
import { authApi } from './api';
import './App.css';

// Create React Query client (before session handling so we can clear cache if needed)
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

// Extract session or OAuth code from URL immediately (before React renders)
// This handles the OAuth callback redirect
const urlParams = new URLSearchParams(window.location.search);
const sessionFromUrl = urlParams.get('session');
const oauthCode = urlParams.get('code');

// Handle OAuth callback code (when Spotify redirects to frontend)
if (oauthCode && !sessionFromUrl) {
  // Extract session asynchronously
  authApi.handleCallback(oauthCode, urlParams.get('state') || undefined)
    .then((session) => {
      setSession(session);
      // Clean up URL
      window.history.replaceState({}, '', window.location.pathname);
    })
    .catch((error) => {
      console.error('OAuth callback failed:', error);
      window.history.replaceState({}, '', '/login');
    });
} else if (sessionFromUrl) {
  setSession(sessionFromUrl);
  // Clear any cached auth errors from previous sessions
  queryClient.clear();
  // Clean up URL
  window.history.replaceState({}, '', window.location.pathname);
}

// Ant Design theme configuration
const theme = {
  token: {
    colorPrimary: '#1DB954', // Spotify green
    borderRadius: 8,
  },
};

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ConfigProvider theme={theme}>
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
                    <Route path="/settings" element={<Settings />} />
                  </Route>
                </Routes>
              </AuthProvider>
            </BrowserRouter>
          </AntApp>
        </ConfigProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
