/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
        sans: ['Manrope', 'ui-sans-serif', 'system-ui'],
      },
      colors: {
        ink: { 900: '#0a0e12', 800: '#11161c', 700: '#1a2129', 600: '#232c36', 500: '#2f3a46', 400: '#4a5866' },
        phosphor: { DEFAULT: '#7FFFB2', dim: '#4fd488', dark: '#2a7a50' },
        amber: { signal: '#FFB547', dim: '#c78833' },
        alert: '#FF5C5C',
        paper: '#F5F1E8',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in': 'fadeIn 0.4s ease-out',
        'slide-up': 'slideUp 0.4s cubic-bezier(0.16, 1, 0.3, 1)',
      },
      keyframes: {
        fadeIn: { '0%': { opacity: 0 }, '100%': { opacity: 1 } },
        slideUp: { '0%': { opacity: 0, transform: 'translateY(8px)' }, '100%': { opacity: 1, transform: 'translateY(0)' } },
      },
    },
  },
}
