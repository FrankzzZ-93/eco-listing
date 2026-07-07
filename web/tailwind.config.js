import colors from 'tailwindcss/colors';

// Scoped to the ported image-studio only. Preflight (global reset) is OFF so it
// never clobbers the Ant Design pages; a scoped box-sizing/base reset lives in
// src/imagegen/index.css under `.imagegen-scope` instead.
/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'media',
  // Standard Tailwind (preflight ON) — this is the studio's native setup, so its
  // components render exactly like upstream. The studio CSS is a lazy chunk
  // loaded only on the /studio route.
  content: ['./src/imagegen/**/*.{js,ts,jsx,tsx}', './node_modules/streamdown/dist/*.js'],
  theme: {
    extend: {
      colors: {
        background: 'hsl(var(--background) / <alpha-value>)',
        border: 'hsl(var(--border) / <alpha-value>)',
        gray: colors.zinc,
        foreground: 'hsl(var(--foreground) / <alpha-value>)',
        input: 'hsl(var(--input) / <alpha-value>)',
        muted: {
          DEFAULT: 'hsl(var(--muted) / <alpha-value>)',
          foreground: 'hsl(var(--muted-foreground) / <alpha-value>)',
        },
        primary: {
          DEFAULT: 'hsl(var(--primary) / <alpha-value>)',
          foreground: 'hsl(var(--primary-foreground) / <alpha-value>)',
        },
        sidebar: {
          DEFAULT: 'hsl(var(--sidebar) / <alpha-value>)',
          foreground: 'hsl(var(--sidebar-foreground) / <alpha-value>)',
        },
      },
      fontFamily: {
        sans: ['var(--font-ui-sans)'],
        mono: ['var(--font-mono)'],
      },
    },
  },
  plugins: [],
}
