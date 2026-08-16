import { apiFetch, apiUrl, expectJson } from './http'

export const TOOL_SHORT_LABELS: Record<string, { zh: string; en: string }> = {
  brainstorm: { zh: '头脑风暴', en: 'Brainstorm' },
  web_search: { zh: '网页搜索', en: 'Web search' },
  paper_search: { zh: '论文搜索', en: 'Paper search' },
  reason: { zh: '深度推理', en: 'Deep reason' },
  geogebra_analysis: { zh: 'GeoGebra 分析', en: 'GeoGebra analysis' },
  imagegen: { zh: '图像生成', en: 'Image generation' },
  videogen: { zh: '视频生成', en: 'Video generation' },
}

export const FALLBACK_TOGGLEABLE_TOOLS = [
  { name: 'brainstorm', label: '头脑风暴', labels: TOOL_SHORT_LABELS.brainstorm },
  { name: 'web_search', label: '网页搜索', labels: TOOL_SHORT_LABELS.web_search },
  { name: 'paper_search', label: '论文搜索', labels: TOOL_SHORT_LABELS.paper_search },
  { name: 'reason', label: '深度推理', labels: TOOL_SHORT_LABELS.reason },
] as const

export interface ToolItem {
  name: string
  label: string
  labels: { zh?: string; en?: string }
  descriptions: { zh?: string; en?: string }
  toggleable: boolean
  enabled: boolean
  comingSoon: boolean
}

interface ToolsListResponse {
  tools?: Array<{
    name: string
    description?: string
    description_i18n?: { zh?: string; en?: string }
    toggleable?: boolean
    enabled?: boolean
    coming_soon?: boolean
  }>
  enabled_optional_tools?: string[]
}

function fallbackTools(enabledNames?: string[]): ToolItem[] {
  const enabled = new Set(enabledNames ?? [])
  const allOn = enabled.size === 0
  return FALLBACK_TOGGLEABLE_TOOLS.map((tool) => ({
    name: tool.name,
    label: tool.label,
    labels: { ...tool.labels },
    descriptions: {},
    toggleable: true,
    enabled: allOn ? true : enabled.has(tool.name),
    comingSoon: false,
  }))
}

export function toolLabel(tool: ToolItem, language: 'zh' | 'en'): string {
  return tool.labels[language] || tool.label || tool.name
}

export async function listToggleableTools(): Promise<ToolItem[]> {
  try {
    const response = await apiFetch(apiUrl('/api/v1/tools'), { cache: 'no-store' })
    const payload = await expectJson<ToolsListResponse>(response)
    const fromCatalog = (payload.tools ?? [])
      .filter((tool) => tool.toggleable || tool.coming_soon)
      .map((tool) => {
        const short = TOOL_SHORT_LABELS[tool.name]
        const zh = short?.zh || tool.name
        const en = short?.en || tool.name
        return {
          name: tool.name,
          label: zh,
          labels: { zh, en },
          descriptions: {
            zh: tool.description_i18n?.zh || tool.description || '',
            en: tool.description_i18n?.en || tool.description || '',
          },
          toggleable: Boolean(tool.toggleable),
          enabled: Boolean(tool.enabled),
          comingSoon: Boolean(tool.coming_soon),
        }
      })
    if (fromCatalog.length > 0) return fromCatalog
    return fallbackTools(payload.enabled_optional_tools)
  } catch {
    return fallbackTools()
  }
}

export async function setEnabledOptionalTools(names: string[]): Promise<string[]> {
  const response = await apiFetch('/api/v1/settings/enabled-tools', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled_tools: names }),
  })
  const payload = await expectJson<{ enabled_optional_tools?: string[] }>(response)
  return payload.enabled_optional_tools ?? names
}
