/** @type {import('tailwindcss').Config} */
/**
 * Theme colours live in CSS variables that hold whole colour values (`#f1ede2`,
 * and `rgba(255,255,255,0.06)` in the glass theme) rather than channel
 * triplets. Tailwind cannot fold an opacity modifier into such a value, so it
 * dropped the declaration entirely: `bg-muted/70` and every
 * `bg-[var(--muted)]/70` in the tree emitted no rule at all, which is why the
 * sidebars had no hover state, no text hierarchy and no surface tint.
 *
 * `color-mix` gives the modifier somewhere to land. At full opacity it
 * resolves to the variable untouched, so existing utilities keep their exact
 * colour, and it composes correctly with the variables that already carry an
 * alpha of their own.
 */
const alpha = name => `color-mix(in srgb, var(${name}) calc(<alpha-value> * 100%), transparent)`

module.exports = {
  darkMode: 'class',
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './features/**/*.{js,ts,jsx,tsx,mdx}',
    './shared/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './lib/reading-age-presentation.ts',
  ],
  theme: {
    extend: {
      fontFamily: {
        // Geist and Lora are Latin-only. Without an explicit CJK face after
        // them, Chinese fell through to the browser's generic `serif`/`sans`,
        // which differs per machine and per OS — a serif heading rendered its
        // Latin in Lora and its Chinese in whatever the browser happened to
        // pick. Naming the CJK faces makes both scripts deterministic and
        // pairs a Latin serif with a proper 宋体 rather than a stray fallback.
        sans: [
          'var(--font-sans)',
          'PingFang SC',
          'Hiragino Sans GB',
          'Microsoft YaHei',
          'Noto Sans SC',
          'system-ui',
          'sans-serif',
        ],
        serif: [
          'var(--font-serif)',
          'Songti SC',
          'STSong',
          'Noto Serif SC',
          'Source Han Serif SC',
          'SimSun',
          'Georgia',
          'serif',
        ],
      },
      colors: {
        border: alpha('--border'),
        input: alpha('--input'),
        ring: alpha('--ring'),
        background: alpha('--background'),
        foreground: alpha('--foreground'),
        primary: {
          DEFAULT: alpha('--primary'),
          foreground: alpha('--primary-foreground'),
        },
        secondary: {
          DEFAULT: alpha('--secondary'),
          foreground: alpha('--secondary-foreground'),
        },
        destructive: {
          DEFAULT: alpha('--destructive'),
          foreground: alpha('--destructive-foreground'),
        },
        muted: {
          DEFAULT: alpha('--muted'),
          foreground: alpha('--muted-foreground'),
        },
        accent: {
          DEFAULT: alpha('--accent'),
          foreground: alpha('--accent-foreground'),
        },
        popover: {
          DEFAULT: alpha('--popover'),
          foreground: alpha('--popover-foreground'),
        },
        card: {
          DEFAULT: alpha('--card'),
          foreground: alpha('--card-foreground'),
        },
        success: {
          DEFAULT: alpha('--success'),
          foreground: alpha('--success-foreground'),
          surface: alpha('--success-surface'),
        },
        warning: {
          DEFAULT: alpha('--warning'),
          foreground: alpha('--warning-foreground'),
          surface: alpha('--warning-surface'),
        },
        info: {
          DEFAULT: alpha('--info'),
          foreground: alpha('--info-foreground'),
          surface: alpha('--info-surface'),
        },
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'gradient-conic': 'conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))',
      },
    },
  },
  plugins: [],
}
