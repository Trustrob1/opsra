/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        teal: {
          DEFAULT: '#028090',
          light: '#00A896',
          dark: '#015F6B',
        },
        mint: '#E0F4F6',
        accent: '#F4A261',
        'op-dark': '#0D1B2A',
        'op-dark2': '#112233',
        'op-green': '#27AE60',
        'op-red': '#E05252',
        'op-gray': '#6B7C8E',
        'op-light': '#F5FAFB',
        'op-border': '#D6E8EC',
      },
      fontFamily: {
        syne: ['Syne', 'ui-sans-serif', 'system-ui'],
        dm: ['DM Sans', 'ui-sans-serif', 'system-ui'],
      },
    },
  },
  plugins: [],
}