import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// dev 서버는 5173 (서버 main.py의 CORS가 5173만 허용한다)
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
})
