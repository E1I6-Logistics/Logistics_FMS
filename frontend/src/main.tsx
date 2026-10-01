import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './FmsControlApp'
import AppErrorBoundary from './components/AppErrorBoundary'
import { installGlobalErrorLogging } from './utils/clientLogger'
import './index.css'

installGlobalErrorLogging()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </React.StrictMode>,
)
