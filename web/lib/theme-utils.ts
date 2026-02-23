/**
 * Theme utilities for common scenarios
 * Use these helper functions for theme-related logic in components
 */

import { setTheme, type Theme } from './theme'

/**
 * Toggle theme between light and dark
 */
export function toggleTheme(currentTheme: Theme): Theme {
  const newTheme = currentTheme === 'light' ? 'dark' : 'light'
  setTheme(newTheme)
  return newTheme
}

/**
 * Set theme to light mode
 */
export function setLightTheme(): void {
  setTheme('light')
}

/**
 * Set theme to dark mode
 */
export function setDarkTheme(): void {
  setTheme('dark')
}

/**
 * Get CSS class for theme-aware styling
 */
export function getThemeClass(theme: Theme): string {
  return theme === 'dark' ? 'dark' : ''
}

/**
 * Get contrast color for theme
 */
export function getTextColorForTheme(theme: Theme): string {
  return theme === 'dark'
    ? 'text-slate-100 dark:text-slate-100'
    : 'text-slate-900 dark:text-slate-900'
}

/**
 * Get background color for theme
 */
export function getBackgroundForTheme(theme: Theme): string {
  return theme === 'dark' ? 'dark:bg-slate-800' : 'bg-white'
}

/**
 * Watch theme changes via localStorage events
 */
export function onThemeChange(callback: (theme: Theme) => void): () => void {
  const handleStorageChange = (e: StorageEvent) => {
    if (e.key === 'deeptutor-theme' && (e.newValue === 'light' || e.newValue === 'dark')) {
      callback(e.newValue)
    }
  }

  window.addEventListener('storage', handleStorageChange)

  // Return cleanup function
  return () => {
    window.removeEventListener('storage', handleStorageChange)
  }
}
