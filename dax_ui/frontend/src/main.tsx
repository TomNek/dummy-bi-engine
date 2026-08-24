import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ServerApp } from './components/server'
import { ErrorBoundary } from './components/ui/error-boundary'

// Debug: expose stores for Playwright inspection
import { useReportStore } from './stores/report-store'
import { useAppStore } from './stores/app-store'
import { useFilterStore } from './stores/filter-store'
;(window as unknown as Record<string, unknown>).__STORES__ = { useReportStore, useAppStore, useFilterStore }

// Route: /server/ui renders the Report Server management UI
// Everything else renders the runtime report UI
const isServerUI = window.location.pathname.startsWith('/server/ui')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      {isServerUI ? <ServerApp /> : <App />}
    </ErrorBoundary>
  </StrictMode>,
)
