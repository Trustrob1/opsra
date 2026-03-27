/**
 * PostCSS config — required for Tailwind CSS v3 to work with Vite.
 * Both tailwindcss and autoprefixer are in package.json devDependencies.
 * Without this file, `npm run dev` and `npm run build` both fail.
 */
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
