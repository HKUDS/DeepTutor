'use client'
import dynamic from 'next/dynamic'
import { apiUrl } from '@/lib/api'
import { extractMathAnimatorResult } from '@/lib/math-animator-types'
import type { VisualizeResult } from '@/lib/visualize-types'
const Visual = dynamic(() => import('@/components/visualize/VisualizationViewer'), { ssr: false })
const Animation = dynamic(() => import('@/components/math-animator/MathAnimatorViewer'), {
  ssr: false,
})
export default function NoteResult({ payload }: { payload: Record<string, unknown> }) {
  if (payload.renderer && payload.payload)
    return <Visual result={payload as unknown as VisualizeResult} />
  if (Array.isArray(payload.artifacts) && payload.artifacts.length) {
    const result = extractMathAnimatorResult(payload)
    if (result)
      return (
        <Animation
          bare
          result={{
            ...result,
            timings: {},
            code: { ...result.code, content: '' },
            render: { visual_review: result.render.visual_review },
          }}
        />
      )
  }
  const items = Array.isArray(payload.workspace_items)
    ? (payload.workspace_items as Record<string, unknown>[])
    : []
  return (
    <div className="space-y-2">
      {items.map((item, i) => {
        const url = String(item.url || '')
        if (!/^(https?:\/\/|\/(?!\/))/.test(url)) return null
        const mime = String(item.mime_type || '')
        return (
          <div key={i}>
            {mime.startsWith('audio/') ? (
              <audio className="w-full" controls preload="none" src={apiUrl(url)} />
            ) : mime.startsWith('video/') ? (
              <video className="w-full" controls preload="none" src={apiUrl(url)} />
            ) : mime.startsWith('image/') ? (
              // Generated assets use authenticated/scoped API URLs, not Next's image proxy.
              // eslint-disable-next-line @next/next/no-img-element
              <img
                className="h-auto max-w-full rounded-md"
                src={apiUrl(url)}
                alt={String(item.title || item.filename || '')}
              />
            ) : (
              <a className="text-[var(--primary)] underline" href={apiUrl(url)}>
                {String(item.filename || item.title || '')}
              </a>
            )}
          </div>
        )
      })}
    </div>
  )
}
