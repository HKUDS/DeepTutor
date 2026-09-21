'use client'

import { useEffect, useState } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import ChatWorkspace from '@/features/chat/components/ChatWorkspace'
import { ActivityLibrary } from '@/components/learning/ActivityLibrary'

export default function WatchingPage() {
  const query = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const requested = query.get('create') === '1' || query.has('video')
  const [creating, setCreating] = useState(requested)
  if (requested && !creating) setCreating(true)
  useEffect(() => {
    if (!requested) return
    if (query.get('create') === '1') {
      const next = new URLSearchParams(query.toString())
      next.delete('create')
      router.replace(`${pathname}${next.size ? `?${next}` : ''}`, { scroll: false })
    }
  }, [pathname, query, requested, router])
  return creating || requested ? <ChatWorkspace watching /> : <ActivityLibrary kind="watching" onCreate={() => setCreating(true)} />
}
