import type { CSSProperties, ReactNode } from 'react'

/** Scale a single learning text run, keeping surrounding UI at its own size. */
export function LearningText({
  children,
  size,
  className = '',
  inline = false,
}: {
  children: ReactNode
  size: number
  className?: string
  /** Keep intentional labels in their surrounding status line. */
  inline?: boolean
}) {
  return (
    <span
      className={`learning-text ${className}`}
      style={
        {
          display: inline ? 'inline' : 'block',
          '--learning-text-base': `${size}px`,
        } as CSSProperties
      }
    >
      {children}
    </span>
  )
}
