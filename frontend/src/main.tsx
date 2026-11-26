import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './theme.css'
import ServerApp from './server/ServerApp'

const root = document.getElementById('root')
if (!root) throw new Error('#root가 없습니다 (index.html 확인)')

createRoot(root).render(
  <StrictMode>
    <ServerApp />
  </StrictMode>,
)
