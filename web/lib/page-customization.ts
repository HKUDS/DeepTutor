import type { TFunction } from 'i18next'

export const STARTER_GROUPS = ['explain', 'solve', 'practice', 'plan', 'research'] as const
export type StarterGroup = (typeof STARTER_GROUPS)[number]
export interface StarterPrompt {
  label: string
  prompt: string
}
export interface ComposerControls {
  skills: boolean
  mcp: boolean
  partners: boolean
  preferences: boolean
  voice: boolean
}
export interface ChatPageCustomization {
  hidden_modes: string[]
  controls: ComposerControls
  starters: Partial<Record<StarterGroup, StarterPrompt[]>>
}
export interface LearningPageCustomization {
  hidden_features: string[]
}
export interface PageCustomization {
  chat: ChatPageCustomization
  learning: LearningPageCustomization
}
export const DEFAULT_PAGE_CUSTOMIZATION: PageCustomization = {
  chat: {
    hidden_modes: [],
    controls: { skills: true, mcp: true, partners: true, preferences: true, voice: true },
    starters: {},
  },
  learning: { hidden_features: [] },
}
export function starterPrompts(
  chat: ChatPageCustomization,
  group: StarterGroup,
  t: TFunction
): StarterPrompt[] {
  return (
    chat.starters[group] ??
    [1, 2, 3, 4].map(n => ({
      label: t(`starters.${group}.${n}`),
      prompt: t(`starters.${group}.${n}.prompt`),
    }))
  )
}
export function toggleHidden(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter(item => item !== value) : [...values, value]
}
