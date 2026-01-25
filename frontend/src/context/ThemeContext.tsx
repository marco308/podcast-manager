import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';

export type ThemePreference = 'light' | 'dark' | 'system' | 'auto';

interface ThemeContextType {
  isDarkMode: boolean;
  themePreference: ThemePreference;
  setThemePreference: (preference: ThemePreference) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

const STORAGE_KEY = 'theme-preference';
const DARK_START_HOUR = 19; // 7 PM
const DARK_END_HOUR = 7;   // 7 AM

function getSystemPrefersDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function isNightTime(): boolean {
  const hour = new Date().getHours();
  return hour >= DARK_START_HOUR || hour < DARK_END_HOUR;
}

function computeIsDarkMode(preference: ThemePreference): boolean {
  switch (preference) {
    case 'dark':
      return true;
    case 'light':
      return false;
    case 'system':
      return getSystemPrefersDark();
    case 'auto':
      // First check system preference, then fall back to time-based
      if (window.matchMedia('(prefers-color-scheme: dark)').media !== 'not all') {
        return getSystemPrefersDark();
      }
      return isNightTime();
    default:
      return false;
  }
}

function getStoredPreference(): ThemePreference {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark' || stored === 'system' || stored === 'auto') {
    return stored;
  }
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

  // Update dark mode when preference changes
  useEffect(() => {
    updateDarkMode();
  }, [updateDarkMode]);

  // Listen for system preference changes
  useEffect(() => {
    if (themePreference !== 'system' && themePreference !== 'auto') return;

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = () => updateDarkMode();

    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, [themePreference, updateDarkMode]);

  // For 'auto' mode, check time periodically
  useEffect(() => {
    if (themePreference !== 'auto') return;

    // Check every minute for time-based changes
    const interval = setInterval(updateDarkMode, 60000);
    return () => clearInterval(interval);
  }, [themePreference, updateDarkMode]);

  // Apply data-theme attribute to document
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', isDarkMode ? 'dark' : 'light');
  }, [isDarkMode]);

  const setThemePreference = useCallback((preference: ThemePreference) => {
    setThemePreferenceState(preference);
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

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
