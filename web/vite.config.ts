import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({
  plugins: [vue()],
  base: './',
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: false } } },
  build: { outDir: 'dist', emptyOutDir: true, rolldownOptions: { input: { workbench: 'index.html', trainer: 'trainer.html' } } },
})
