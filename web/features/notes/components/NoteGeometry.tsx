'use client'

import dynamic from 'next/dynamic'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { GeogebraPayload } from '@/components/Geogebra'
const Geometry = dynamic(() => import('@/components/Geogebra'), { ssr: false })

export default function NoteGeometry({ data }: { data: string }) {
  const root = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const payload = useMemo(() => {
    const parsed = JSON.parse(data)
    const view =
      parsed.view ||
      (parsed.settings
        ? {
            x_min: parsed.settings.xMin,
            x_max: parsed.settings.xMax,
            y_min: parsed.settings.yMin,
            y_max: parsed.settings.yMax,
          }
        : undefined)
    return {
      app_name: parsed.app_name || 'classic',
      commands: parsed.commands.map(String),
      show_axes: parsed.show_axes ?? parsed.settings?.showAxes,
      show_grid: parsed.show_grid ?? parsed.settings?.showGrid,
      ...(view && Object.values(view).every(Number.isFinite) ? { view } : {}),
    } as GeogebraPayload
  }, [data])
  useEffect(() => {
    const observer = new ResizeObserver(entries => {
      const next = Math.floor(entries[0]?.contentRect.width || 0)
      if (next > 0) setWidth(next)
    })
    if (root.current) observer.observe(root.current)
    return () => observer.disconnect()
  }, [])
  return (
    <div ref={root} className="w-full min-w-0">
      {width > 0 && (
        <Geometry
          payload={payload}
          perspective="G"
          width={width}
          height={Math.max(280, Math.min(440, Math.round(width * 0.65)))}
        />
      )}
    </div>
  )
}
