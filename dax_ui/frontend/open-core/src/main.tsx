import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { OpenCoreApp } from '../../src/open-core/OpenCoreApp'
import '../../src/open-core/open-core.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <OpenCoreApp />
  </StrictMode>,
)
