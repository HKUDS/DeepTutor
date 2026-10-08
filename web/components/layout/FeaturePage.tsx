import type { ComponentPropsWithRef, ReactNode, Ref, UIEventHandler } from 'react'

/** Feature page standard, based on Personalized Learning:
 * - Centered 1180px outer box; horizontal gutters 24px, 36px from 768px.
 * - Vertical padding 28px, 36px from 1024px; 24px from header to content.
 * - Serif page title 27px / 30px at 640px of usable content; no title icon.
 * - Sans description 12.5px, section label 13.5px; one h1 per page.
 * - Actions stack below the title under 640px of content and wrap in order.
 * - Grids share 520 / 800 / 1040px container breakpoints and a 12px gap.
 * - Readers, editors and chats retain pane-specific working toolbars.
 * Use FeaturePage once per scrolling page, or PageContainer inside an
 * existing scroller. Child components must not add another page gutter.
 */
export function PageContainer({
  children,
  className = '',
  spacing = 'page',
  ...props
}: ComponentPropsWithRef<'div'> & { spacing?: 'page' | 'toolbar' }) {
  return (
    <div
      {...props}
      data-page-container
      className={`dt-page-container mx-auto w-full min-w-0 max-w-[1180px] px-6 md:px-9 ${spacing === 'page' ? 'py-7 lg:py-9' : 'py-3'} ${className}`}
    >
      {children}
    </div>
  )
}

export function FeaturePage({
  children,
  className = '',
  scrollRef,
  onScroll,
}: {
  children: ReactNode
  className?: string
  scrollRef?: Ref<HTMLElement>
  onScroll?: UIEventHandler<HTMLElement>
}) {
  return (
    <section
      ref={scrollRef}
      onScroll={onScroll}
      data-feature-page
      className={`h-full min-h-0 w-full min-w-0 overflow-y-auto bg-[var(--background)] text-[var(--foreground)] [scrollbar-gutter:stable] ${className}`}
    >
      <PageContainer>{children}</PageContainer>
    </section>
  )
}

export const PAGE_TITLE_CLASS = 'dt-page-title min-w-0 break-words font-serif font-semibold leading-normal tracking-[-0.02em] text-[var(--foreground)]'
export const PAGE_DESCRIPTION_CLASS = 'mt-1.5 max-w-2xl text-[12.5px] leading-relaxed text-[var(--muted-foreground)]'
export const PAGE_SECTION_TITLE_CLASS = 'text-[13.5px] font-semibold text-[var(--foreground)]'

/** No decorative title icon or divider. Icons belong to cards and actions.
 * Secondary sections use h2 so a feature page always has one main heading.
 */
export function PageHeader({
  title,
  description,
  action,
  meta,
  level = 1,
  titleId,
  headingTour,
}: {
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  meta?: ReactNode
  level?: 1 | 2
  titleId?: string
  headingTour?: string
}) {
  const Heading = level === 1 ? 'h1' : 'h2'
  return (
    <header data-page-header className="dt-page-header mb-6 flex min-w-0 flex-col gap-4">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2.5">
          <Heading id={titleId} data-tour={headingTour} className={level === 1 ? PAGE_TITLE_CLASS : PAGE_SECTION_TITLE_CLASS}>
            {title}
          </Heading>
          {meta}
        </div>
        {description && <p className={PAGE_DESCRIPTION_CLASS}>{description}</p>}
      </div>
      {action && <div data-page-actions className="flex max-w-full shrink-0 flex-wrap items-center gap-2 [&>div]:max-w-full [&>div]:flex-wrap">{action}</div>}
    </header>
  )
}

export function pageActionClass(variant: 'primary' | 'secondary' = 'primary') {
  return `dt-page-action inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-[12.5px] font-medium leading-[18px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-60 ${
    variant === 'primary'
      ? 'bg-[var(--primary)] text-[var(--primary-foreground)] hover:opacity-90'
      : 'border border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--muted)]'
  }`
}

/** Column limits describe the content, while one set of container breakpoints
 * controls every library. Works on divs and semantic lists alike.
 */
export function pageGridClass(columns: 2 | 3 | 5 | 'board' = 2) {
  return `dt-page-grid dt-page-grid-${columns}`
}
