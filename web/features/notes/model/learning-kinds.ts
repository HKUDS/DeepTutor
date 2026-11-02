import {
  BookOpen,
  CheckSquare,
  Image as ImageIcon,
  Layers,
  ListOrdered,
  ListTodo,
  Music,
  Network,
  Play,
  Shapes,
  Sigma,
  Waypoints,
  type LucideIcon,
} from 'lucide-react'

/** What a learning block can be made into. One list for the insert menu, a
 *  block's own kind switcher and Dito's "generate here" menu, so the three
 *  never offer different things. */
export interface LearningKind {
  kind: string
  label: string
  alias: string
  Icon: LucideIcon
  /** What the prompt box asks for. */
  placeholder: string
}

export const LEARNING_KINDS: LearningKind[] = [
  {
    kind: 'mermaid',
    label: 'Diagram',
    alias: '图解',
    Icon: Network,
    placeholder: 'What should the diagram show?',
  },
  {
    kind: 'timeline',
    label: 'Timeline',
    alias: '时间线',
    Icon: ListOrdered,
    placeholder: 'Which events, in what span?',
  },
  {
    kind: 'concept_map',
    label: 'Concept map',
    alias: '概念图',
    Icon: Waypoints,
    placeholder: 'Which concepts should it connect?',
  },
  {
    kind: 'quiz',
    label: 'Quiz me',
    alias: '测验',
    Icon: CheckSquare,
    placeholder: 'What should the questions check?',
  },
  {
    kind: 'flashcards',
    label: 'Flash Cards',
    alias: '闪卡',
    Icon: Layers,
    placeholder: 'What should the cards help you remember?',
  },
  {
    kind: 'image',
    label: 'Generate image',
    alias: '生成图片',
    Icon: ImageIcon,
    placeholder: 'Describe the picture',
  },
  {
    kind: 'animation',
    label: 'Animation',
    alias: '动画',
    Icon: Play,
    placeholder: 'What should the animation explain?',
  },
  {
    kind: 'geogebra',
    label: 'Geometry',
    alias: '几何',
    Icon: Sigma,
    placeholder: 'Which figure or construction?',
  },
  {
    kind: 'audio',
    label: 'Podcast',
    alias: '播客',
    Icon: Music,
    placeholder: 'What should the episode cover?',
  },
  {
    kind: 'research',
    label: 'Research',
    alias: '研究',
    Icon: BookOpen,
    placeholder: 'What should be researched?',
  },
  {
    kind: 'task',
    label: 'Linked task',
    alias: '任务',
    Icon: ListTodo,
    placeholder: 'What needs doing?',
  },
]

/** Kinds a block can only be filled with, never picked from a menu. */
const LEGACY: Record<string, { label: string; Icon: LucideIcon }> = {
  visualization: { label: 'Visualization', Icon: Shapes },
  media: { label: 'Media', Icon: ImageIcon },
  code: { label: 'Code', Icon: Sigma },
}

export function learningKind(kind: string): LearningKind {
  return (
    LEARNING_KINDS.find(k => k.kind === kind) ?? {
      kind,
      alias: '',
      placeholder: 'What should this block teach?',
      ...(LEGACY[kind] ?? { label: kind, Icon: Shapes }),
    }
  )
}

/** Whether a block already holds generated material (and its prompt can fold away). */
export function hasLearningContent(
  kind: string,
  markdown: string,
  payload: Record<string, unknown>
) {
  if (kind === 'task') return Boolean(payload.taskId)
  return Boolean(
    markdown.trim() ||
    [
      'questions',
      'cards',
      'events',
      'nodes',
      'commands',
      'sub_topics',
      'artifacts',
      'workspace_items',
    ].some(key => Array.isArray(payload[key]) && (payload[key] as unknown[]).length) ||
    payload.graph ||
    payload.renderer
  )
}

/** The settings a block's own Generate sends besides its prompt. */
export function learningGenerationConfig(
  kind: string,
  data: string
): Record<string, unknown> | undefined {
  if (kind !== 'audio') return undefined
  let generation: Record<string, unknown> = {}
  try {
    generation = (JSON.parse(data || '{}').generation || {}) as Record<string, unknown>
  } catch {
    /* Malformed data keeps the defaults. */
  }
  return {
    target_minutes: Number(generation.target_minutes) || 1,
    ...(generation.host_voice ? { host_voice: generation.host_voice } : {}),
    ...(generation.expert_voice ? { expert_voice: generation.expert_voice } : {}),
  }
}
