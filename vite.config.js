import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  // In dev (vite) serve from root so OAuth callbacks hit /auth/callback correctly.
  // In production build (vite build) use the GitHub Pages subpath.
  base: command === 'build' ? '/PLEXIS-main/' : '/',
  plugins: [react()],
}))
