import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './theme.css'
import App from './App'
import ServerApp from './server/ServerApp'

const root = document.getElementById('root')
if (!root) throw new Error('#root가 없습니다 (index.html 확인)')

// 기본은 서버 모드. 주소 뒤에 ?demo를 붙이면 가짜 데이터 시연(mock/demo.js)
const isDemo = new URLSearchParams(window.location.search).has('demo')

createRoot(root).render(
  <StrictMode>
    {isDemo ? <App /> : <ServerApp />}
  </StrictMode>,
)
