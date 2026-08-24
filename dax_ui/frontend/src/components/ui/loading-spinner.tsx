import { cn } from '@/lib/utils'
import { Loader2 } from 'lucide-react'

interface LoadingSpinnerProps {
  text?: string
  className?: string
  size?: 'sm' | 'md' | 'lg'
  'data-testid'?: string
}

export function LoadingSpinner({
  text,
  className,
  size = 'md',
  ...props
}: LoadingSpinnerProps) {
  const sizeClasses = {
    sm: 'h-4 w-4',
    md: 'h-6 w-6',
    lg: 'h-8 w-8',
  }

  return (
    <div
      className={cn('flex items-center justify-center gap-2', className)}
      data-testid={props['data-testid']}
    >
      <Loader2 className={cn('animate-spin text-muted-foreground', sizeClasses[size])} />
      {text && <span className="text-sm text-muted-foreground">{text}</span>}
    </div>
  )
}
