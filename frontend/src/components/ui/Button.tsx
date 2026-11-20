import type { ButtonHTMLAttributes } from 'react'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'

const styles: Record<Variant, string> = {
  primary: 'bg-accent text-accent-ink hover:bg-accent-strong font-semibold',
  secondary: 'border border-control-line bg-control text-ink hover:border-ink-faint font-medium',
  danger: 'border border-bad/40 bg-bad/10 text-bad hover:bg-bad/20 font-semibold',
  ghost: 'text-ink-muted hover:text-ink hover:bg-control font-medium',
}

export function Button({
  variant = 'secondary',
  size = 'md',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md' }) {
  const sizing = size === 'sm' ? 'h-8 px-3 text-xs' : 'h-10 px-4 text-sm'
  return (
    <button
      type="button"
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-lg transition disabled:cursor-not-allowed disabled:opacity-50 ${sizing} ${styles[variant]} ${className}`}
    />
  )
}
