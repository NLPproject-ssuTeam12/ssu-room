import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// dev 서버는 5173 (서버 main.py의 CORS가 5173만 허용한다).
// host: true = 같은 네트워크의 다른 컴퓨터도 http://이컴퓨터IP:5173 으로 열 수 있다 (2대 시연, 서버는 SSUROOM_LAN=1)
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, host: true },
})
