import { describe, expect, it } from 'vitest'
import { moduleRouteAvailable, type ModuleStatus } from '@/hooks/useModules'

const reading: ModuleStatus = {
  id: 'reading', installed: false, enabled: false, ready: false,
  navigation: ['/learning/reading', '/learning/watching'], issues: [],
}
describe('module navigation ownership', () => {
  it('blocks absent module pages including nested direct URLs', () => {
    expect(moduleRouteAvailable('/learning/reading/materials/item', [reading])).toBe(false)
    expect(moduleRouteAvailable('/learning/watching', [reading])).toBe(false)
    expect(moduleRouteAvailable('/chat', [reading])).toBe(true)
    expect(moduleRouteAvailable('/learning/reading-list', [reading])).toBe(true)
  })
  it('distinguishes enabled modules from execution readiness', () => {
    expect(moduleRouteAvailable('/learning/reading', [{ ...reading, installed: true, enabled: true }])).toBe(true)
    expect(moduleRouteAvailable('/learning/reading', [{ ...reading, installed: true }])).toBe(false)
  })
})
