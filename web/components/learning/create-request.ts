'use client'

import { useEffect, useRef } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'

/** Opens creation when a link arrives with `?create=1`, then drops the flag from the URL. */
export function useCreateRequest(open: () => void) {
  const router = useRouter()
  const pathname = usePathname()
  const query = useSearchParams()
  const openRef = useRef(open)
  useEffect(() => { openRef.current = open }, [open])
  const consumed = useRef(false)
  useEffect(() => {
    if (query.get('create') !== '1') { consumed.current = false; return }
    if (consumed.current) return
    consumed.current = true
    openRef.current()
    const next = new URLSearchParams(query.toString())
    next.delete('create')
    router.replace(`${pathname}${next.size ? `?${next}` : ''}`, { scroll: false })
  }, [pathname, query, router])
}

export function requestedLearningCreation() {
  return typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('create') === '1'
}
