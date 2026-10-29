'use client'

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { apiFetch, apiUrl } from '@/lib/api'
import { DEFAULT_PAGE_CUSTOMIZATION, type PageCustomization } from '@/lib/page-customization'

interface PageCustomizationState {
  value: PageCustomization
  loading: boolean
  error: boolean
  reload: () => void
  save: <K extends keyof PageCustomization>(
    section: K,
    value: PageCustomization[K]
  ) => Promise<void>
}
const Context = createContext<PageCustomizationState>({
  value: DEFAULT_PAGE_CUSTOMIZATION,
  loading: false,
  error: false,
  reload: () => {},
  save: async () => {
    throw new Error('Page customization provider missing')
  },
})

/** Account-scoped API persistence; no private prompts cached in browser storage. */
export function PageCustomizationProvider({ children }: { children: ReactNode }) {
  const [value, setValue] = useState(DEFAULT_PAGE_CUSTOMIZATION)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const revision = useRef(0)
  const mounted = useRef(true)
  const reload = useCallback(() => {
    const request = ++revision.current
    void apiFetch(apiUrl('/api/settings/page-customization'), {
      cache: 'no-store',
      signal: AbortSignal.timeout(15000),
    })
      .then(async response => {
        if (!response.ok) throw new Error('Could not load page customization')
        const next = (await response.json()) as PageCustomization
        if (mounted.current && revision.current === request) {
          setValue(next)
          setError(false)
        }
      })
      .catch(() => {
        if (mounted.current && revision.current === request) setError(true)
      })
      .finally(() => {
        if (mounted.current && revision.current === request) setLoading(false)
      })
  }, [])
  useEffect(() => {
    mounted.current = true
    reload()
    window.addEventListener('focus', reload)
    return () => {
      mounted.current = false
      window.removeEventListener('focus', reload)
    }
  }, [reload])
  const save = useCallback(
    async <K extends keyof PageCustomization>(section: K, next: PageCustomization[K]) => {
      ++revision.current // A stale GET must not overwrite a successful save.
      const response = await apiFetch(apiUrl(`/api/settings/page-customization/${section}`), {
        method: 'PUT',
        signal: AbortSignal.timeout(15000),
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(next),
      })
      if (!response.ok) throw new Error('Could not save page customization')
      const saved = (await response.json()) as PageCustomization
      if (mounted.current) {
        ++revision.current
        setValue(saved)
        setError(false)
        setLoading(false)
      }
    },
    []
  )
  const state = useMemo(
    () => ({ value, loading, error, reload, save }),
    [value, loading, error, reload, save]
  )
  return <Context.Provider value={state}>{children}</Context.Provider>
}
export function usePageCustomization() {
  return useContext(Context)
}
