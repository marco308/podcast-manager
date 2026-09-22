import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';

export type ThemePreference = 'light' | 'dark' | 'system';

interface ThemeContextType {
  isDarkMode: boolean;
  themePreference: ThemePreference;
  setThemePreference: (preference: ThemePreference) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

const STORAGE_KEY = 'theme-preference';

function getSystemPrefersDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function computeIsDarkMode(preference: ThemePreference): boolean {
  switch (preference) {
    case 'dark':
      return true;
    case 'light':
      return false;
    case 'system':
      return getSystemPrefersDark();
    default:
      return false;
  }
}

function getStoredPreference(): ThemePreference {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark' || stored === 'system') {
    return stored;
  }
  // A stored 'auto' (the removed time-of-day mode, issue #248) falls through
  // to 'system', which is what it resolved to in every browser anyway.
  return 'system'; // Default to system preference
}

interface ThemeProviderProps {
  children: ReactNode;
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  const [themePreference, setThemePreferenceState] = useState<ThemePreference>(getStoredPreference);
  const [isDarkMode, setIsDarkMode] = useState(() => computeIsDarkMode(getStoredPreference()));

  const updateDarkMode = useCallback(() => {
    setIsDarkMode(computeIsDarkMode(themePreference));
  }, [themePreference]);

  // Listen for system preference changes
  useEffect(() => {
    if (themePreference !== 'system') return;

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = () => updateDarkMode();

    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, [themePreference, updateDarkMode]);

  // Apply data-theme attribute to document
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', isDarkMode ? 'dark' : 'light');
  }, [isDarkMode]);

  const setThemePreference = useCallback((preference: ThemePreference) => {
    setThemePreferenceState(preference);
    setIsDarkMode(computeIsDarkMode(preference));
    localStorage.setItem(STORAGE_KEY, preference);
  }, []);

  const toggleTheme = useCallback(() => {
    const newPreference = isDarkMode ? 'light' : 'dark';
    setThemePreference(newPreference);
  }, [isDarkMode, setThemePreference]);

  return (
    <ThemeContext.Provider value={{ isDarkMode, themePreference, setThemePreference, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components -- hook co-located with its provider; only affects dev fast-refresh
export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
