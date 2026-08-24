import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from '../../src/App'
import { ErrorBoundary } from '../../src/components/ui/error-boundary'
import { useAppStore, useReportStore, useFilterStore } from '../../src/stores'
import '../../src/index.css'

if (typeof window !== 'undefined') {
  ;(window as unknown as Record<string, unknown>).__STORES__ = { useAppStore, useReportStore, useFilterStore }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
