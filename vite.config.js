import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  // In Cloudflare Pages, Render, Vercel, and standard hosts, serve from root ('/').
  // If building for GitHub Pages repository subpath, set GITHUB_PAGES=true or VITE_BASE_PATH.
  base: process.env.VITE_BASE_PATH || (process.env.GITHUB_PAGES ? '/PLEXIS-main/' : '/'),
  plugins: [react()],
}))
