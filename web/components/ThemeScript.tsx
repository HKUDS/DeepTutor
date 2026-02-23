'use client'

/**
 * ThemeScript - Initializes theme from localStorage before React hydration
 * This prevents the flash of wrong theme on page load
 */
export default function ThemeScript() {
  const themeScript = `
    (function() {
      try {
        const stored = localStorage.getItem('deeptutor-theme');

        if (stored === 'dark') {
          document.documentElement.classList.add('dark');
        } else if (stored === 'light') {
          document.documentElement.classList.remove('dark');
        } else {
          // Use system preference if not set
          if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
            document.documentElement.classList.add('dark');
            localStorage.setItem('deeptutor-theme', 'dark');
          } else {
            localStorage.setItem('deeptutor-theme', 'light');
          }
        }
      } catch (e) {
        // Silently fail - localStorage may be disabled
      }
    })();
  `

  return <script dangerouslySetInnerHTML={{ __html: themeScript }} suppressHydrationWarning />
}
