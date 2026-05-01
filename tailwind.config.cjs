/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{astro,html,js,ts,tsx,md,mdx}'],
  theme: {
    extend: {
      colors: {
        parchment: '#f7f1e3',
        ink: '#2d2417',
        venetian: '#8b1f1f',
        ottoman: '#0e6b5f',
        gold: '#b8945c',
      },
      fontFamily: {
        serif: ['"EB Garamond"', 'Georgia', 'serif'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
