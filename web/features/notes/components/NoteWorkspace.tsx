'use client'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import { useCallback, useEffect, useRef, useState, type ComponentType } from 'react'
import type { NoteCompanionProps } from './note-companion-props'
import { useRouter } from 'next/navigation'
import { useTranslation } from 'react-i18next'
import {
  getNote,
  saveNote,
  listNotes,
  createNote,
  getSuggestions,
  reviewSuggestion,
  noteRequest,
  type NoteBlock,
  type NotePage,
  type NoteSummary,
  type NoteSuggestion,
} from '@/lib/notes-api'
import { exportCoWriterDocx } from '@/lib/co-writer-api'
import { notifyCoWriterChanged } from '@/lib/co-writer-events'
import { browserStorage } from '@/shared/storage'
import { useAuthStatus } from '@/hooks/useAuthStatus'
import { researchOutline } from '../model/research'
import type { NoteAsk, NoteEditorHandle } from './NoteEditor'
import NotePageTree from './NotePageTree'
import './note-workspace.css'
import NotePageHead from './NotePageHead'
import NoteTopBar, { type NoteSaveStatus } from './NoteTopBar'
import NoteOutline from './NoteOutline'
import { blockLineCenter } from './NoteThreadMarkers'
import { foldIntoOrb } from '../model/fold-motion'
import { useNoteThreads } from './useNoteThreads'
import { pageDescendants } from '../model/page-tree'
import { inlineText } from '../model/threads'
import { learningKind } from '../model/learning-kinds'
const Editor = dynamic(() => import('./NoteEditor'), {
  ssr: false,
  loading: () => <div className="dt-note-editor-loading" aria-hidden />,
})
const SourcePicker = dynamic(() => import('./NoteSourcePicker'), { ssr: false })
const FavoritesPicker = dynamic(() => import('./NoteFavoritesPicker'), { ssr: false })

