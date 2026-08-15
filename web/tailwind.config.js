// Apple/iOS system palette (upstream edf05e8) — replaces Tailwind's zinc/blue so
// the studio's grays and accent match the iOS design language.
const appleGray = {
  50: '#f9f9fb',
  100: '#f2f2f7',
  200: '#e5e5ea',
  300: '#d1d1d6',
  400: '#aeaeb2',
  500: '#8e8e93',
  600: '#636366',
  700: '#48484a',
  800: '#2c2c2e',
  900: '#1c1c1e',
  950: '#09090b',
};

const appleBlue = {
  50: '#eef7ff',
  100: '#d9ecff',
  200: '#b8dcff',
  300: '#83c5ff',
  400: '#45a8ff',
  500: '#0a84ff',
  600: '#007aff',
  700: '#0066d6',
  800: '#0055b3',
  900: '#08488f',
  950: '#062d5d',
};

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
        gray: appleGray,
        blue: appleBlue,
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
