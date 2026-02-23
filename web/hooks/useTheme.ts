/**
 * useTheme hook for managing theme throughout the application
 */
import { useState } from 'react'
import { setTheme, initializeTheme, type Theme } from '@/lib/theme'

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(() => initializeTheme())
  const isLoaded = true

  const updateTheme = (newTheme: Theme) => {
    setTheme(newTheme)
    setThemeState(newTheme)
  }

  return {
    theme,
    isLoaded,
    setTheme: updateTheme,
    isDark: theme === 'dark',
    isLight: theme === 'light',
  }
}
