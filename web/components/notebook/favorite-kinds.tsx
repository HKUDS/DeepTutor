import { createElement } from 'react'
import {
  Bookmark,
  BookOpen,
  Bot,
  Calculator,
  FileQuestion,
  FileText,
  GraduationCap,
  MessageSquare,
  Search,
  Video,
  type LucideIcon,
} from 'lucide-react'
import { FAVORITE_LABELS } from '@/lib/favorite-content'

/** One icon and label per kind of favorite, shared by every surface that
 *  shows one: the collection page, the note picker and the card on a page.
 *  The tint lives in favorites.css under `[data-kind]`. */
const ICONS: Record<string, LucideIcon> = {
  chat: MessageSquare,
  tutorbot: Bot,
  research: Search,
  reading: BookOpen,
  video_learning: Video,
  question: FileQuestion,
  solve: Calculator,
  co_writer: FileText,
  guided_learning: GraduationCap,
}

export function favoriteIcon(kind: string): LucideIcon {
  return ICONS[kind] || Bookmark
}

export function favoriteLabel(kind: string): string {
  return FAVORITE_LABELS[kind] || 'Favorite content'
}

/** The kind's icon on its tinted tile. */
export function FavoriteKindIcon({ kind, size = 16 }: { kind: string; size?: number }) {
  return (
    <span className="dt-fav-kind" data-kind={kind} aria-hidden>
      {createElement(favoriteIcon(kind), { size, strokeWidth: 1.7 })}
    </span>
  )
}
