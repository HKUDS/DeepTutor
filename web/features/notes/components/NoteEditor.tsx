'use client'

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react'
import dynamic from 'next/dynamic'
import type { FavoriteSnapshot } from '@/lib/favorite-content'
import NoteFavoriteBlock from './NoteFavoriteBlock'
import {
  createExtension,
  BlockNoteSchema,
  BlockNoteEditor,
  defaultBlockSpecs,
  defaultInlineContentSpecs,
  type PartialBlock,
} from '@blocknote/core'
import { SideMenuExtension, SuggestionMenu } from '@blocknote/core/extensions'
import { en, zh } from '@blocknote/core/locales'
import {
  BlockNoteViewRaw,
  useCreateBlockNote,
  createReactBlockSpec,
  createReactInlineContentSpec,
  SuggestionMenuController,
  FormattingToolbarController,
  SideMenuController,
  getDefaultReactSlashMenuItems,
  useExtension,
  useExtensionState,
  useActiveStyles,
} from '@blocknote/react'
import { useTranslation } from 'react-i18next'
import {
  Bold,
  Italic,
  Underline,
  Strikethrough,
  Code,
  Sparkles,
  GripVertical,
  ArrowUp,
  ArrowDown,
  Plus,
  Trash2,
  Copy,
  RefreshCcw,
  Upload,
  Link as LinkIcon,
  Info,
  ListTree,
  Columns2,
  Bookmark,
  Globe,
  FileCode,
  CalendarDays,
  Table2,
  FileText,
  ArrowUpRight,
  Image as ImageIcon,
  Film,
  Music,
  Heading1,
  Heading2,
  Heading3,
  Sigma,
  BookOpen,
  CheckSquare,
  Network,
  Layers,
  Play,
  ListOrdered,
  ChevronDown,
  PenLine,
  Minimize2,
  Maximize2,
  Languages,
  MessageSquareText,
} from 'lucide-react'
import Tooltip from '@/shared/ui/Tooltip'
import { subscribeToThemeChanges } from '@/lib/theme'
import { parseNoteMarkdown } from '../model/markdown'
import { insertNoteClips, type NoteClipInput } from '../model/clip-editing'
import { listNotes, type NoteBlock, type NotePage, type NoteSuggestion } from '@/lib/notes-api'
import { apiFetch, apiUrl } from '@/lib/api'
import { inputRules, InputRule } from '@tiptap/pm/inputrules'
import { closeHistory } from '@tiptap/pm/history'
import '@blocknote/core/style.css'
import './notes.css'
import NoteMath from './NoteMath'
import NoteInlineReviews from './NoteInlineReviews'
import useNoteBlockDrag from './useNoteBlockDrag'
import { noteFile } from './NoteFile'
import { noteUpload, activeNoteUploads } from './NoteUpload'
import { noteMediaAccept, noteMediaType } from '../model/media'
import {
  basicPreviewKinds,
  isBasicPreviewKind,
  type BlockPreviewKind,
} from '../model/block-previews'
import NoteInsertMenu, { type NoteMenuItem } from './NoteInsertMenu'
import NoteThreadMarkers from './NoteThreadMarkers'
import { LEARNING_KINDS, learningGenerationConfig } from '../model/learning-kinds'
import type { NoteThreadView } from '../model/threads'
import {
  callout,
  toggleHeading,
  noteColumn,
  noteColumns,
  tableOfContents,
  webCard,
  htmlEmbed,
  taskView,
  noteDate,
} from './NoteRichBlocks'

const Markdown = dynamic(() => import('@/components/common/MarkdownRenderer'), { ssr: false })
const LearningContent = dynamic(() => import('./NoteLearningContent'), { ssr: false })

