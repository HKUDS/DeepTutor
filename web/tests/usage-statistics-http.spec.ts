import { afterEach, expect, it, vi } from 'vitest'
import { fetchUsageStatistics } from '@/lib/usage-statistics'

afterEach(() => vi.unstubAllGlobals())

it('keeps actionable HTTP refusal details from the actual usage request', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    detail: 'Workspace access was revoked. Select an accessible workspace.',
  }), { status: 403, headers: { 'x-request-id': 'usage-refused' } })))
  await expect(fetchUsageStatistics(2026)).rejects.toMatchObject({
    message: 'Workspace access was revoked. Select an accessible workspace.',
    status: 403,
    correlationId: 'usage-refused',
  })
})

it('reports non-JSON proxy failures without exposing the proxy page as usage data', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>private proxy diagnostic</html>', {
    status: 502, statusText: 'Bad Gateway',
  })))
  await expect(fetchUsageStatistics(2026)).rejects.toMatchObject({ message: 'Bad Gateway', status: 502 })
})
