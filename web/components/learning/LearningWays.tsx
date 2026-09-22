'use client'

import Link from 'next/link'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  AnimatePresence,
  m as motion,
  useReducedMotion,
  type Transition,
} from 'framer-motion'
import { ArrowUpRight, ArrowRight, Check, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
type LearningKind = LearningSurface['kind']
import { LEARNING_SURFACES, type LearningSurface } from './surfaces'

const FOCUSABLE = 'a[href], input:not([disabled]), select:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])'
const tileClass = (accent: string) =>
  `flex h-11 w-11 shrink-0 items-center justify-center rounded-[14px] ${accent}`
const titleClass = 'text-[16px] font-semibold tracking-[-0.02em]'

/** The whole card owns the shared transform; child layout projection keeps text undistorted. */
export function LearningWays() {
  const { t } = useTranslation()
  const reduceMotion = useReducedMotion()
  const [openKind, setOpenKind] = useState<LearningKind | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const id = useId()
  const sharedId = (part: string, kind: LearningKind) => `${id}-${kind}-${part}`
  const close = useCallback(() => setOpenKind(null), [])
  const open = LEARNING_SURFACES.find(surface => surface.kind === openKind)
  const spring: Transition = reduceMotion
    ? { duration: 0 }
    : { type: 'spring', stiffness: 340, damping: 34, mass: 0.9 }

  return (
    <>
      <section aria-labelledby={id} className="mb-10">
        <h2 id={id} className="sr-only">
          {t('Ways to learn')}
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {LEARNING_SURFACES.map(surface => {
            const opened = openKind === surface.kind
            return (
              <motion.div
                key={surface.kind}
                layoutId={sharedId('surface', surface.kind)}
                className="group relative h-full border border-border bg-card shadow-sm transition-colors hover:border-primary/30"
                style={{ borderRadius: 20 }}
                whileHover={reduceMotion || opened ? undefined : { y: -3 }}
                whileTap={reduceMotion || opened ? undefined : { scale: 0.985, y: -1 }}
                transition={spring}
              >
                <button
                  type="button"
                  onClick={event => {
                    triggerRef.current = event.currentTarget
                    setOpenKind(surface.kind)
                  }}
                  aria-haspopup="dialog"
                  aria-expanded={opened}
                  aria-controls={opened ? `${id}-panel` : undefined}
                  className="relative flex h-full min-h-[196px] w-full flex-col items-start rounded-[20px] p-5 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring"
                >
                  <span className="mb-5 flex w-full items-center justify-between">
                    <motion.span
                      layout="position"
                      layoutId={sharedId('icon', surface.kind)}
                      transition={spring}
                      className={tileClass(surface.accent)}
                    >
                      <surface.icon size={21} aria-hidden="true" />
                    </motion.span>
                    <ArrowUpRight
                      size={18}
                      aria-hidden="true"
                      className="text-muted-foreground/50 transition duration-200 group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-foreground group-focus-within:text-foreground motion-reduce:transform-none"
                    />
                  </span>
                  <motion.h3
                    layout="position"
                    layoutId={sharedId('title', surface.kind)}
                    transition={spring}
                    className={titleClass}
                  >
                    {t(surface.title)}
                  </motion.h3>
                  <motion.p
                    layout="position"
                    layoutId={sharedId('description', surface.kind)}
                    transition={spring}
                    className="mt-2 text-[12.5px] leading-[1.7] text-muted-foreground"
                  >
                    {t(surface.description)}
                  </motion.p>
                </button>
              </motion.div>
            )
          })}
        </div>
      </section>
      <AnimatePresence>
        {open && (
          <WayPanel
            key={open.kind}
            surface={open}
            id={id}
            sharedId={sharedId}
            spring={spring}
            reduceMotion={!!reduceMotion}
            close={close}
            triggerRef={triggerRef}
          />
        )}
      </AnimatePresence>
    </>
  )
}

function WayPanel({
  surface,
  id,
  sharedId,
  spring,
  reduceMotion,
  close,
  triggerRef,
}: {
  surface: LearningSurface
  id: string
  sharedId: (part: string, kind: LearningKind) => string
  spring: Transition
  reduceMotion: boolean
  close: () => void
  triggerRef: React.RefObject<HTMLButtonElement | null>
}) {
  const { t } = useTranslation()
  const rootRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const fade: Transition = { duration: reduceMotion ? 0 : 0.2 }

  // Keep the page inert and its scroll position intact until the return animation finishes.
  useEffect(() => {
    const trigger = triggerRef.current
    const siblings = Array.from(document.body.children).filter(
      (node): node is HTMLElement => node instanceof HTMLElement && node !== rootRef.current
    )
    const previous = siblings.map(node => node.inert)
    siblings.forEach(node => {
      node.inert = true
    })
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    panelRef.current?.focus({ preventScroll: true })
    return () => {
      siblings.forEach((node, index) => {
        node.inert = previous[index]
      })
      document.body.style.overflow = overflow
      if (trigger?.isConnected) trigger.focus({ preventScroll: true })
    }
  }, [triggerRef])

  return createPortal(
    <motion.div
      ref={rootRef}
      layoutRoot
      className="fixed inset-0 z-[80] grid place-items-center p-3 sm:p-6"
      initial="hidden"
      animate="visible"
      exit="hidden"
    >
      {/* The scrim must not fade the shared elements along with itself. */}
      <motion.div
        className="absolute inset-0 bg-black/30 backdrop-blur-[6px] dark:bg-black/50"
        variants={{ hidden: { opacity: 0 }, visible: { opacity: 1 } }}
        transition={reduceMotion ? fade : { duration: 0.3 }}
        onClick={close}
        aria-hidden="true"
      />
      <motion.div
        layoutId={sharedId('surface', surface.kind)}
        transition={spring}
        style={{ borderRadius: 28 }}
        ref={panelRef}
        id={`${id}-panel`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-description`}
        tabIndex={-1}
        onKeyDown={event => {
          if (event.key === 'Escape') {
            event.stopPropagation()
            close()
            return
          }
          if (event.key !== 'Tab') return
          const nodes = Array.from(panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])
          const first = nodes[0]
          const last = nodes[nodes.length - 1]
          if (
            event.shiftKey &&
            (document.activeElement === first || document.activeElement === panelRef.current)
          ) {
            event.preventDefault()
            last?.focus()
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault()
            first?.focus()
          }
        }}
        className="relative flex overflow-hidden border border-border bg-card shadow-[0_32px_100px_-24px_rgb(0_0_0/0.3)] max-h-[calc(100dvh-1.5rem)] w-full max-w-[35rem] flex-col outline-none sm:max-h-[calc(100dvh-3rem)]"
      >
        <motion.div
          layout="position"
          transition={spring}
          className="relative min-h-0 overflow-y-auto overscroll-contain rounded-t-[28px] px-6 pt-7 sm:px-8 sm:pt-8"
        >
          <div className="flex items-center gap-3.5 pr-9">
            <motion.span
              layout="position"
              layoutId={sharedId('icon', surface.kind)}
              transition={spring}
              className={tileClass(surface.accent)}
            >
              <surface.icon size={21} aria-hidden="true" />
            </motion.span>
            <motion.h3
              layout="position"
              id={`${id}-title`}
              layoutId={sharedId('title', surface.kind)}
              transition={spring}
              className={titleClass}
            >
              {t(surface.title)}
            </motion.h3>
          </div>
          <motion.button
            type="button"
            onClick={close}
            aria-label={t('Close')}
            variants={{ hidden: { opacity: 0 }, visible: { opacity: 1 } }}
            transition={fade}
            className="absolute right-5 top-6 flex h-9 w-9 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring sm:right-6 sm:top-7"
          >
            <X size={18} aria-hidden="true" />
          </motion.button>
          <motion.p
            layout="position"
            layoutId={sharedId('description', surface.kind)}
            transition={spring}
            id={`${id}-description`}
            className="mt-5 text-[12.5px] leading-[1.7] text-muted-foreground"
          >
            {t(surface.description)}
          </motion.p>
          <motion.div
            layout="position"
            variants={{
              hidden: { opacity: 0 },
              visible: { opacity: 1, transition: { ...fade, delay: reduceMotion ? 0 : 0.12 } },
            }}
            transition={{ duration: reduceMotion ? 0 : 0.1, layout: spring }}
          >
            <p className="mt-4 text-[14px] leading-[1.85]">{t(surface.intro)}</p>
            <ul className="mb-1 mt-6 space-y-3 rounded-2xl bg-muted/50 p-4">
              {surface.highlights.map(highlight => (
                <li key={highlight} className="flex items-start gap-3 text-[12.5px] leading-[1.7]">
                  <span
                    className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${surface.accent}`}
                  >
                    <Check size={12} aria-hidden="true" />
                  </span>
                  {t(highlight)}
                </li>
              ))}
            </ul>
          </motion.div>
        </motion.div>
        <motion.div
          layout="position"
          variants={{
            hidden: { opacity: 0 },
            visible: { opacity: 1, transition: { ...fade, delay: reduceMotion ? 0 : 0.16 } },
          }}
          transition={{ ...fade, layout: spring }}
          className="relative flex shrink-0 flex-wrap items-center justify-end gap-2 p-6 sm:px-8"
        >
          <button
            type="button"
            onClick={close}
            className="rounded-xl px-4 py-2.5 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
          >
            {t('Go back')}
          </button>
          <Link
            href={surface.href}
            className="group flex items-center gap-3 rounded-xl bg-primary px-5 py-2.5 text-[13px] font-medium text-primary-foreground shadow-sm transition hover:brightness-110 active:scale-[0.98] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring motion-reduce:transform-none"
          >
            {t('Start')}
            <ArrowRight
              size={16}
              aria-hidden="true"
              className="transition-transform group-hover:translate-x-0.5 motion-reduce:transform-none"
            />
          </Link>
        </motion.div>
      </motion.div>
    </motion.div>,
    document.body
  )
}
