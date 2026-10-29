'use client'

import { createElement, forwardRef, type CSSProperties, type HTMLAttributes } from 'react'
import {
  AlarmClock,
  CircleCheck,
  CircleDashed,
  CircleDot,
  Repeat2,
  type LucideIcon,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { formatTime } from '../model/dates'
import type { CalendarItem } from '../model/items'

const TASK_ICONS: Record<string, LucideIcon> = {
  todo: CircleDashed,
  doing: CircleDot,
  done: CircleCheck,
}

export function itemTitle(
  item: CalendarItem,
  t: (key: string, options?: Record<string, unknown>) => string
): string {
  if (item.kind === 'review') return t('{{count}} reviews due', { count: item.count })
  return item.title || t('(No title)')
}

export function itemIcon(item: CalendarItem): LucideIcon | null {
  if (item.kind === 'task') return TASK_ICONS[item.card.status] ?? CircleDashed
  if (item.kind === 'review') return Repeat2
  if (item.kind === 'automation') return AlarmClock
  if (item.kind === 'event' && item.occurrence.task_id) return CircleDot
  return null
}

/**
 * One line for an item in a day row, a month cell or a list. Spans are
 * tinted bars; timed items read as a coloured dot, a time and a title.
 */
export const ItemChip = forwardRef<
  HTMLButtonElement,
  {
    item: CalendarItem
    variant: 'span' | 'line'
    selected?: boolean
    past?: boolean
    showTime?: boolean
    continuesBefore?: boolean
    continuesAfter?: boolean
    style?: CSSProperties
    className?: string
  } & Omit<HTMLAttributes<HTMLButtonElement>, 'style' | 'className'>
>(function ItemChip(
  {
    item,
    variant,
    selected,
    past,
    showTime = true,
    continuesBefore,
    continuesAfter,
    style,
    className = '',
    ...props
  },
  ref
) {
  const { t, i18n } = useTranslation()
  const Icon = itemIcon(item)
  const done = item.kind === 'task' && item.card.status === 'done'
  return (
    <button
      ref={ref}
      type="button"
      data-kind={item.kind}
      data-variant={variant}
      data-selected={selected || undefined}
      data-past={past || undefined}
      data-done={done || undefined}
      data-cut-before={continuesBefore || undefined}
      data-cut-after={continuesAfter || undefined}
      className={`dt-cal-chip ${className}`}
      style={{ '--ev': item.color, ...style } as CSSProperties}
      {...props}
    >
      {variant === 'line' && !Icon && <span aria-hidden className="dt-cal-chip-dot" />}
      {Icon &&
        createElement(Icon, {
          'aria-hidden': true,
          size: 12,
          strokeWidth: 2,
          className: 'dt-cal-chip-icon',
        })}
      {variant === 'line' && showTime && !item.allDay && (
        <span className="dt-cal-chip-time">{formatTime(item.start, i18n.language)}</span>
      )}
      <span className="dt-cal-chip-title">{itemTitle(item, t)}</span>
    </button>
  )
})