export default function NoteWorkspace({
  docId,
  embedded = false,
  companion: Companion,
}: {
  docId: string
  embedded?: boolean
  companion?: ComponentType<NoteCompanionProps>
}) {
  const { t } = useTranslation()
  const router = useRouter()
  const auth = useAuthStatus()
  const owner =
    auth.statusAvailable && !auth.loading ? (auth.enabled ? auth.userId : 'local') : null
  const [mutating, setMutating] = useState(false)
  const [page, setPage] = useState<NotePage | null>(null)
  const [pages, setPages] = useState<NoteSummary[]>([])
  const [error, setError] = useState('')
  const [reviewErrors, setReviewErrors] = useState<Record<string, string>>({})
  const [status, setStatus] = useState<NoteSaveStatus>('Saved')
  const [tree, setTreeOpen] = useState(false)
  const [outlineOpen, setOutlineOpenState] = useState(true)
  const setOutlineOpen = (open: boolean) => {
    setOutlineOpenState(open)
    if (owner) browserStorage.writeRaw('local', `deeptutor.notes.outline:${owner}`, String(open))
  }
  const [mainEl, setMainEl] = useState<HTMLElement | null>(null)
  // How much margin the page column leaves: room for the open outline, for
  // its folded rail, or for neither.
  const [margin, setMargin] = useState<'wide' | 'rail' | 'none'>('none')
  const slot = useRef<HTMLDivElement>(null)
  const setTree = (open: boolean) => {
    setTreeOpen(open)
    if (owner) browserStorage.writeRaw('local', `deeptutor.notes.tree:${owner}`, String(open))
  }
  const [sources, setSources] = useState(false)
  const [favorites, setFavorites] = useState(false)
  const [suggestions, setSuggestions] = useState<NoteSuggestion[]>([])
  const [backlinks, setBacklinks] = useState<NoteSummary[]>([])
  const [recovery, setRecovery] = useState<{ title: string; blocks: NoteBlock[] } | null>(null)
  const editor = useRef<NoteEditorHandle | null>(null)
  const latest = useRef<NotePage | null>(null)
  const version = useRef(0)
  const savedVersion = useRef(0)
  const inflight = useRef<Promise<void> | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const root = useRef<HTMLDivElement>(null)
  const draftKey = owner ? `deeptutor.notes.draft:${owner}:${docId}` : null
  const refreshSuggestions = useCallback(() => {
    void getSuggestions(docId)
      .then(r => {
        const pending = r.suggestions.filter(s => s.status === 'pending')
        setSuggestions(previous =>
          JSON.stringify(previous) === JSON.stringify(pending) ? previous : pending
        )
      })
      .catch(e => setError(String(e)))
  }, [docId])
  const refreshPages = useCallback(() => {
    void listNotes()
      .then(r => setPages(r.documents))
      .catch(e => setError(String(e)))
  }, [])
  const persistDraft = useCallback(() => {
    if (draftKey && latest.current)
      browserStorage.writeRaw(
        'local',
        draftKey,
        JSON.stringify({
          title: latest.current.title,
          blocks: latest.current.blocks,
          revision: latest.current.revision,
        })
      )
  }, [draftKey])
  const flush = useCallback(async () => {
    if (inflight.current) await inflight.current
    if (savedVersion.current === version.current || !latest.current) return
    const save = async () => {
      while (savedVersion.current !== version.current && latest.current) {
        const snapshot = latest.current
        const at = version.current
        setStatus('Saving…')
        const result = await saveNote(docId, {
          title: snapshot.title,
          blocks: snapshot.blocks,
          expected_revision: snapshot.revision,
        })
        latest.current = { ...latest.current, revision: result.revision, content: result.content }
        savedVersion.current = at
        if (version.current === at) {
          if (draftKey) browserStorage.removeRaw('local', draftKey)
          setStatus('Saved')
        } else persistDraft()
        setPage(current =>
          current ? { ...current, revision: result.revision, content: result.content } : current
        )
        setPages(current =>
          current.map(p =>
            p.id === docId ? { ...p, title: snapshot.title, revision: result.revision } : p
          )
        )
        notifyCoWriterChanged()
      }
    }
    inflight.current = save()
    try {
      await inflight.current
      setError('')
    } catch (err) {
      persistDraft()
      setStatus('Save failed')
      setError(err instanceof Error ? err.message : String(err))
      throw err
    } finally {
      inflight.current = null
    }
  }, [docId, draftKey, persistDraft])
  const changed = useCallback(
    (patch: Partial<NotePage>) => {
      if (!latest.current) return
      if (patch.blocks && JSON.stringify(patch.blocks) === JSON.stringify(latest.current.blocks))
        return
      latest.current = { ...latest.current, ...patch }
      // Keep the editor's remount snapshot current too. Updating only the ref
      // leaves initialContent stale after a lazy component reload/remount.
      setPage(current => (current ? { ...current, ...patch } : current))
      version.current++
      persistDraft()
      setStatus('Unsaved changes')
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => {
        void flush().catch(() => {})
      }, 900)
    },
    [flush, persistDraft]
  )
  useEffect(() => {
    if (!draftKey) return
    let cancelled = false
    void getNote(docId)
      .then(doc => {
        if (cancelled) return
        const raw = browserStorage.readRaw('local', draftKey)
        if (raw) {
          try {
            const draft = JSON.parse(raw)
            if (Array.isArray(draft.blocks)) {
              if (draft.revision === doc.revision) {
                doc = { ...doc, title: draft.title, blocks: draft.blocks }
                version.current++
              } else setRecovery(draft)
            }
          } catch {
            /* Ignore invalid recovery data, never overwrite the server page. */
          }
        }
        latest.current = doc
        setPage(doc)
        setTreeOpen(browserStorage.readRaw('local', `deeptutor.notes.tree:${owner}`) === 'true')
        setOutlineOpenState(
          browserStorage.readRaw('local', `deeptutor.notes.outline:${owner}`) !== 'false'
        )
        refreshPages()
        refreshSuggestions()
        void noteRequest<{ pages: NoteSummary[] }>(`/${docId}/backlinks`).then(r => {
          if (!cancelled) setBacklinks(r.pages)
        })
      })
      .catch(err => setError(String(err)))
    return () => {
      cancelled = true
      if (timer.current) clearTimeout(timer.current)
    }
  }, [docId, draftKey, owner, refreshPages, refreshSuggestions])
  useEffect(() => {
    const onUnload = (e: BeforeUnloadEvent) => {
      if (version.current !== savedVersion.current) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', onUnload)
    return () => window.removeEventListener('beforeunload', onUnload)
  }, [])
  useEffect(() => {
    const el = root.current
    const showSources = () => setSources(true)
    const showFavorites = () => setFavorites(true)
    el?.addEventListener('note-sources', showSources)
    el?.addEventListener('note-favorites', showFavorites)
    const saveBeforeSwitch = (e: Event) => {
      ;(e as CustomEvent<Promise<void>[]>).detail.push(flush())
    }
    window.addEventListener('deeptutor:before-workspace-switch', saveBeforeSwitch)
    return () => {
      el?.removeEventListener('note-sources', showSources)
      el?.removeEventListener('note-favorites', showFavorites)
      window.removeEventListener('deeptutor:before-workspace-switch', saveBeforeSwitch)
    }
  }, [flush])
  const threads = useNoteThreads({
    pageId: docId,
    owner,
    embedded,
    flush,
    onSuggestions: refreshSuggestions,
    onError: message => setError(message),
  })
  const findBlock = useCallback((blockId: string) => {
    const walk = (blocks: NoteBlock[]): NoteBlock | undefined => {
      for (const block of blocks) {
        if (block.id === blockId) return block
        const nested = walk(block.children || [])
        if (nested) return nested
      }
    }
    return walk(latest.current?.blocks || [])
  }, [])
  /** What kind of block it is: a learning block's kind, or the block type. */
  const blockKind = useCallback(
    (blockId: string): string | null => {
      const block = findBlock(blockId)
      if (!block) return null
      return block.type === 'learning' ? `learning:${String(block.props.kind || '')}` : block.type
    },
    [findBlock]
  )
  /** Plain text of a block on the page, or null once it is gone. */
  const blockText = useCallback(
    (blockId: string): string | null => {
      const block = findBlock(blockId)
      if (!block) return null
      if (block.type === 'learning') {
        const kind = String(block.props.kind || '')
        const prompt = String(block.props.prompt || '').trim()
        return `${t(learningKind(kind).label)}${prompt ? ` · ${prompt}` : ''}`
      }
      return inlineText(block.content).trim()
    },
    [findBlock, t]
  )
  const scrollToBlock = useCallback((blockId: string, flash = true) => {
    const el = root.current?.querySelector<HTMLElement>(
      `.dt-note-editor .bn-block-outer[data-id="${CSS.escape(blockId)}"]`
    )
    if (!el) return
    el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    if (flash)
      el.querySelector('.bn-block-content')?.animate(
        [{ backgroundColor: 'var(--dt-note-anchor-flash)' }, { backgroundColor: 'transparent' }],
        { duration: 1400, easing: 'ease-out' }
      )
  }, [])
  const notebookLink = useCallback(
    (sessionId?: string) =>
      router.push(
        `/co-writer/${docId}${sessionId ? `?chat=${encodeURIComponent(sessionId)}` : ''}`
      ),
    [docId, router]
  )
  const ask = useCallback(
    (request: NoteAsk) => {
      if (embedded) return notebookLink()
      threads.startThread(request)
    },
    [embedded, notebookLink, threads]
  )
  const openThread = useCallback(
    (sessionId: string) => {
      if (embedded) return notebookLink(sessionId)
      const thread = threads.threads.find(item => item.session_id === sessionId)
      void threads.openThread(sessionId)
      if (thread) scrollToBlock(thread.block_id)
    },
    [embedded, notebookLink, scrollToBlock, threads]
  )
  // A block clicked while a conversation is open: a conversation not begun
  // yet moves to it; one under way offers to ask about it in its own thread.
  const [focus, setFocus] = useState<{ key: string; blockId: string } | null>(null)
  const focusBlock = useCallback(
    (blockId: string) => {
      const open = threads.open
      if (!open) return
      if (blockId === open.blockId || threads.retarget(blockId)) setFocus(null)
      else
        setFocus(current =>
          current?.blockId === blockId && current.key === open.key
            ? current
            : { key: open.key, blockId }
        )
    },
    [threads]
  )
  const focused = focus && threads.open && focus.key === threads.open.key ? focus.blockId : null
  const askAtCursor = useCallback(
    (prompt?: string) => {
      const blockId = editor.current?.cursorBlockId() || latest.current?.blocks?.[0]?.id
      if (blockId) ask({ blockId, prompt })
    },
    [ask]
  )
  /* Closing the panel folds the conversation into its orb on the line: a
     ghost of the panel shrinks into the orb, which then takes a breath. */
  const foldPanel = useCallback(() => {
    const open = threads.open
    const panel = slot.current
    const host = root.current
    const keep = Boolean(open && (open.sessionId || threads.hasMessages))
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (!open || !panel || !host || !keep || still) {
      threads.close()
      return
    }
    // The clone is taken before the panel unmounts; it unmounts once the
    // collapse is under way.
    foldIntoOrb(
      panel,
      host,
      () => {
        const orb = open.sessionId
          ? host.querySelector<HTMLElement>(`[data-thread-orb="${CSS.escape(open.sessionId)}"]`)
          : null
        if (orb) return { rect: orb.getBoundingClientRect(), orb }
        const editorEl = host.querySelector<HTMLElement>('.dt-note-editor')
        const center = editorEl ? blockLineCenter(editorEl, open.blockId) : null
        if (!editorEl || center === null) return null
        const box = editorEl.getBoundingClientRect()
        return {
          rect: new DOMRect(box.right - 31, box.top + center - 4, 8, 8),
          orb: host.querySelector<HTMLElement>('.dt-note-orbs'),
        }
      },
      threads.close
    )
  }, [threads])
  useEffect(() => {
    const el = root.current
    const generate = (event: Event) => {
      if (embedded) return notebookLink()
      threads.generateBlock((event as CustomEvent).detail)
    }
    const openFromBlock = (event: Event) => openThread((event as CustomEvent).detail.sessionId)
    const regenerate = (event: Event) => {
      if (embedded) return notebookLink()
      threads.regenerateBlock((event as CustomEvent).detail)
    }
    el?.addEventListener('note-generate', generate)
    el?.addEventListener('note-open-thread', openFromBlock)
    el?.addEventListener('note-regenerate', regenerate)
    return () => {
      el?.removeEventListener('note-generate', generate)
      el?.removeEventListener('note-open-thread', openFromBlock)
      el?.removeEventListener('note-regenerate', regenerate)
    }
  }, [embedded, notebookLink, openThread, threads])
  // The page column's spare margin decides whether the outline can stay open.
  useEffect(() => {
    if (!mainEl) return
    const observer = new ResizeObserver(([entry]) => {
      const spare = (entry.contentRect.width - 820) / 2
      setMargin(spare >= 212 ? 'wide' : spare >= 52 ? 'rail' : 'none')
    })
    observer.observe(mainEl)
    return () => observer.disconnect()
  }, [mainEl])
  const applySuggestion = async (suggestion: NoteSuggestion, accept: boolean) => {
    setMutating(true)
    setReviewErrors(previous => ({ ...previous, [suggestion.id]: '' }))
    editor.current?.setEditable(false)
    try {
      await flush()
      const replacement =
        accept && suggestion.operation !== 'comment' && suggestion.operation !== 'delete'
          ? suggestion.blocks || editor.current?.parse(suggestion.markdown)
          : undefined
      const result = await reviewSuggestion(docId, suggestion.id, accept, replacement)
      latest.current = result
      setPage(result)
      if (accept && suggestion.operation !== 'comment' && result.blocks)
        editor.current?.replace(result.blocks)
      refreshSuggestions()
      setError('')
    } catch (err) {
      const message = String(err instanceof Error ? err.message : err)
      setReviewErrors(previous => ({
        ...previous,
        [suggestion.id]: message.includes('The suggested block changed')
          ? t(
              'This block has changed. Your edits are safe. Discuss a new suggestion or dismiss this one.'
            )
          : message,
      }))
    } finally {
      setMutating(false)
      editor.current?.setEditable(true)
    }
  }
  const continueResearch = async (suggestion: NoteSuggestion) => {
    const outline = researchOutline(suggestion)
    if (!outline) return
    try {
      await flush()
      await reviewSuggestion(docId, suggestion.id, false)
      refreshSuggestions()
      root.current?.dispatchEvent(
        new CustomEvent('note-generate', {
          bubbles: true,
          detail: {
            kind: 'research',
            blockId: suggestion.block_id,
            prompt: outline.topic,
            config: { ...outline.research_config, confirmed_outline: outline.sub_topics },
          },
        })
      )
    } catch (err) {
      setError(String(err))
    }
  }
  const metadata = async (patch: Partial<NotePage>) => {
    setMutating(true)
    editor.current?.setEditable(false)
    try {
      await flush()
      const result = await saveNote(docId, {
        ...patch,
        expected_revision: latest.current!.revision,
      })
      latest.current = result
      setPage(result)
      refreshPages()
      notifyCoWriterChanged()
    } catch (err) {
      setError(String(err))
    } finally {
      setMutating(false)
      editor.current?.setEditable(true)
    }
  }
  const exportFile = async (format: 'md' | 'docx') => {
    try {
      await flush()
      const doc = latest.current!
      const blob =
        format === 'docx'
          ? await exportCoWriterDocx({ title: doc.title, content: doc.content })
          : new Blob([doc.content], { type: 'text/markdown' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${doc.title || 'Note'}.${format}`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) {
      setError(String(err))
    }
  }
  const invalidParents = pageDescendants(pages, docId)
  const createPage = async (parentId: string | null = null) => {
    setMutating(true)
    try {
      await flush()
      const doc = await createNote('', parentId)
      refreshPages()
      router.push(`/co-writer/${doc.id}`)
    } catch (err) {
      setError(String(err))
    } finally {
      setMutating(false)
    }
  }
  const openPage = async (id: string) => {
    if (id === docId) return
    try {
      await flush()
      router.push(`/co-writer/${id}`)
    } catch {
      /* Keep the unsaved page visible. */
    }
  }
  const navigate = async (event: React.MouseEvent<HTMLAnchorElement>, id: string) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
    if (id === docId || version.current !== savedVersion.current) {
      event.preventDefault()
      if (id === docId) return
      try {
        await flush()
        router.push(`/co-writer/${id}`)
      } catch {
        /* Keep the unsaved page visible. */
      }
    }
  }
  return (
    <div
      ref={root}
      className="dt-note-workspace"
      onClickCapture={event => {
        const link = (event.target as HTMLElement).closest<HTMLAnchorElement>('a[data-note-source]')
        if (
          !link ||
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        )
          return
        // Editor link handling otherwise consumes the click as a selection.
        // Flush pending text/title changes before leaving the page.
        event.preventDefault()
        event.stopPropagation()
        const url = new URL(link.href, window.location.href)
        void flush()
          .then(() => {
            if (url.origin === window.location.origin)
              router.push(`${url.pathname}${url.search}${url.hash}`)
            else window.location.assign(url.href)
          })
          .catch(() => {
            /* Save error stays visible; keep the current page. */
          })
      }}
    >
      <NoteTopBar
        page={page}
        pages={pages}
        invalidParents={invalidParents}
        status={status}
        busy={mutating}
        embedded={embedded}
        treeOpen={tree}
        companionOpen={Boolean(threads.open)}
        onToggleTree={() => setTree(!tree)}
        onToggleCompanion={() => (threads.open ? foldPanel() : askAtCursor())}
        onNavigate={navigate}
        onOpenPage={id => void openPage(id)}
        onCreatePage={() => void createPage()}
        onMetadata={patch => void metadata(patch)}
        onInsertFavorite={() => setFavorites(true)}
        onExport={format => void exportFile(format)}
      />
      {error && (
        <div role="alert" className="dt-note-banner is-error">
          <span className="flex-1">{error}</span>
          <button className="dt-note-button" onClick={() => void flush().catch(() => {})}>
            {t('Retry')}
          </button>
          <button
            className="dt-note-button"
            onClick={() => {
              if (latest.current?.blocks)
                setRecovery({ title: latest.current.title, blocks: latest.current.blocks })
              void getNote(docId).then(result => {
                latest.current = result
                setPage(result)
                editor.current?.replace(result.blocks || editor.current.parse(result.content))
                savedVersion.current = version.current
                setError('')
              })
            }}
          >
            {t('Reload page')}
          </button>
        </div>
      )}
      {recovery && (
        <div className="dt-note-banner">
          <span className="flex-1">{t('A local draft differs from this page.')}</span>
          <button
            className="dt-note-button"
            onClick={async () => {
              const doc = await createNote(`${recovery.title} (${t('Recovered draft')})`)
              await saveNote(doc.id, { blocks: recovery.blocks, expected_revision: doc.revision })
              if (draftKey) browserStorage.removeRaw('local', draftKey)
              setRecovery(null)
              refreshPages()
              router.push(`/co-writer/${doc.id}`)
            }}
          >
            {t('Save draft as a new page')}
          </button>
        </div>
      )}
      <div className="dt-note-body">
        {tree && (
          <NotePageTree
            pages={pages}
            currentId={docId}
            busy={mutating}
            embedded={embedded}
            onNavigate={navigate}
            onCreate={createPage}
          />
        )}
        <main className="dt-note-main" ref={setMainEl}>
          {page && margin !== 'none' && (
            <NoteOutline
              blocks={page.blocks}
              scroller={mainEl}
              open={outlineOpen}
              roomy={margin === 'wide'}
              onToggle={() => setOutlineOpen(!outlineOpen)}
              onJump={id => scrollToBlock(id, false)}
            />
          )}
          {page && (
            <div className="dt-note-document">
              <NotePageHead
                page={page}
                disabled={mutating}
                onTitle={title => {
                  setPage({ ...page, title })
                  changed({ title })
                }}
                onMetadata={patch => void metadata(patch)}
              />
              <Editor
                key={docId}
                page={page}
                suggestions={suggestions}
                reviewBusy={mutating}
                reviewErrors={reviewErrors}
                onContinueResearch={suggestion => void continueResearch(suggestion)}
                onReview={(suggestion, accept) => void applySuggestion(suggestion, accept)}
                onDiscuss={suggestion =>
                  suggestion.block_id
                    ? ask({
                        blockId: suggestion.block_id,
                        prompt: `${t('Discuss this feedback')}: ${suggestion.explanation}`,
                      })
                    : askAtCursor(`${t('Discuss this feedback')}: ${suggestion.explanation}`)
                }
                onChange={blocks => changed({ blocks })}
                onReady={handle => {
                  editor.current = handle
                  if (version.current !== savedVersion.current) void flush().catch(() => {})
                }}
                onAI={ask}
                threads={threads.threads}
                activeThread={threads.open}
                threadsInteractive={!embedded}
                onOpenThread={openThread}
                onDeleteThread={threads.removeThread}
                onFocusBlock={threads.open && !embedded ? focusBlock : undefined}
              />
              {!!backlinks.length && (
                <section className="dt-note-backlinks" aria-label={t('Linked from')}>
                  <h2>{t('Linked from')}</h2>
                  {backlinks.map(p => (
                    <Link key={p.id} href={`/co-writer/${p.id}`} onClick={e => navigate(e, p.id)}>
                      <span aria-hidden>{p.icon || '↗'}</span>
                      {p.title || t('Untitled')}
                    </Link>
                  ))}
                </section>
              )}
            </div>
          )}
        </main>
        {threads.open && owner && Companion && (
          <div ref={slot} className="dt-note-companion-slot">
            <Companion
              key={threads.open.key}
              pageId={docId}
              pageTitle={page?.title || ''}
              thread={threads.open}
              bound={threads.bound}
              threads={threads.threads}
              blockText={blockText}
              blockKind={blockKind}
              focus={focused}
              onAskFocus={draft => {
                if (!focused) return
                setFocus(null)
                ask({ blockId: focused, prompt: draft || undefined })
                scrollToBlock(focused, false)
              }}
              onDismissFocus={() => setFocus(null)}
              prefill={threads.prefill}
              onSend={threads.send}
              onMake={(kind, prompt, again) => {
                const anchor = threads.open?.blockId
                const redo = threads.open?.regenerate
                if (again && anchor && redo) {
                  // Another version of the block itself, filed for review.
                  if (!editor.current?.hasBlock(anchor)) {
                    setError(t('The line this conversation was about has been deleted.'))
                    return
                  }
                  editor.current.updateLearningPrompt(anchor, prompt)
                  threads.send(
                    `${t('Regenerate')} · ${t(learningKind(redo.kind).label)} · ${prompt || t('Generate this learning block from the page')}`,
                    { generate: { blockId: anchor, kind: redo.kind, config: redo.config } }
                  )
                  return
                }
                const blockId =
                  anchor && editor.current?.hasBlock(anchor)
                    ? editor.current.insertLearningAfter(anchor, kind, prompt)
                    : null
                if (!blockId) {
                  setError(t('The line this conversation was about has been deleted.'))
                  return
                }
                threads.send(
                  `${t(learningKind(kind).label)} · ${prompt || t('Generate this learning block from the page')}`,
                  { generate: { blockId, kind } }
                )
              }}
              onRegenerate={threads.regenerate}
              onSelect={openThread}
              onNewHere={() =>
                threads.open && ask({ blockId: threads.open.blockId, quote: threads.open.quote })
              }
              onJump={() => threads.open && scrollToBlock(threads.open.blockId)}
              onSuggestions={refreshSuggestions}
              onClose={foldPanel}
            />
          </div>
        )}
      </div>
      {sources && (
        <SourcePicker
          onClose={() => setSources(false)}
          onInsert={(title, markdown, url, id) =>
            editor.current?.insertClip(title, markdown, url, id)
          }
          onKnowledge={name => {
            const blockId = editor.current?.cursorBlockId() || latest.current?.blocks?.[0]?.id
            if (blockId)
              ask({
                blockId,
                knowledgeRef: name,
                prompt: `${t('Find source passages in this knowledge base and suggest cited notes')}: ${name}`,
              })
          }}
        />
      )}
      {favorites && (
        <FavoritesPicker
          onSynthesize={sources =>
            askAtCursor(
              `${t('Organize these favorites into a coherent note. Cite the source of each section.')}\n\n${sources}`
            )
          }
          onClose={() => setFavorites(false)}
          onInsert={clips => {
            editor.current?.insertClips(clips)
            setFavorites(false)
          }}
        />
      )}
    </div>
  )
}
