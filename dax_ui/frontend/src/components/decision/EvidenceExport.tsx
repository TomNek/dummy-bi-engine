import React, { useCallback } from 'react'
import { Download } from 'lucide-react'

export interface EvidenceExportProps {
  kpiId: string
  evidenceBundle?: Record<string, unknown> | null
  disabled?: boolean
}

export const EvidenceExport: React.FC<EvidenceExportProps> = ({
  kpiId,
  evidenceBundle,
  disabled = false,
}) => {
  const isDisabled = disabled || !evidenceBundle
  const handleExport = useCallback(() => {
    if (!evidenceBundle) return
    const blob = new Blob([JSON.stringify(evidenceBundle, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `evidence_${kpiId}_${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }, [kpiId, evidenceBundle])

  return (
    <button
      data-testid="evidence-export-btn"
      onClick={handleExport}
      disabled={isDisabled}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '6px 14px',
        borderRadius: 8,
        border: '1px solid #d1d5db',
        backgroundColor: isDisabled ? '#f9fafb' : '#fff',
        color: isDisabled ? '#9ca3af' : '#374151',
        fontSize: 12,
        fontWeight: 500,
        cursor: isDisabled ? 'not-allowed' : 'pointer',
        transition: 'all 0.15s ease',
      }}
      title={isDisabled ? 'No evidence bundle available' : 'Download evidence bundle as JSON'}
    >
      <Download size={13} />
      Export Evidence
    </button>
  )
}
