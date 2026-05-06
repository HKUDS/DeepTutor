/**
 * ThemeScript - Initializes theme from localStorage before React hydration
 * This prevents the flash of wrong theme on page load.
 *
 * This is a Server Component that renders an inline script tag.
 * The script runs before React hydration to prevent theme flash.
 */
export default function ThemeScript() {
  const themeScript = `(function(){try{var s=localStorage.getItem('deeptutor-theme');document.documentElement.classList.remove('dark','theme-glass','theme-snow');if(s==='dark'){document.documentElement.classList.add('dark');}else if(s==='glass'){document.documentElement.classList.add('dark','theme-glass');}else if(s==='snow'){document.documentElement.classList.add('theme-snow');}else if(s==='light'){}else{if(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches){document.documentElement.classList.add('dark');localStorage.setItem('deeptutor-theme','dark');}else{localStorage.setItem('deeptutor-theme','light');}}}catch(e){}})();`;

  return (
    <script
      dangerouslySetInnerHTML={{ __html: themeScript }}
      suppressHydrationWarning
    />
  );
}
