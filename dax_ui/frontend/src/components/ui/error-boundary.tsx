import { Component, type ErrorInfo, type ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
  fallback?: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
  errorInfo: ErrorInfo | null
}

/**
 * React Error Boundary — catches render errors and shows fallback UI
 * instead of crashing/unmounting the entire React app.
 *
 * UX-1: Prevents total app crash from component-level errors.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null, errorInfo: null }
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.setState({ errorInfo })
    console.error('[ErrorBoundary] Caught render error:', error, errorInfo)
  }

  handleReload = () => {
    window.location.reload()
  }

  handleDismiss = () => {
    this.setState({ hasError: false, error: null, errorInfo: null })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }

      return (
        <div
          className="flex flex-col items-center justify-center h-screen bg-background text-foreground p-8"
          data-testid="error-boundary-fallback"
          role="alert"
          aria-live="assertive"
        >
          <div className="max-w-lg w-full space-y-6 text-center">
            <div className="space-y-2">
              <div className="text-4xl" aria-hidden="true">⚠️</div>
              <h1 className="text-xl font-semibold">Something went wrong</h1>
              <p className="text-sm text-muted-foreground">
                An unexpected error occurred in the application. You can try
                dismissing the error or reloading the page.
              </p>
            </div>

            {this.state.error && (
              <details className="text-left bg-muted rounded-md p-3">
                <summary className="text-sm font-medium cursor-pointer">
                  Error details
                </summary>
                <pre className="mt-2 text-xs text-destructive whitespace-pre-wrap overflow-auto max-h-48">
                  {this.state.error.message}
                  {this.state.errorInfo?.componentStack && (
                    <>
                      {'\n\nComponent stack:'}
                      {this.state.errorInfo.componentStack}
                    </>
                  )}
                </pre>
              </details>
            )}

            <div className="flex items-center justify-center gap-3">
              <button
                onClick={this.handleDismiss}
                className="px-4 py-2 text-sm font-medium rounded-md border border-border bg-background hover:bg-accent transition-colors"
                data-testid="error-boundary-dismiss"
                aria-label="Dismiss error and try to recover"
              >
                Dismiss
              </button>
              <button
                onClick={this.handleReload}
                className="px-4 py-2 text-sm font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
                data-testid="error-boundary-reload"
                aria-label="Reload the page"
              >
                Reload Page
              </button>
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