const math = createReactBlockSpec(
  { type: 'math', propSchema: { formula: { default: '' } }, content: 'none' },
  {
    render: function MathBlock({ block, editor }) {
      const { t } = useTranslation()
      const [editing, setEditing] = useState(!block.props.formula)
      return (
        <div className="dt-note-math" contentEditable={false}>
          {editing ? (
            <input
              autoFocus
              aria-label={t('Math formula')}
              value={block.props.formula}
              onChange={e => editor.updateBlock(block, { props: { formula: e.target.value } })}
              onBlur={() => {
                if (block.props.formula.trim()) setEditing(false)
              }}
              onKeyDown={e => {
                if (e.key === 'Enter' || e.key === 'Escape') {
                  e.preventDefault()
                  setEditing(false)
                  editor.focus()
                }
              }}
            />
          ) : (
            <button onClick={() => setEditing(true)}>
              <NoteMath formula={block.props.formula} display />
            </button>
          )}
        </div>
      )
    },
  }
)
const clip = createReactBlockSpec(
  {
    type: 'clip',
    content: 'none',
    propSchema: {
      title: { default: '' },
      markdown: { default: '' },
      sourceUrl: { default: '' },
      sourceId: { default: '' },
      favoriteType: { default: '' },
      summary: { default: '' },
      metadata: { default: '{}' },
      expanded: { default: false },
    },
  },
  {
    render: function ClipBlock({ block, editor }) {
      const { t } = useTranslation()
      if (block.props.favoriteType || /^\/notebooks?\//.test(block.props.sourceUrl))
        return (
          <NoteFavoriteBlock
            title={block.props.title}
            markdown={block.props.markdown}
            sourceUrl={block.props.sourceUrl}
            type={block.props.favoriteType}
            summary={block.props.summary}
            metadata={block.props.metadata}
            expanded={block.props.expanded}
            onActivate={() => {
              if (editor.getTextCursorPosition().block.id !== block.id)
                editor.setTextCursorPosition(block.id, 'start')
            }}
            onExpanded={expanded =>
              editor.transact(tr => {
                // Reading a saved excerpt is view state, not a content edit.
                tr.setMeta('addToHistory', false)
                editor.updateBlock(block, { props: { expanded } })
              })
            }
          />
        )
      return (
        <div className="dt-note-clip" contentEditable={false}>
          <details open>
            <summary>{block.props.title || t('Excerpt')}</summary>
            <Markdown content={block.props.markdown} />
          </details>
          {block.props.sourceUrl && (
            <a data-note-source href={block.props.sourceUrl}>
              {t('Return to source')}
            </a>
          )}
        </div>
      )
    },
  }
)
const learning = createReactBlockSpec(
  {
    type: 'learning',
    content: 'none',
    propSchema: {
      kind: { default: 'mermaid' },
      prompt: { default: '' },
      markdown: { default: '' },
      data: { default: '{}' },
      sourceUrl: { default: '' },
    },
  },
  {
    render: ({ block, editor }) => (
      <LearningContent
        id={block.id}
        {...block.props}
        onChange={props => editor.updateBlock(block, { props })}
      />
    ),
  }
)
const pageLink = createReactInlineContentSpec(
  {
    type: 'pageLink',
    propSchema: { pageId: { default: '' }, title: { default: '' } },
    content: 'none',
  },
  {
    render: ({ inlineContent }) => (
      <a className="dt-note-link" href={`/co-writer/${inlineContent.props.pageId}`}>
        <FileText size={14} aria-hidden="true" />
        <span>{inlineContent.props.title}</span>
        <ArrowUpRight size={12} aria-hidden="true" />
      </a>
    ),
  }
)
const inlineMath = createReactInlineContentSpec(
  { type: 'inlineMath', propSchema: { formula: { default: '' } }, content: 'none' },
  {
    render: function InlineMath({ inlineContent, updateInlineContent }) {
      const { t } = useTranslation()
      const [edit, setEdit] = useState(false)
      return (
        <span contentEditable={false} className="dt-note-inline-math">
          {edit ? (
            <input
              aria-label={t('Math formula')}
              autoFocus
              value={inlineContent.props.formula}
              onChange={e =>
                updateInlineContent({ type: 'inlineMath', props: { formula: e.target.value } })
              }
              onBlur={() => setEdit(false)}
              onKeyDown={e => {
                if (e.key === 'Enter' || e.key === 'Escape') {
                  e.preventDefault()
                  setEdit(false)
                }
              }}
            />
          ) : (
            <button onClick={() => setEdit(true)}>
              <NoteMath formula={inlineContent.props.formula} />
            </button>
          )}
        </span>
      )
    },
  }
)
const noteInputRules = createExtension({
  key: 'note-input-rules',
  inputRules: [{ find: /^\$\$\s$/, replace: () => ({ type: 'math', props: { formula: '' } }) }],
  prosemirrorPlugins: [
    inputRules({
      rules: [
        new InputRule(/(?:^|[^$])\$([^$\n]+)\$$/, (state, match, start, end) => {
          const node = state.schema.nodes.inlineMath
          if (!node) return null
          const offset = match[0].startsWith('$') ? 0 : 1
          return state.tr.replaceWith(start + offset, end, node.create({ formula: match[1] }))
        }),
      ],
    }),
  ],
})
const schema = BlockNoteSchema.create({
  blockSpecs: {
    ...defaultBlockSpecs,
    file: noteFile(),
    math: math(),
    clip: clip(),
    learning: learning(),
    noteUpload: noteUpload(),
    callout: callout(),
    toggleHeading: toggleHeading(),
    noteColumn: noteColumn(),
    noteColumns: noteColumns(),
    tableOfContents: tableOfContents(),
    webCard: webCard(),
    htmlEmbed: htmlEmbed(),
    taskView: taskView(),
  },
  inlineContentSpecs: { ...defaultInlineContentSpecs, pageLink, inlineMath, noteDate },
})
/** Drop inline content a block type cannot hold. A stray string there (a model
 *  echoing "timeline" into a learning block) makes the editor reject the page. */
export function fitSchema(blocks: NoteBlock[]): NoteBlock[] {
  return blocks.map(block => {
    const spec = (schema.blockSchema as Record<string, { content?: string } | undefined>)[
      block.type
    ]
    const { content, ...rest } = block
    return {
      ...(spec?.content === 'none' ? rest : { ...rest, content }),
      children: fitSchema(block.children || []),
    } as NoteBlock
  })
}
/** Reuse the notebook's normal migration before clipping into an unopened legacy page. */
export function parseLegacyNoteContent(markdown: string): NoteBlock[] {
  const editor = BlockNoteEditor.create({ schema })
  try {
    return parseNoteMarkdown(markdown, text => editor.tryParseMarkdownToBlocks(text) as NoteBlock[])
  } finally {
    editor._tiptapEditor.destroy()
  }
}
export type NotesEditor = typeof schema.BlockNoteEditor
export interface NoteEditorHandle {
  blocks: () => NoteBlock[]
  setEditable: (editable: boolean) => void
  replace: (blocks: NoteBlock[]) => void
  parse: (markdown: string) => NoteBlock[]
  insertClip: (
    title: string,
    markdown: string,
    sourceUrl: string,
    sourceId?: string,
    favorite?: FavoriteSnapshot
  ) => void
  insertClips: (clips: NoteClipInput[]) => void
  focusBlock: (id: string) => void
  /** A learning block of ``kind`` right after ``blockId``; its id, or null. */
  insertLearningAfter: (blockId: string, kind: string, prompt: string) => string | null
  /** Keep the request a learning block is regenerated from as its prompt. */
  updateLearningPrompt: (blockId: string, prompt: string) => void
  /** The block the caret is in, for "ask Dito" from outside the page. */
  cursorBlockId: () => string | null
  hasBlock: (id: string) => boolean
}

/** Where a conversation is opened from, and what it starts with. */
export interface NoteAsk {
  blockId: string
  quote?: string
  prompt?: string
  /** Send the prompt straight away (a toolbar action) instead of drafting it. */
  autoSend?: boolean
  /** A knowledge base to search in this conversation. */
  knowledgeRef?: string
}

/** BlockNote nudges the side menu down by a guess at each heading level's
 *  line; the notebook's own type scale differs, so the handles measure the
 *  line themselves from the block's top instead. */
const SIDE_MENU_FLOATING = { useFloatingOptions: { middleware: [] } }

function Handles({ editor }: { editor: NotesEditor }) {
  const { t } = useTranslation()
  const handleRoot = useRef<HTMLDivElement>(null)
  const menu = useExtension(SideMenuExtension)
  const block = useExtensionState(SideMenuExtension, { selector: state => state?.block })
  const [open, setOpen] = useState(false)
  const drag = useNoteBlockDrag(editor)
  const blockId = block?.id
  // Centre the handles on the block's first line of text, whatever its type
  // and font; a card without text keeps them level with its top edge. The
  // side menu sits at the block's top (see SIDE_MENU_FLOATING), so the
  // offset is measured from there. Written onto the node rather than kept in
  // state: it is a measurement of the DOM, and the menu re-renders on hover.
  useLayoutEffect(() => {
    const root = handleRoot.current
    if (!blockId || !root) return
    root.style.transform = ''
    const outer = editor.domElement?.querySelector<HTMLElement>(
      `.bn-block-outer[data-id="${CSS.escape(blockId)}"]`
    )
    const content = outer?.querySelector<HTMLElement>(':scope > .bn-block > .bn-block-content')
    if (!outer || !content) return
    const top = outer.getBoundingClientRect().top
    const inline = content.querySelector<HTMLElement>('.bn-inline-content')
    let center = content.getBoundingClientRect().top - top + root.offsetHeight / 2
    if (inline) {
      const range = document.createRange()
      range.selectNodeContents(inline)
      const line = [...range.getClientRects()].find(rect => rect.height > 0)
      const box = inline.getBoundingClientRect()
      const style = getComputedStyle(inline)
      const lineHeight = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.5
      center = line ? line.top + line.height / 2 - top : box.top + lineHeight / 2 - top
    }
    root.style.transform = `translateY(${center - root.offsetHeight / 2}px)`
  }, [blockId, editor])
  // A menu left open by a click elsewhere would keep the handles frozen on
  // this block, and no other block would show its own.
  useEffect(() => {
    if (!open) return
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent && event.key !== 'Escape') return
      if (event instanceof PointerEvent && handleRoot.current?.contains(event.target as Node))
        return
      setOpen(false)
      menu.unfreezeMenu()
    }
    document.addEventListener('pointerdown', close, true)
    document.addEventListener('keydown', close, true)
    return () => {
      document.removeEventListener('pointerdown', close, true)
      document.removeEventListener('keydown', close, true)
    }
  }, [menu, open])
  if (!block) return null
  return (
    <div ref={handleRoot} className="dt-note-handle">
      <Tooltip label={t('Add below · Option-click to add above')}>
        <button
          aria-label={t('Add block')}
          onClick={e => {
            const [next] = editor.insertBlocks(
              [{ type: 'paragraph' }],
              block.id,
              e.altKey ? 'before' : 'after'
            )
            if (next) editor.setTextCursorPosition(next.id, 'start')
            editor.getExtension(SuggestionMenu)?.openSuggestionMenu('/')
          }}
        >
          <Plus size={16} />
        </button>
      </Tooltip>
      <Tooltip label={t('Drag or open block menu')}>
        <button
          aria-label={t('Drag or open block menu')}
          className="dt-note-drag-handle"
          onPointerDown={event => drag.start(event, block.id)}
          onPointerMove={drag.move}
          onPointerUp={drag.end}
          onPointerCancel={drag.cancel}
          onClick={() => {
            if (drag.consumeClick()) return
            if (!open) editor.setTextCursorPosition(block.id, 'start')
            setOpen(!open)
            if (!open) menu.freezeMenu()
            else menu.unfreezeMenu()
          }}
        >
          <GripVertical size={16} />
        </button>
      </Tooltip>
      {drag.indicator}
      {open && (
        <div
          className="dt-note-menu"
          onMouseLeave={() => {
            setOpen(false)
            menu.unfreezeMenu()
          }}
        >
          {block.type === 'learning' && block.props.kind !== 'task' && (
            // A generated block shows only its material; asking for another
            // version opens a conversation with the old request to edit.
            <button
              onClick={() => {
                const props = block.props as { kind: string; prompt: string; data: string }
                editor.domElement
                  ?.querySelector(`[data-id="${CSS.escape(block.id)}"]`)
                  ?.dispatchEvent(
                    new CustomEvent('note-regenerate', {
                      bubbles: true,
                      detail: {
                        blockId: block.id,
                        kind: props.kind,
                        prompt: props.prompt,
                        config: learningGenerationConfig(props.kind, props.data),
                      },
                    })
                  )
                setOpen(false)
                menu.unfreezeMenu()
              }}
            >
              <RefreshCcw size={14} />
              {t('Regenerate…')}
            </button>
          )}
          {(['up', 'down'] as const).map(direction => (
            <button
              key={direction}
              onClick={() => {
                editor.transact(tr => closeHistory(tr))
                if (direction === 'up') editor.moveBlocksUp(block.id)
                else editor.moveBlocksDown(block.id)
                editor.transact(tr => closeHistory(tr))
                setOpen(false)
                menu.unfreezeMenu()
              }}
            >
              {direction === 'up' ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
              {t(direction === 'up' ? 'Move up' : 'Move down')}
            </button>
          ))}
          {(['nest', 'unnest'] as const).map(action => (
            <button
              key={action}
              disabled={action === 'nest' ? !editor.canNestBlock() : !editor.canUnnestBlock()}
              onClick={() => {
                editor.transact(tr => closeHistory(tr))
                if (action === 'nest') editor.nestBlock()
                else editor.unnestBlock()
                editor.transact(tr => closeHistory(tr))
                setOpen(false)
                menu.unfreezeMenu()
                editor.focus()
              }}
            >
              <ListTree size={14} />
              {editor.dictionary.formatting_toolbar[action].tooltip}
            </button>
          ))}
          <button
            onClick={() => {
              const original = editor.getBlock(block.id)
              if (original) {
                const duplicate = JSON.parse(JSON.stringify(original))
                const rekey = (b: NoteBlock) => {
                  b.id = crypto.randomUUID()
                  b.children?.forEach(rekey)
                }
                rekey(duplicate)
                editor.insertBlocks([duplicate], block.id, 'after')
              }
              setOpen(false)
              menu.unfreezeMenu()
            }}
          >
            <Copy size={14} />
            {t('Duplicate')}
          </button>
          <button
            onClick={() => {
              editor.removeBlocks([block.id])
              setOpen(false)
              menu.unfreezeMenu()
            }}
          >
            <Trash2 size={14} />
            {t('Delete')}
          </button>
          {block.type === 'table' &&
            [
              'Add row',
              'Add column',
              'Remove last row',
              'Remove last column',
              'Toggle header row',
            ].map(action => (
              <button
                key={action}
                onClick={() => {
                  const table = editor.getBlock(block.id)
                  if (table?.type !== 'table') return
                  const content = structuredClone(table.content)
                  if (action === 'Add row')
                    content.rows.push({
                      cells: Array.from({ length: content.rows[0]?.cells.length || 2 }, () => []),
                    })
                  if (action === 'Add column') {
                    content.rows.forEach(r => {
                      if (r.cells.every(c => Array.isArray(c))) r.cells = [...r.cells, []]
                      else
                        r.cells = r.cells
                          .map(c =>
                            Array.isArray(c)
                              ? {
                                  type: 'tableCell' as const,
                                  props: {
                                    colspan: 1,
                                    rowspan: 1,
                                    backgroundColor: 'default',
                                    textColor: 'default',
                                    textAlignment: 'left' as const,
                                  },
                                  content: c,
                                }
                              : c
                          )
                          .concat([
                            {
                              type: 'tableCell',
                              props: {
                                colspan: 1,
                                rowspan: 1,
                                backgroundColor: 'default',
                                textColor: 'default',
                                textAlignment: 'left',
                              },
                              content: [],
                            },
                          ])
                    })
                    content.columnWidths.push(undefined)
                  }
                  if (action === 'Remove last row' && content.rows.length > 1) content.rows.pop()
                  if (action === 'Remove last column' && content.rows[0]?.cells.length > 1) {
                    content.rows.forEach(r => r.cells.pop())
                    content.columnWidths.pop()
                  }
                  if (action === 'Toggle header row')
                    content.headerRows = content.headerRows ? 0 : 1
                  editor.updateBlock(table, { content })
                  setOpen(false)
                  menu.unfreezeMenu()
                }}
              >
                {t(action)}
              </button>
            ))}
          {block.type === 'codeBlock' && (
            <button
              onClick={() => {
                const code = editor.getBlock(block.id)
                const text = Array.isArray(code?.content)
                  ? code.content.map(c => ('text' in c ? c.text : '')).join('')
                  : ''
                handleRoot.current?.dispatchEvent(
                  new CustomEvent('note-generate', {
                    bubbles: true,
                    detail: {
                      kind: 'code',
                      prompt: `Use exec only if it is enabled to run this code and report output in a comment. Do not claim execution if unavailable.\n${text}`,
                      blockId: block.id,
                    },
                  })
                )
                setOpen(false)
                menu.unfreezeMenu()
              }}
            >
              {t('Run code')}
            </button>
          )}
          {editor.schema.blockSchema[block.type as keyof typeof schema.blockSchema].content ===
            'inline' &&
            (['paragraph', 'heading', 'bulletListItem', 'checkListItem'] as const).map(type => (
              <button
                key={type}
                onClick={() => {
                  editor.updateBlock(block.id, { type })
                  setOpen(false)
                  menu.unfreezeMenu()
                }}
              >
                {t(
                  {
                    paragraph: 'Text',
                    heading: 'Heading',
                    bulletListItem: 'Bullet list',
                    checkListItem: 'To-do list',
                  }[type]
                )}
              </button>
            ))}
        </div>
      )}
    </div>
  )
}

