import { apiFetch, apiUrl, expectJson } from './http'

export const FALLBACK_TOGGLEABLE_TOOLS = [
  { name: 'brainstorm', label: '头脑风暴' },
  { name: 'web_search', label: '网页搜索' },
  { name: 'paper_search', label: '论文搜索' },
  { name: 'reason', label: '深度推理' },
] as const

export interface ToolItem {
  name: string
  label: string
  toggleable: boolean
  enabled: boolean
}

interface ToolsListResponse {
  tools?: Array<{
    name: string
    description?: string
    description_i18n?: { zh?: string; en?: string }
    toggleable?: boolean
    enabled?: boolean
  }>
  enabled_optional_tools?: string[]
}

export async function listToggleableTools(): Promise<ToolItem[]> {
  try {
    const response = await apiFetch(apiUrl('/api/v1/tools'), { cache: 'no-store' })
    const payload = await expectJson<ToolsListResponse>(response)
    const fromCatalog = (payload.tools ?? [])
      .filter((tool) => tool.toggleable)
      .map((tool) => ({
        name: tool.name,
        label: tool.description_i18n?.zh || tool.description || tool.name,
        toggleable: true,
        enabled: Boolean(tool.enabled),
      }))
    if (fromCatalog.length > 0) return fromCatalog
    const enabled = new Set(payload.enabled_optional_tools ?? [])
    return FALLBACK_TOGGLEABLE_TOOLS.map((tool) => ({
      name: tool.name,
      label: tool.label,
      toggleable: true,
      enabled: enabled.size === 0 ? true : enabled.has(tool.name),
    }))
  } catch {
    return FALLBACK_TOGGLEABLE_TOOLS.map((tool) => ({
      name: tool.name,
      label: tool.label,
      toggleable: true,
      enabled: true,
    }))
  }
}
