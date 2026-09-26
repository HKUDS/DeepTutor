import { BookOpen, BookText, Clapperboard, ClipboardCheck, Route, type LucideIcon } from 'lucide-react'
import type { LearningKind } from '@/lib/learning-dashboard'
import { BOOKS_HOME, MASTERY_HOME, PRACTICE_HOME, READING_HOME, WATCHING_HOME } from '@/lib/learning-routes'

export interface LearningSurface {
  kind: LearningKind | "practice"
  href: string
  /** Product copy — every field here is a translation key, never rendered raw. */
  title: string
  /** The one line that fits on a card. */
  description: string
  /** What the surface actually does, for someone who has never opened it. */
  intro: string
  /** Three capabilities, each true of the shipped feature. */
  highlights: readonly [string, string, string]
  /** Plural key for how much the learner already has here. */
  unit: string
  icon: LucideIcon
  /**
   * Identity hue. Per-surface colour is confined to the icon tile: everything
   * else on the card is theme tokens, so four surfaces read as one page.
   */
  accent: string
}

export const LEARNING_SURFACES: readonly LearningSurface[] = [
  {
    kind: 'books',
    href: BOOKS_HOME,
    title: 'Books',
    description: 'Generate, browse and study your AI-authored books.',
    intro:
      'Name a subject and DeepTutor writes you a book on it — a spine of chapters first, then each page written out in full.',
    highlights: [
      'Edit the chapter spine before a word is written',
      'Pages carry figures, timelines, quizzes and flash cards',
      'Your place is kept, and the tutor reads along with you',
    ],
    unit: '{{count}} books',
    icon: BookOpen,
    accent: 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
  },
  {
    kind: 'mastery',
    href: MASTERY_HOME,
    title: 'Mastery Path',
    description: 'Learn through a living mastery map',
    intro:
      'Say what you want to master. You and the tutor settle the outline together, and it becomes a map of knowledge points to work through.',
    highlights: [
      'The outline is agreed in conversation before study begins',
      'Each knowledge point tracks its own mastery',
      'Reviews fall due on their own schedule',
    ],
    unit: '{{count}} paths',
    icon: Route,
    accent: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
  },
  {
    kind: 'practice',
    href: PRACTICE_HOME,
    title: 'Practice',
    description: 'Your question bank, mistakes and daily reviews.',
    intro: 'Bring questions from every learning activity together, import your own, and build lasting recall through daily practice.',
    highlights: [
      'Questions from chat, books and mastery paths collect automatically',
      'Import your own questions from spreadsheets',
      'Mistakes return when they are due for review',
    ],
    unit: '{{count}} questions',
    icon: ClipboardCheck,
    accent: 'bg-sky-500/10 text-sky-600 dark:text-sky-400',
  },
  {
    kind: 'reading',
    href: READING_HOME,
    title: 'Immersive Reading',
    description: 'Read your materials with a tutor by your side.',
    intro:
      'Bring in PDFs, EPUBs, web pages, video or audio and read them here. Select any passage to ask about it.',
    highlights: [
      'Documents, web pages, video and audio in one library',
      'Answers name the place in the text they came from',
      'Highlights, notes and word explanations stay beside the text',
    ],
    unit: '{{count}} collections',
    icon: BookText,
    accent: 'bg-sky-500/10 text-sky-600 dark:text-sky-400',
  },
  {
    kind: 'watching',
    href: WATCHING_HOME,
    title: 'Immersive Watching',
    description: 'Watch videos with a grounded AI companion.',
    intro:
      'Play a video with the tutor watching alongside you, and ask about whatever is on screen as it runs.',
    highlights: [
      'Ask about any moment while the video plays',
      'Jump straight to a line of the transcript',
      'Notes are stamped with the moment you took them',
    ],
    unit: '{{count}} videos',
    icon: Clapperboard,
    accent: 'bg-violet-500/10 text-violet-600 dark:text-violet-400',
  },
] as const

export const learningSurface = (kind: LearningKind): LearningSurface =>
  LEARNING_SURFACES.find(surface => surface.kind === kind)!
