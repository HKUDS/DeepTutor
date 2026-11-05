'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch, apiUrl } from '@/lib/api'

export interface ModuleStatus {
  id: string
  installed: boolean
  enabled: boolean
  ready: boolean
  navigation: string[]
  issues: string[]
}

export function moduleRouteAvailable(path: string, modules: ModuleStatus[]): boolean {
  const owners = modules.filter(module => module.navigation.some(
    prefix => path === prefix || path.startsWith(`${prefix}/`)
  ))
  return owners.length === 0 || owners.every(module => module.installed && module.enabled)
}

// One deployment inventory request serves the sidebar, route gate and runtimes.
// A focus/retry refresh observes a server restarted with a different selection.
let pending: Promise<ModuleStatus[]> | null = null
function readModules() {
  if (!pending) {
    pending = apiFetch(apiUrl('/api/modules'))
      .then(async response => {
        if (!response.ok) throw new Error('Module inventory unavailable')
        const result = await response.json() as { modules: ModuleStatus[] }
        return result.modules
      })
  }
  return pending
}

export function useModules() {
  const [modules, setModules] = useState<ModuleStatus[] | null>(null)
  const [error, setError] = useState(false)
  const [revision, setRevision] = useState(0)
  const reload = useCallback(() => {
    pending = null
    setError(false)
    setRevision(value => value + 1)
  }, [])
  useEffect(() => {
    let active = true
    void readModules()
      .then(result => { if (active) setModules(result) })
      .catch(() => { if (active) setError(true) })
    window.addEventListener('focus', reload)
    return () => { active = false; window.removeEventListener('focus', reload) }
  }, [revision, reload])
  return { modules, error, reload, available: (path: string) => modules !== null && moduleRouteAvailable(path, modules) }
}
