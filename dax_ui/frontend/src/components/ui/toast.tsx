/**
 * Toast notification system
 * 
 * Lightweight toast/notification component with Zustand store.
 * Displays transient messages at the bottom-right of the screen.
 * Auto-dismisses after a configurable duration.
 */
import { useEffect } from 'react'
import { create } from 'zustand'
import { X } from 'lucide-react'

// --- Types ---

export type ToastVariant = 'default' | 'success' | 'error' | 'warning'

export interface ToastItem {
  id: string
  message: string
  variant: ToastVariant
  duration: number // ms, 0 = sticky
}

interface ToastStore {
  toasts: ToastItem[]
  addToast: (message: string, opts?: { variant?: ToastVariant; duration?: number }) => string
  removeToast: (id: string) => void
}

let _nextId = 0

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  addToast: (message, opts) => {
    const id = `toast-${++_nextId}`
    const item: ToastItem = {
      id,
      message,
      variant: opts?.variant ?? 'default',
      duration: opts?.duration ?? 4000,
    }
    set((s) => ({ toasts: [...s.toasts, item] }))
    return id
  },
  removeToast: (id) => {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
  },
}))

/** Convenience function — can be called from anywhere (no hook needed) */
export function toast(message: string, opts?: { variant?: ToastVariant; duration?: number }) {
  return useToastStore.getState().addToast(message, opts)
}

// --- Variant styles ---

const variantClasses: Record<ToastVariant, string> = {
  default: 'bg-background border-border text-foreground',
  success: 'bg-green-50 border-green-300 text-green-900 dark:bg-green-950 dark:border-green-800 dark:text-green-100',
  error: 'bg-destructive/10 border-destructive text-destructive',
  warning: 'bg-yellow-50 border-yellow-300 text-yellow-900 dark:bg-yellow-950 dark:border-yellow-800 dark:text-yellow-100',
}

// --- Single toast ---

function ToastEntry({ item }: { item: ToastItem }) {
  const { removeToast } = useToastStore()

  useEffect(() => {
    if (item.duration <= 0) return
    const timer = setTimeout(() => removeToast(item.id), item.duration)
    return () => clearTimeout(timer)
  }, [item.id, item.duration, removeToast])

  return (
    <div
      data-testid="status-toast"
      data-toast-variant={item.variant}
      className={`
        flex items-center gap-2 px-4 py-3 rounded-md border shadow-lg
        text-sm max-w-sm animate-in slide-in-from-right-5 fade-in
        ${variantClasses[item.variant]}
      `}
    >
      <span className="flex-1">{item.message}</span>
      <button
        onClick={() => removeToast(item.id)}
        className="shrink-0 opacity-60 hover:opacity-100 transition-opacity"
        aria-label="Dismiss"
        data-testid="toast-dismiss"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}

// --- Toaster container ---

export function Toaster() {
  const { toasts } = useToastStore()

  if (toasts.length === 0) return null

  return (
    <div
      data-testid="toast-container"
      className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 pointer-events-auto"
    >
      {toasts.map((t) => (
        <ToastEntry key={t.id} item={t} />
      ))}
    </div>
  )
}
