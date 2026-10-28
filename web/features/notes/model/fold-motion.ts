/**
 * Closing Dito folds the conversation back into its orb on the line.
 *
 * Three beats, all on the compositor (transform, opacity, filter): the panel
 * itself, cloned, collapses toward the orb and dissolves; a spark of light
 * leaves the point it collapses into and arcs onto the orb; the orb takes it
 * in with a small spring and a ring. The live panel is already gone, so the
 * page reflows under the clone and the orb is measured where it ends up.
 */

const EASE_OUT = 'cubic-bezier(0.32, 0.72, 0, 1)'
const SPRING = 'cubic-bezier(0.34, 1.56, 0.64, 1)'

export interface FoldTarget {
  rect: DOMRect
  /** The orb to land on; absent while a new thread's orb is still mounting. */
  orb: HTMLElement | null
}

export function foldIntoOrb(
  panel: HTMLElement,
  host: HTMLElement,
  locate: () => FoldTarget | null,
  close: () => void
) {
  const from = panel.getBoundingClientRect()
  const ghost = panel.cloneNode(true) as HTMLElement
  ghost.classList.add('dt-note-fold-ghost')
  ghost.setAttribute('aria-hidden', 'true')
  ghost.inert = true
  Object.assign(ghost.style, {
    left: `${from.left}px`,
    top: `${from.top}px`,
    width: `${from.width}px`,
    height: `${from.height}px`,
  })
  host.appendChild(ghost)
  // A clone starts scrolled to the top; keep the transcript where it was read.
  const originals = panel.querySelectorAll('*')
  const copies = ghost.querySelectorAll('*')
  originals.forEach((el, i) => {
    if (el.scrollTop) copies[i].scrollTop = el.scrollTop
  })
  panel.style.visibility = 'hidden'
  const started = performance.now()

  // The card starts collapsing at once, toward where the orb is now; waiting
  // for the page to settle would leave it hanging over the reflowing text.
  const estimate = locate()
  const ex = estimate ? estimate.rect.left + estimate.rect.width / 2 : from.left
  const ey = estimate ? estimate.rect.top + estimate.rect.height / 2 : from.top + from.height / 2
  // Collapse toward the point of the panel nearest the orb, so the card
  // reads as drawn into it rather than shrinking in place.
  const ox = Math.min(Math.max(ex - from.left, 0), from.width)
  const oy = Math.min(Math.max(ey - from.top, 24), from.height - 24)
  const sx = from.left + ox
  const sy = from.top + oy
  const pull = { x: (ex - sx) * 0.4, y: (ey - sy) * 0.4 }
  ghost.style.transformOrigin = `${ox}px ${oy}px`
  const collapse = ghost.animate(
    [
      { transform: 'translate(0, 0) scale(1)', opacity: 1, filter: 'blur(0px)' },
      {
        transform: `translate(${pull.x * 0.4}px, ${pull.y * 0.4}px) scale(0.6)`,
        opacity: 0.75,
        filter: 'blur(1px)',
        offset: 0.45,
      },
      {
        transform: `translate(${pull.x}px, ${pull.y}px) scale(0.05)`,
        opacity: 0,
        filter: 'blur(8px)',
      },
    ],
    { duration: 380, easing: 'cubic-bezier(0.3, 0, 0.2, 1)', fill: 'forwards' }
  )
  collapse.finished.finally(() => ghost.remove())
  // Unmount the panel only once the collapse is running on the compositor:
  // the page's re-render then cannot hold its first frames back.
  void collapse.ready.then(close, close)

  // The spark flies to where the orb ends up once the page has reflowed.
  void collapse.ready.finally(() =>
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        const target = locate()
        if (!target) return
        const tx = target.rect.left + target.rect.width / 2
        const ty = target.rect.top + target.rect.height / 2
        const dx = tx - sx
        const dy = ty - sy
        // The spark: born where the card collapses, lifted on a short arc.
        const spark = document.createElement('div')
        spark.className = 'dt-note-fold-spark'
        spark.style.left = `${sx}px`
        spark.style.top = `${sy}px`
        host.appendChild(spark)
        const lift = Math.min(48, 16 + Math.hypot(dx, dy) * 0.12)
        const flight = spark.animate(
          [
            { transform: 'translate(-50%, -50%) scale(0.2)', opacity: 0 },
            {
              transform: `translate(calc(-50% + ${dx * 0.3}px), calc(-50% + ${dy * 0.3}px)) scale(1.8)`,
              opacity: 1,
              offset: 0.3,
            },
            {
              transform: `translate(calc(-50% + ${dx * 0.7}px), calc(-50% + ${dy * 0.7 - lift}px)) scale(1.15)`,
              opacity: 1,
              offset: 0.7,
            },
            {
              transform: `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(0.6)`,
              opacity: 0.9,
            },
          ],
          {
            duration: 460,
            delay: Math.max(0, 140 - (performance.now() - started)),
            easing: EASE_OUT,
            fill: 'both',
          }
        )
        flight.finished
          .then(() => {
            spark.remove()
            land(host, tx, ty, target.orb)
          })
          .catch(() => spark.remove())
      })
    )
  )
}

function land(host: HTMLElement, x: number, y: number, orb: HTMLElement | null) {
  const ring = document.createElement('div')
  ring.className = 'dt-note-fold-ring'
  ring.style.left = `${x}px`
  ring.style.top = `${y}px`
  host.appendChild(ring)
  ring
    .animate(
      [
        { transform: 'translate(-50%, -50%) scale(0.5)', opacity: 0.75 },
        { transform: 'translate(-50%, -50%) scale(2.8)', opacity: 0 },
      ],
      { duration: 560, easing: EASE_OUT, fill: 'forwards' }
    )
    .finished.finally(() => ring.remove())
  orb?.animate(
    [
      { transform: 'scale(1.7)' },
      { transform: 'scale(0.9)', offset: 0.55 },
      { transform: 'scale(1)' },
    ],
    { duration: 460, easing: SPRING }
  )
}
