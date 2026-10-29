import {
  DEFAULT_UI_LAYOUT,
  UI_LAYOUT_ATTRIBUTE,
  UI_LAYOUT_STORAGE_KEY,
} from "@/lib/ui-layout";

/**
 * ThemeScript - Initializes theme from localStorage before React hydration
 * This prevents the flash of wrong theme on page load.
 *
 * Must be a Server Component: in Next.js / React 19, <script> tags rendered
 * by Client Components are inert on the client. Rendering it from the server
 * inlines the snippet into the SSR HTML so the browser executes it before
 * hydration.
 */
export default function ThemeScript() {
  const themeScript = `
    (function() {
      try {
        const stored = localStorage.getItem('deeptutor-theme');

        document.documentElement.classList.remove('dark', 'theme-glass', 'theme-snow');

        if (stored === 'dark') {
          document.documentElement.classList.add('dark');
        } else if (stored === 'glass') {
          document.documentElement.classList.add('dark', 'theme-glass');
        } else if (stored === 'snow') {
          document.documentElement.classList.add('theme-snow');
        } else if (stored === 'light') {
          // already clean
        } else {
          // No stored preference: Default (snow) for light systems,
          // Dark for prefers-color-scheme: dark.
          if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
            document.documentElement.classList.add('dark');
            localStorage.setItem('deeptutor-theme', 'dark');
          } else {
            document.documentElement.classList.add('theme-snow');
            localStorage.setItem('deeptutor-theme', 'snow');
          }
        }
      } catch (e) {
        /* localStorage may be disabled */
      }
      // UI layout tokens (see lib/ui-layout.ts) must also paint before React.
      try {
        const layout = localStorage.getItem('${UI_LAYOUT_STORAGE_KEY}');
        document.documentElement.setAttribute(
          '${UI_LAYOUT_ATTRIBUTE}',
          layout === 'classic' || layout === 'modern' ? layout : '${DEFAULT_UI_LAYOUT}',
        );
      } catch (e) {
        document.documentElement.setAttribute('${UI_LAYOUT_ATTRIBUTE}', '${DEFAULT_UI_LAYOUT}');
      }
    })();
  `;

  return (
    <script
      dangerouslySetInnerHTML={{ __html: themeScript }}
      suppressHydrationWarning
    />
  );
}
