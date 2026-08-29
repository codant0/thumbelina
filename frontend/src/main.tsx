import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { LocaleProvider } from './i18n'
import './index.css'
import './styles/layout.css'
import './styles/chat.css'
import './styles/pages.css'
import './styles/knowledge.css'
import './styles/composer.css'
import './styles/todo.css'
import './styles/trajectory.css'
import './styles/coder.css'
import './styles/memory.css'
import './styles/blocks.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LocaleProvider>
      <App />
    </LocaleProvider>
  </StrictMode>,
)