export default function NoteEditor({
  page,
  onChange,
  onReady,
  onAI,
  suggestions,
  reviewBusy,
  reviewErrors,
  onReview,
  onDiscuss,
  onContinueResearch,
  threads,
  activeThread,
  threadsInteractive,
  onOpenThread,
  onDeleteThread,
  onFocusBlock,
}: {
  page: NotePage
  suggestions: NoteSuggestion[]
  reviewBusy: boolean
  reviewErrors?: Record<string, string>
  onContinueResearch: (suggestion: NoteSuggestion) => void
  onReview: (suggestion: NoteSuggestion, accept: boolean) => void
  onDiscuss: (suggestion: NoteSuggestion) => void
  onChange: (blocks: NoteBlock[]) => void
  onReady: (handle: NoteEditorHandle) => void
  onAI: (ask: NoteAsk) => void
  threads: NoteThreadView[]
  activeThread: { sessionId: string | null; blockId: string } | null
  threadsInteractive: boolean
  onOpenThread: (sessionId: string) => void
  onDeleteThread: (sessionId: string) => Promise<void>
  /** The block the learner clicked or moved the cursor into. */
  onFocusBlock?: (blockId: string) => void
}) {
  const { t, i18n } = useTranslation()
  const theme = useSyncExternalStore<'light' | 'dark'>(
    subscribeToThemeChanges,
    () => (document.documentElement.classList.contains('dark') ? 'dark' : 'light'),
    () => 'light'
  )
  const ready = useRef(false)
  const container = useRef<HTMLDivElement>(null)
  const [containerEl, setContainerEl] = useState<HTMLDivElement | null>(null)
  const attachContainer = useCallback((el: HTMLDivElement | null) => {
    container.current = el
    setContainerEl(el)
  }, [])
  // BlockNote hides the block handles whenever the page scrolls and shows
  // them again only on the next mouse move; once the scroll settles, show
  // them for the block under a pointer that has not moved.
  useEffect(() => {
    if (!containerEl) return
    let pointer: { x: number; y: number } | null = null
    let timer = 0
    const track = (event: PointerEvent) => {
      if (event.pointerType === 'mouse') pointer = { x: event.clientX, y: event.clientY }
    }
    const settle = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(() => {
        if (!pointer) return
        const box = containerEl.getBoundingClientRect()
        if (pointer.y < box.top || pointer.y > box.bottom) return
        document.elementFromPoint(pointer.x, pointer.y)?.dispatchEvent(
          new MouseEvent('mousemove', {
            bubbles: true,
            clientX: pointer.x,
            clientY: pointer.y,
          })
        )
      }, 140)
    }
    window.addEventListener('pointermove', track, { passive: true })
    document.addEventListener('scroll', settle, { capture: true, passive: true })
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('pointermove', track)
      document.removeEventListener('scroll', settle, { capture: true })
    }
  }, [containerEl])
  const uploadInput = useRef<HTMLInputElement>(null)
  const uploadAnchor = useRef<string | null>(null)
  const uploadRetry = useRef<string | null>(null)
  const initialized = useRef(false)
  const latest = useRef({ onChange, onReady, onAI, onFocusBlock })
  useLayoutEffect(() => {
    latest.current = { onChange, onReady, onAI, onFocusBlock }
  }, [onChange, onReady, onAI, onFocusBlock])
  const editor = useCreateBlockNote(
    {
      schema,
      tables: { headers: true },
      extensions: [noteInputRules],
      dictionary: (() => {
        const base = i18n.language.startsWith('zh') ? zh : en
        return {
          ...base,
          placeholders: {
            ...base.placeholders,
            default: t('Write, press / to insert, or Space to ask Dito'),
          },
        }
      })(),
      initialContent: page.blocks?.length
        ? (fitSchema(page.blocks) as PartialBlock<
            typeof schema.blockSchema,
            typeof schema.inlineContentSchema,
            typeof schema.styleSchema
          >[])
        : undefined,
      uploadFile: async file => {
        const body = new FormData()
        body.append('file', file)
        const res = await apiFetch(apiUrl(`/api/documents/${page.id}/assets`), {
          method: 'POST',
          body,
        })
        if (!res.ok) {
          const error = await res.json().catch(() => ({}))
          throw new Error(t(error.detail || 'Upload failed'))
        }
        return (await res.json()).url as string
      },
    },
    [page.id]
  )
  useEffect(() => {
    const retry = (event: Event) => {
      uploadRetry.current = (event as CustomEvent).detail.blockId
      if (uploadInput.current) {
        uploadInput.current.accept = noteMediaAccept
        uploadInput.current.click()
      }
    }
    const el = container.current
    el?.addEventListener('note-upload-retry', retry)
    return () => el?.removeEventListener('note-upload-retry', retry)
  }, [])
  const parseMarkdown = useCallback(
    (text: string) =>
      parseNoteMarkdown(text, value => editor.tryParseMarkdownToBlocks(value) as NoteBlock[]),
    [editor]
  )
  useEffect(() => {
    let cancelled = false
    // BlockNote mounts React node views synchronously; initialize after React commits.
    queueMicrotask(() => {
      if (cancelled || initialized.current) return
      initialized.current = true
      if (page.blocks === null && page.content)
        editor.replaceBlocks(editor.document, parseMarkdown(page.content) as typeof editor.document)
      const insertClips = (clips: NoteClipInput[]) => {
        insertNoteClips(editor, clips)
        // PickerShell restores focus when it closes. Return to the document
        // afterwards so immediate undo/redo works without an extra click.
        requestAnimationFrame(() => {
          if (container.current) editor.focus()
        })
      }
      latest.current.onReady({
        blocks: () => editor.document as NoteBlock[],
        setEditable: editable => {
          editor.isEditable = editable
        },
        replace: blocks => {
          // Each acceptance is one undo step, independent of nearby typing or
          // another approval, even when the responses arrive within 500 ms.
          editor.transact(tr => closeHistory(tr))
          editor.replaceBlocks(
            editor.document,
            blocks.length
              ? (fitSchema(blocks as NoteBlock[]) as typeof editor.document)
              : [{ type: 'paragraph' }]
          )
          editor.transact(tr => closeHistory(tr))
        },
        parse: parseMarkdown,
        insertClip: (title, markdown, sourceUrl, sourceId = '', favorite) =>
          insertClips([{ title, markdown, sourceUrl, sourceId, favorite }]),
        insertClips,
        insertLearningAfter: (blockId, kind, prompt) => {
          const anchor = editor.getBlock(blockId)
          if (!anchor) return null
          const [created] = editor.insertBlocks(
            [{ type: 'learning', props: { kind, prompt } }],
            anchor,
            'after'
          )
          return created?.id ?? null
        },
        updateLearningPrompt: (blockId, prompt) => {
          const target = editor.getBlock(blockId)
          if (target?.type === 'learning' && target.props.prompt !== prompt)
            editor.updateBlock(target, { props: { prompt } })
        },
        cursorBlockId: () => {
          try {
            return editor.getTextCursorPosition().block.id
          } catch {
            return (editor.document[0] as NoteBlock | undefined)?.id ?? null
          }
        },
        hasBlock: id => Boolean(editor.getBlock(id)),
        focusBlock: id => {
          if (editor.getBlock(id)) {
            editor.setTextCursorPosition(id, 'start')
            editor.focus()
            container.current
              ?.querySelector(`[data-id="${CSS.escape(id)}"]`)
              ?.scrollIntoView({ block: 'center', behavior: 'smooth' })
          }
        },
      })
      ready.current = true
      const target = window.location.hash.slice(1)
      if (target && editor.getBlock(target)) {
        editor.setTextCursorPosition(target, 'start')
        container.current
          ?.querySelector(`[data-id="${CSS.escape(target)}"]`)
          ?.scrollIntoView({ block: 'center' })
      }
      // Persist the first conversion as a revisioned migration, even before typing.
      if (page.blocks === null) latest.current.onChange(editor.document as NoteBlock[])
    })
    return () => {
      cancelled = true
    }
  }, [editor, page.blocks, page.content, parseMarkdown])
  /** Open a conversation on the caret's line; with a selection, about it. */
  const ai = useCallback(
    (instruction: string) => {
      const quote = editor.getSelectedText().trim()
      const block = editor.getTextCursorPosition().block
      latest.current.onAI({
        blockId: block.id,
        quote: quote || undefined,
        prompt: instruction || undefined,
        autoSend: Boolean(instruction && quote),
      })
    },
    [editor]
  )
  const getItems = async (query: string): Promise<NoteMenuItem[]> => {
    const insert = (block: Record<string, unknown>) => {
      const current = editor.getTextCursorPosition().block
      const empty =
        current.type === 'paragraph' && (!current.content || current.content.length === 0)
      const [created] = empty
        ? editor.replaceBlocks(
            [current],
            [
              block as PartialBlock<
                typeof schema.blockSchema,
                typeof schema.inlineContentSchema,
                typeof schema.styleSchema
              >,
            ]
          ).insertedBlocks
        : editor.insertBlocks(
            [
              block as PartialBlock<
                typeof schema.blockSchema,
                typeof schema.inlineContentSchema,
                typeof schema.styleSchema
              >,
            ],
            current,
            'after'
          )
      if (created) {
        // Form blocks own focus. Focusing the editor here immediately blurs an
        // auto-focused formula input and closes it before the user can type.
        if (['math', 'webCard', 'htmlEmbed', 'learning'].includes(created.type)) {
          // SuggestionMenu restores editor focus after the insertion callback.
          // Hand it to the new form after that transaction and React commit.
          requestAnimationFrame(() => {
            container.current
              ?.querySelector<HTMLElement>(
                `[data-id="${CSS.escape(created.id)}"] input, [data-id="${CSS.escape(created.id)}"] textarea`
              )
              ?.focus()
          })
        } else {
          const target =
            created.type === 'noteColumns'
              ? created.children?.[0]?.children?.[0]?.id || created.id
              : created.id
          editor.setTextCursorPosition(target, 'start')
          editor.focus()
        }
      }
      return created
    }
    const item = (
      title: string,
      group: string,
      subtext: string,
      aliases: string[],
      Icon: typeof Info,
      action: () => void,
      preview: BlockPreviewKind,
      shortcut?: string
    ): NoteMenuItem => ({
      title: t(title),
      group: t(group),
      subtext: t(subtext),
      aliases,
      icon: <Icon size={19} strokeWidth={1.6} />,
      onItemClick: action,
      preview,
      shortcut,
    })
    const shortcuts: Record<string, string> = {
      heading: '#',
      heading_2: '##',
      heading_3: '###',
      heading_4: '####',
      bullet_list: '-',
      numbered_list: '1.',
      check_list: '[]',
      toggle_list: '>',
      quote: '"',
      code_block: '```',
      divider: '---',
    }
    const defaults = getDefaultReactSlashMenuItems(editor).flatMap(i => {
      const key = (i as { key?: string }).key || ''
      return isBasicPreviewKind(key)
        ? [{ ...i, preview: key, group: t('Basic blocks'), shortcut: shortcuts[key] }]
        : []
    })
    defaults.sort(
      (a, b) => basicPreviewKinds.indexOf(a.preview) - basicPreviewKinds.indexOf(b.preview)
    )
    const items: NoteMenuItem[] = [
      item(
        'Ask Dito',
        'Suggested',
        'Write, explain or improve this part of your note.',
        ['ai', '生成', '续写'],
        Sparkles,
        () => ai(''),
        'ai'
      ),
      item(
        'Reference a source',
        'Suggested',
        'Bring in a passage from your reading, chats or knowledge bases.',
        ['source', '引用', '知识'],
        BookOpen,
        () => container.current?.dispatchEvent(new CustomEvent('note-sources', { bubbles: true })),
        'source'
      ),
      item(
        'Insert favorite',
        'Suggested',
        'Keep an original answer with its source.',
        ['favorite', '收藏'],
        Bookmark,
        () =>
          container.current?.dispatchEvent(new CustomEvent('note-favorites', { bubbles: true })),
        'favorite'
      ),
      ...defaults,
      item(
        'Callout',
        'Basic blocks',
        'Highlight a key idea, tip or warning.',
        ['callout', '标注', '提示'],
        Info,
        () => insert({ type: 'callout' }),
        'callout'
      ),
      item(
        'Page link',
        'Basic blocks',
        'Link to another notebook page.',
        ['page', '页面', '链接'],
        FileText,
        () => editor.getExtension(SuggestionMenu)?.openSuggestionMenu('[['),
        'pageLink'
      ),
      ...(
        [
          ['image', 'Image', ImageIcon, 'image/png,image/jpeg,image/gif,image/webp', '图片'],
          ['video', 'Video', Film, 'video/mp4', '视频'],
          ['audio', 'Audio', Music, 'audio/mpeg,audio/wav', '音频'],
          ['file', 'File', Upload, noteMediaAccept, '文件'],
        ] as const
      ).map(([key, label, Icon, accept, alias]) =>
        item(
          label,
          'Media',
          'Upload a file to this page.',
          [key, alias],
          Icon,
          () => {
            if (uploadInput.current) {
              uploadAnchor.current = editor.getTextCursorPosition().block.id
              uploadRetry.current = null
              uploadInput.current.accept = accept
              uploadInput.current.click()
            }
          },
          key
        )
      ),
      item(
        'Web bookmark',
        'Media',
        'Save a link with a title and a short description.',
        ['bookmark', '书签'],
        Bookmark,
        () => insert({ type: 'webCard' }),
        'bookmark'
      ),
      item(
        'Embed',
        'Media',
        'Display an external page that allows embedding.',
        ['embed', '嵌入'],
        Globe,
        () => insert({ type: 'webCard', props: { mode: 'embed' } }),
        'embed'
      ),
      item(
        'HTML',
        'Media',
        'Preview HTML inside an isolated frame.',
        ['html', '网页'],
        FileCode,
        () => insert({ type: 'htmlEmbed' }),
        'htmlEmbed'
      ),
      ...(['table', 'board', 'list'] as const).map(view =>
        item(
          { table: 'Task table', board: 'Task board', list: 'Task list' }[view],
          'Linked views',
          'View and update tasks from this workspace.',
          ['task', view, '任务', { table: '表格', board: '看板', list: '列表' }[view]],
          Table2,
          () => insert({ type: 'taskView', props: { view } }),
          `task_${view}`
        )
      ),
      item(
        'Table of contents',
        'Advanced blocks',
        'Jump to headings; updates as your page changes.',
        ['toc', '目录'],
        ListTree,
        () => insert({ type: 'tableOfContents' }),
        'toc'
      ),
      item(
        'Math formula',
        'Advanced blocks',
        'Write a mathematical expression using LaTeX.',
        ['math', '公式'],
        Sigma,
        () => insert({ type: 'math' }),
        'math',
        '$$'
      ),
      ...([1, 2, 3] as const).map(level =>
        item(
          `Toggle heading ${level}`,
          'Advanced blocks',
          'Keep supporting notes inside a collapsible heading.',
          ['toggle', '折叠', `h${level}`],
          [Heading1, Heading2, Heading3][level - 1],
          () =>
            insert({ type: 'toggleHeading', props: { level }, children: [{ type: 'paragraph' }] }),
          `toggle_heading_${level}`
        )
      ),
      ...([2, 3, 4, 5] as const).map(count =>
        item(
          `${count} columns`,
          'Advanced blocks',
          'Arrange related ideas side by side. Stacks on small screens.',
          ['columns', '列', String(count)],
          Columns2,
          () =>
            insert({
              type: 'noteColumns',
              children: Array.from({ length: count }, () => ({
                type: 'noteColumn',
                children: [{ type: 'paragraph' }],
              })),
            }),
          `columns_${count}`
        )
      ),
      item(
        'Date',
        'Inline',
        'Add an editable date in your text.',
        ['date', '日期'],
        CalendarDays,
        () =>
          editor.insertInlineContent([
            { type: 'noteDate', props: { date: new Date().toLocaleDateString('en-CA') } },
            ' ',
          ]),
        'date'
      ),
      item(
        'Inline formula',
        'Inline',
        'Place a formula within a sentence.',
        ['inline math', '行内公式'],
        Sigma,
        () => editor.insertInlineContent([{ type: 'inlineMath', props: { formula: 'x^2' } }, ' ']),
        'inlineMath',
        '$…$'
      ),
      ...LEARNING_KINDS.map(({ kind, label, alias, Icon }) =>
        item(
          label,
          'Learning',
          'Create learning material grounded in this page.',
          [kind, alias],
          Icon,
          () => {
            insert({ type: 'learning', props: { kind } })
          },
          ({ image: 'generated_image', audio: 'podcast' }[kind] || kind) as BlockPreviewKind
        )
      ),
    ]
    const needle = query.toLowerCase().trim()
    return items.filter(i =>
      [i.title, ...(i.aliases || [])].some(label => label.toLowerCase().includes(needle))
    )
  }
  const pageItems = async (query: string): Promise<NoteMenuItem[]> => {
    const { documents } = await listNotes()
    return documents
      .filter(d => d.id !== page.id && d.title.toLowerCase().includes(query.toLowerCase()))
      .slice(0, 15)
      .map(d => ({
        title: d.title,
        preview: 'pageLink' as const,
        previewTitle: d.title,
        subtext: t('Open linked page'),
        icon: <FileText size={19} />,
        onItemClick: () =>
          editor.insertInlineContent([
            { type: 'pageLink', props: { pageId: d.id, title: d.title } },
            ' ',
          ]),
      }))
  }
  const Toolbar = () => {
    const activeStyles = useActiveStyles(editor)
    const [panel, setPanel] = useState<'link' | 'ai' | 'color' | null>(null)
    const [linkUrl, setLinkUrl] = useState('')
    const [linkError, setLinkError] = useState('')
    // Atomic source/media blocks cannot receive inline formatting. BlockNote
    // also selects these on interaction; only offer tools for selected text.
    if (!editor.getSelectedText().trim()) return null
    const keep = (e: React.MouseEvent) => e.preventDefault()
    const color = activeStyles.textColor || 'default'
    return (
      <div
        className="dt-note-toolbar"
        onMouseDown={e => {
          if (!(e.target as HTMLElement).closest('input')) e.preventDefault()
        }}
      >
        <button
          className={`dt-note-toolbar-ai ${panel === 'ai' ? 'is-open' : ''}`}
          aria-haspopup="menu"
          aria-expanded={panel === 'ai'}
          onMouseDown={keep}
          onClick={() => setPanel(panel === 'ai' ? null : 'ai')}
        >
          <Sparkles size={14} />
          {t('Ask Dito')}
          <ChevronDown size={12} className="opacity-60" />
        </button>
        <span className="dt-note-toolbar-sep" aria-hidden />
        {(
          [
            ['bold', Bold, 'Bold'],
            ['italic', Italic, 'Italic'],
            ['underline', Underline, 'Underline'],
            ['strike', Strikethrough, 'Strikethrough'],
            ['code', Code, 'Code'],
          ] as const
        ).map(([style, Icon, label]) => (
          <Tooltip key={style} label={t(label)}>
            <button
              aria-label={t(label)}
              aria-pressed={!!activeStyles[style]}
              onMouseDown={keep}
              onClick={() => editor.toggleStyles({ [style]: true })}
            >
              <Icon size={15} />
            </button>
          </Tooltip>
        ))}
        <Tooltip label={t('Link')}>
          <button
            aria-label={t('Link')}
            aria-expanded={panel === 'link'}
            onMouseDown={keep}
            onClick={() => setPanel(panel === 'link' ? null : 'link')}
          >
            <LinkIcon size={15} />
          </button>
        </Tooltip>
        <Tooltip label={t('Text color')}>
          <button
            aria-label={t('Text color')}
            aria-haspopup="menu"
            aria-expanded={panel === 'color'}
            onMouseDown={keep}
            onClick={() => setPanel(panel === 'color' ? null : 'color')}
          >
            <span className="dt-note-color-glyph" data-color={color}>
              A
            </span>
            <ChevronDown size={11} className="opacity-60" />
          </button>
        </Tooltip>
        {panel === 'ai' && (
          <div className="dt-note-toolbar-panel" role="menu">
            {(
              [
                ['Rewrite', 'Rewrite the selected text; preserve the rest of the block', PenLine],
                ['Make shorter', 'Shorten the selected text', Minimize2],
                ['Make longer', 'Expand the selected text', Maximize2],
                ['Translate', 'Translate the selected text', Languages],
                ['Explain in a comment', 'Explain this passage in a comment', MessageSquareText],
              ] as const
            ).map(([label, prompt, Icon]) => (
              <button
                key={label}
                role="menuitem"
                onMouseDown={keep}
                onClick={() => {
                  setPanel(null)
                  ai(t(prompt))
                }}
              >
                <Icon size={14} />
                {t(label)}
              </button>
            ))}
            <div className="dt-note-toolbar-divider" />
            <button
              role="menuitem"
              onMouseDown={keep}
              onClick={() => {
                setPanel(null)
                ai('')
              }}
            >
              <Sparkles size={14} />
              {t('Ask about the selection…')}
            </button>
          </div>
        )}
        {panel === 'color' && (
          <div className="dt-note-toolbar-panel is-colors" role="menu">
            {Object.entries({
              default: t('Default color'),
              gray: t('Gray color'),
              red: t('Red color'),
              orange: t('Orange color'),
              yellow: t('Yellow color'),
              green: t('Green color'),
              blue: t('Blue color'),
              purple: t('Purple color'),
            }).map(([c, name]) => (
              <button
                key={c}
                role="menuitemradio"
                aria-checked={color === c}
                onMouseDown={keep}
                onClick={() => {
                  setPanel(null)
                  if (c === 'default') editor.removeStyles({ textColor: color })
                  else editor.addStyles({ textColor: c })
                }}
              >
                <span className="dt-note-color-glyph" data-color={c}>
                  A
                </span>
                {name}
              </button>
            ))}
          </div>
        )}
        {panel === 'link' && (
          <form
            className="dt-note-link-form"
            onSubmit={e => {
              e.preventDefault()
              if (!/^(https?:\/\/|mailto:|\/(?!\/)|#)/i.test(linkUrl.trim())) {
                setLinkError(t('Enter a valid link'))
                return
              }
              editor.createLink(linkUrl.trim())
              setPanel(null)
              editor.focus()
            }}
          >
            <input
              autoFocus
              aria-label={t('Link URL')}
              placeholder={t('Paste a link…')}
              value={linkUrl}
              onChange={e => setLinkUrl(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Escape') {
                  setPanel(null)
                  editor.focus()
                }
              }}
            />
            <button type="submit">{t('Apply')}</button>
            {linkError && <p role="alert">{linkError}</p>}
          </form>
        )}
      </div>
    )
  }
  return (
    <div
      ref={attachContainer}
      className="dt-note-editor"
      onPointerDownCapture={e => {
        // Cards (learning blocks, embeds) take no text cursor, so a click on
        // one is the only sign the learner is looking at it.
        const target = e.target as HTMLElement
        if (target.closest('.bn-side-menu, .dt-note-orbs, .dt-note-ask-orb')) return
        const id = target.closest<HTMLElement>('.bn-block-outer[data-id]')?.dataset.id
        if (id) latest.current.onFocusBlock?.(id)
      }}
      onKeyDownCapture={e => {
        // Read-only card controls stop ProseMirror's key handling. Keep the
        // document history accessible while a card button or source has focus.
        const target = e.target as HTMLElement
        if (
          target.closest('.dt-note-favorite') &&
          !target.closest('input, textarea, [contenteditable="true"]:not(.bn-editor)') &&
          !e.nativeEvent.isComposing &&
          !e.altKey &&
          (e.metaKey || e.ctrlKey) &&
          ['z', 'y'].includes(e.key.toLowerCase())
        ) {
          e.preventDefault()
          e.stopPropagation()
          if (e.shiftKey || e.key.toLowerCase() === 'y') editor.redo()
          else editor.undo()
          editor.focus()
        }
      }}
      onKeyDown={e => {
        if (
          !(
            e.target instanceof HTMLElement &&
            e.target.closest('input, textarea, button, [contenteditable="false"]')
          ) &&
          !e.nativeEvent.isComposing &&
          e.key === ' ' &&
          editor.getTextCursorPosition().block.type === 'paragraph' &&
          editor.getSelectedText() === ''
        ) {
          const content = editor.getTextCursorPosition().block.content
          if (Array.isArray(content) && content.length === 0) {
            e.preventDefault()
            ai('')
          }
        }
      }}
    >
      <input
        ref={uploadInput}
        type="file"
        accept={noteMediaAccept}
        className="hidden"
        onChange={async e => {
          const file = e.target.files?.[0]
          e.target.value = ''
          if (!file) return
          const retryId = uploadRetry.current
          uploadRetry.current = null
          const id = retryId || crypto.randomUUID()
          activeNoteUploads.add(id)
          const existing = retryId ? editor.getBlock(retryId) : undefined
          if (existing?.type === 'noteUpload') {
            editor.updateBlock(existing, { props: { name: file.name, error: '' } })
          } else {
            const anchor =
              editor.getBlock(uploadAnchor.current || '') || editor.getTextCursorPosition().block
            const placeholder = { id, type: 'noteUpload' as const, props: { name: file.name } }
            if (anchor.type === 'paragraph' && !anchor.content?.length)
              editor.replaceBlocks([anchor], [placeholder])
            else editor.insertBlocks([placeholder], anchor, 'after')
          }
          try {
            const type = noteMediaType(file)
            const url = await editor.uploadFile!(file)
            // The user may move the caret or delete the placeholder while uploading.
            const target = editor.getBlock(id)
            if (target?.type === 'noteUpload')
              editor.replaceBlocks(
                [target],
                [{ id, type, props: { url: typeof url === 'string' ? url : '', name: file.name } }]
              )
          } catch (err) {
            activeNoteUploads.delete(id)
            if (editor.getBlock(id)?.type === 'noteUpload')
              editor.updateBlock(id, {
                props: { error: t(err instanceof Error ? err.message : 'Upload failed') },
              })
          } finally {
            activeNoteUploads.delete(id)
          }
        }}
      />
      <BlockNoteViewRaw
        editor={editor}
        theme={theme}
        formattingToolbar={false}
        linkToolbar={false}
        slashMenu={false}
        sideMenu={false}
        filePanel={false}
        tableHandles={false}
        emojiPicker={false}
        comments={false}
        onChange={() => {
          if (ready.current) latest.current.onChange(editor.document as NoteBlock[])
        }}
        onSelectionChange={() => {
          if (!ready.current || !latest.current.onFocusBlock) return
          try {
            latest.current.onFocusBlock(editor.getTextCursorPosition().block.id)
          } catch {
            // No text cursor (a node selection on a card).
          }
        }}
      >
        <NoteThreadMarkers
          editor={editor}
          container={containerEl}
          threads={threads}
          activeSessionId={activeThread?.sessionId ?? null}
          activeBlockId={activeThread?.blockId ?? null}
          interactive={threadsInteractive}
          onOpen={onOpenThread}
          onDelete={onDeleteThread}
          onAsk={blockId => latest.current.onAI({ blockId })}
        />
        {activeThread && (
          // The line the open conversation is about stays marked while it is open.
          <style>{`.dt-note-editor .bn-block-outer[data-id="${CSS.escape(activeThread.blockId)}"] > .bn-block > .bn-block-content { background: var(--dt-note-anchor-bg); box-shadow: -6px 0 0 var(--dt-note-anchor-bg), 6px 0 0 var(--dt-note-anchor-bg); border-radius: 4px; }`}</style>
        )}
        <NoteInlineReviews
          editor={editor}
          suggestions={suggestions}
          busy={reviewBusy}
          errors={reviewErrors}
          onReview={onReview}
          onDiscuss={onDiscuss}
          onContinueResearch={onContinueResearch}
        />
        <FormattingToolbarController formattingToolbar={Toolbar} />
        <SideMenuController
          sideMenu={() => <Handles editor={editor} />}
          floatingUIOptions={SIDE_MENU_FLOATING}
        />
        {['/', '、'].map(trigger => (
          <SuggestionMenuController
            key={trigger}
            triggerCharacter={trigger}
            shouldOpen={tr => {
              const parent = tr.selection.$from.parent
              return (
                !parent.type.spec.code &&
                !parent.type.isInGroup('tableContent') &&
                (trigger !== '、' || parent.textContent.length === 0)
              )
            }}
            getItems={getItems}
            suggestionMenuComponent={NoteInsertMenu}
          />
        ))}
        {['[[', '@'].map(trigger => (
          <SuggestionMenuController
            key={trigger}
            triggerCharacter={trigger}
            getItems={async (query: string): Promise<NoteMenuItem[]> =>
              trigger === '[['
                ? pageItems(query)
                : [
                    {
                      title: t('Reference a source'),
                      preview: 'source' as const,
                      onItemClick: () =>
                        container.current?.dispatchEvent(
                          new CustomEvent('note-sources', { bubbles: true })
                        ),
                    },
                    {
                      title: t('Insert favorite'),
                      preview: 'favorite' as const,
                      onItemClick: () =>
                        container.current?.dispatchEvent(
                          new CustomEvent('note-favorites', { bubbles: true })
                        ),
                    },
                    ...(await pageItems(query)),
                  ]
            }
            suggestionMenuComponent={NoteInsertMenu}
          />
        ))}
      </BlockNoteViewRaw>
    </div>
  )
}
