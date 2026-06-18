import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        serif: ['var(--font-newsreader)', 'Georgia', 'serif'],
        mono: ['var(--font-mono)', 'Courier New', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.02em' }],
        xs: ['0.875rem', { lineHeight: '1.375rem' }],
        sm: ['1rem', { lineHeight: '1.625rem' }],
        md: ['1.125rem', { lineHeight: '1.75rem' }],
        lg: ['1.25rem', { lineHeight: '1.875rem' }],
        xl: ['1.75rem', { lineHeight: '2.25rem' }],
        '2xl': ['2.75rem', { lineHeight: '3rem' }],
        '3xl': ['3.75rem', { lineHeight: '4rem' }],
      },
      colors: {
        paper: 'var(--color-paper)',
        ink: 'var(--color-ink)',
        accent: 'var(--color-accent)',
        'ink-muted': 'var(--color-ink-muted)',
        'ink-faint': 'var(--color-ink-faint)',
        rule: 'var(--color-rule)',
        surface: 'var(--color-surface)',
      },
      maxWidth: {
        content: '720px',
        prose: '62ch',
      },
      screens: {
        xs: '430px',
      },
    },
  },
  plugins: [],
}

export default config
