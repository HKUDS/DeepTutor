'use client'

import { useMemo } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'

// Math nodes already contain LaTeX, not Markdown. Keeping the mode explicit also
// prevents a lone inline formula from being normalized into a display paragraph.
export default function NoteMath({
  formula,
  display = false,
}: {
  formula: string
  display?: boolean
}) {
  const html = useMemo(
    () =>
      katex.renderToString(formula, {
        displayMode: display,
        throwOnError: false,
        trust: false,
        strict: 'ignore',
        maxExpand: 1000,
        maxSize: 20,
      }),
    [formula, display]
  )
  return (
    <span
      className={display ? 'dt-note-formula display' : 'dt-note-formula'}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
