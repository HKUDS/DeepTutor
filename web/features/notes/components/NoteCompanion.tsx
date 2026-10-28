'use client'
/**
 * Dito — a conversation held at one line of the page.
 *
 * The panel opens on a line (a selection, the line's own "ask" orb, a
 * learning block's Generate) and shows that line's conversation; closing it
 * folds the conversation back onto the line as an orb. It can switch to any
 * other conversation on the page, and the page scrolls to where that one
 * was held.
 *
 * The transcript is the main chat's own component, since the conversation is
 * an ordinary session in the shared runtime. The composer is the notebook's:
 * on a page Dito explains, rewrites and makes learning material in place, so
 * it offers that instead of chat's modes, skills and connectors.
 */
import './note-companion.css'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ArrowUp,
  Check,
  FilePlus2,
  Files,
  Languages,
  Lightbulb,
  ListChecks,
  MessageSquareText,
  MessagesSquare,
  Minimize2,
  PenLine,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Square,
  TextQuote,
  X,
  AlignLeft,
  WandSparkles,
} from 'lucide-react'
import { ChatMessageList, RoughActionButton } from '@/features/chat/messages'
import {
  useChatStateAdapter,
  type MessageAttachment,
  type MessageItem,
} from '@/features/chat/ChatStateAdapter'
import { buildSessionActivity } from '@/components/chat/home/SessionActivityPanel'
import SessionViewerPanel, {
  type SessionViewerPanelHandle,
} from '@/components/chat/home/SessionViewerPanel'
import { ChatViewerBridges } from '@/components/chat/home/ChatViewerBridges'
import ModelSelector from '@/components/chat/home/ModelSelector'
import { COMMAND_CONFIRMATION_FAILED } from '@/features/chat/transport/command-delivery'
import { useChatAutoScroll } from '@/hooks/useChatAutoScroll'
import { useMeasuredHeight } from '@/hooks/useMeasuredHeight'
import { useResearchOutlineContinuation } from '@/hooks/useResearchOutlineContinuation'
import { hasPendingAskUser, REPLY_SENT_AS_NEW_MESSAGE } from '@/lib/ask-user-state'
import { copyText } from '@/lib/clipboard'
import { listLLMOptions, type LLMOption } from '@/lib/llm-options'
import type { LLMSelection } from '@/features/chat/model/protocol'
import { notify } from '@/lib/notifications'
import { createNote, noteRequest, saveNote } from '@/lib/notes-api'
import Tooltip from '@/shared/ui/Tooltip'
import { useMenuPopover } from '@/shared/ui/useMenuPopover'
import { resultLearningBlock } from '../model/results'
import { LEARNING_KINDS, learningKind } from '../model/learning-kinds'
import { relativeTime, type NoteThreadView } from '../model/threads'
import type { NoteCompanionProps } from './note-companion-props'

const COMPOSER_FADE = 'linear-gradient(to bottom, #000 calc(100% - 28px), transparent)'
/** What can be made at a line from the composer; a task is not generated. */
const MAKE_KINDS = LEARNING_KINDS.filter(kind => kind.kind !== 'task')

const ABOUT_SELECTION = [
  { label: 'Explain this', prompt: 'Explain this passage in plain words.', Icon: Lightbulb },
  {
    label: 'Rewrite',
    prompt: 'Rewrite this passage more clearly and suggest it as an edit.',
    Icon: PenLine,
  },
  {
    label: 'Make shorter',
    prompt: 'Shorten this passage and suggest it as an edit.',
    Icon: Minimize2,
  },
  { label: 'Give an example', prompt: 'Give a concrete example of this.', Icon: MessageSquareText },
  {
    label: 'Translate',
    prompt: 'Translate this passage and suggest it as an edit.',
    Icon: Languages,
  },
  {
    label: 'Quiz me on this',
    prompt: 'Ask me two questions to check I understand this.',
    Icon: ListChecks,
  },
]
const ABOUT_LINE = [
  {
    label: 'Continue writing here',
    prompt: 'Continue writing from this line and suggest it as an insert.',
    Icon: PenLine,
  },
  { label: 'Explain this part', prompt: 'Explain this part of my notes.', Icon: Lightbulb },
  {
    label: 'Check the facts',
    prompt: 'Check the facts around this line and comment on anything wrong.',
    Icon: ShieldCheck,
  },
  { label: 'Summarize this page', prompt: 'Summarize this page.', Icon: AlignLeft },
]

/** About a card on the page: a learning block, a figure, an embed. */
const ABOUT_CARD = [
  {
    label: 'Walk me through this',
    prompt: 'Walk me through this block: what it shows, step by step, and why it matters.',
    Icon: Lightbulb,
  },
  {
    label: 'Quiz me on this',
    prompt: 'Ask me two questions to check I understand this block.',
    Icon: ListChecks,
  },
  {
    label: 'Improve this block',
    prompt: 'Fix mistakes and fill gaps in this block, and suggest the improved block as an edit.',
    Icon: PenLine,
  },
  {
    label: 'Check the facts',
    prompt: 'Check the facts in this block and comment on anything wrong.',
    Icon: ShieldCheck,
  },
]
const CARD_TYPES = new Set([
  'learning',
  'image',
  'video',
  'audio',
  'file',
  'webCard',
  'htmlEmbed',
  'math',
  'clip',
  'table',
  'codeBlock',
])
const isCard = (kind: string | null) => !!kind && CARD_TYPES.has(kind.split(':')[0])
/** The icon a block is named with: its learning kind's, or a quote mark. */
function BlockIcon({ kind }: { kind: string | null }) {
  const Icon = kind?.startsWith('learning:') ? learningKind(kind.slice(9)).Icon : TextQuote
  return <Icon size={13} strokeWidth={1.8} aria-hidden />
}

function resultBlock(message: MessageItem) {
  const event = [...(message.events || [])].reverse().find(e => e.type === 'result')
  if (!event) return undefined
  const result = (event.metadata || {}) as Record<string, unknown>
  return resultLearningBlock(
    result,
    String(result.response || event.content || message.content || '')
  )
}


export default function NoteCompanion(props: NoteCompanionProps) {
  // Inside /chat's viewer the shared runtime is showing the conversation the
  // learner is in; a second thread here would switch it underneath them.
  const pathname = usePathname() || ''
  if (!pathname.startsWith('/co-writer')) return <EmbeddedNotice {...props} />
  return <ThreadPanel {...props} />
}

function EmbeddedNotice({ pageId, onClose }: NoteCompanionProps) {
  const { t } = useTranslation()
  return (
    <aside className="dt-note-companion" aria-label={t('Dito')}>
      <header className="dt-note-companion-head">
        <Sparkles
          size={15}
          strokeWidth={1.8}
          className="shrink-0 text-[var(--primary)]"
          aria-hidden
        />
        <h2 className="flex-1">{t('Dito')}</h2>
        <button className="dt-note-icon-button" aria-label={t('Close')} onClick={onClose}>
          <X size={16} strokeWidth={1.7} />
        </button>
      </header>
      <div className="dt-note-companion-welcome">
        <p>{t('Dito works beside the page in the notebook, so this conversation stays yours.')}</p>
        <Link className="dt-note-companion-link" href={`/co-writer/${encodeURIComponent(pageId)}`}>
          {t('Open in the notebook')} →
        </Link>
      </div>
    </aside>
  )
}

function ThreadPanel({
  pageId,
  thread,
  bound,
  threads,
  blockText,
  blockKind,
  focus,
  onAskFocus,
  onDismissFocus,
  prefill,
  onSend,
  onMake,
  onRegenerate,
  onSelect,
  onNewHere,
  onJump,
  onSuggestions,
  onClose,
}: NoteCompanionProps) {
  const { t } = useTranslation()
  const {
    state,
    submitUserReply,
    cancelStreamingTurn,
    setLLMSelection,
    deleteTurn,
    editMessage,
    switchBranch,
    loadMessageTrace,
    releaseMessageTrace,
  } = useChatStateAdapter()
  const confirmResearchOutline = useResearchOutlineContinuation()
  const [error, setError] = useState('')
  const [savedPage, setSavedPage] = useState('')
  const [viewerOpen, setViewerOpen] = useState(false)
  const viewerPanelRef = useRef<SessionViewerPanelHandle | null>(null)
  const messages = useMemo(() => (bound ? state.messages : []), [bound, state.messages])
  const streaming = bound && state.isStreaming
  const lastMessage = messages[messages.length - 1]
  const awaitingUserReply = hasPendingAskUser(lastMessage?.events)
  const current = threads.find(item => item.session_id === thread.sessionId)
  const anchorText = blockText(thread.blockId)

  /* ── What a reply can become ──────────────────────────────────────── */
  const insertHere = useCallback(
    (message: MessageItem) => {
      const block = resultBlock(message)
      void noteRequest(`/${pageId}/suggestions`, {
        operation: 'insert',
        // After the line this conversation is about; at the end if it is gone.
        block_id: anchorText === null ? '' : thread.blockId,
        markdown: message.content,
        blocks: block ? [block] : undefined,
        explanation: t('Dito'),
      })
        .then(() => {
          onSuggestions()
          notify(t('Added below the line for your review'))
        })
        .catch(e => setError(String(e)))
    },
    [anchorText, onSuggestions, pageId, t, thread.blockId]
  )
  const saveAsSubpage = useCallback(
    async (message: MessageItem) => {
      try {
        const block = resultBlock(message)
        const doc = await createNote(t('Research notes'), pageId, message.content)
        if (block) await saveNote(doc.id, { blocks: [block], expected_revision: doc.revision })
        setSavedPage(doc.id)
      } catch (err) {
        setError(String(err))
      }
    },
    [pageId, t]
  )
  const replyActions = useCallback(
    (message: MessageItem) => (
      <>
        <RoughActionButton
          icon={FilePlus2}
          label={t('Insert below the line')}
          onClick={() => insertHere(message)}
        />
        <RoughActionButton
          icon={Files}
          label={t('Save as subpage')}
          onClick={() => void saveAsSubpage(message)}
        />
      </>
    ),
    [insertHere, saveAsSubpage, t]
  )

  const submit = useCallback(
    (content: string, make: string | null, again = false) => {
      setError('')
      setSavedPage('')
      if (make) {
        onMake(make, content, again)
        return
      }
      // A turn paused on a question: what was typed is the answer.
      if (awaitingUserReply) {
        void submitUserReply({ text: content })
          .then(sent => {
            if (sent) return
            notify(t(REPLY_SENT_AS_NEW_MESSAGE))
            onSend(content)
          })
          .catch(() => notify(t(COMMAND_CONFIRMATION_FAILED), { tone: 'error' }))
        return
      }
      onSend(content)
    },
    [awaitingUserReply, onMake, onSend, submitUserReply, t]
  )

  /* ── Transcript scrolling: /chat's pin-to-bottom ──────────────────── */
  const { ref: composerBoxRef, height: composerHeight } = useMeasuredHeight<HTMLDivElement>()
  const { containerRef, endRef, shouldAutoScrollRef, handleScroll } = useChatAutoScroll({
    hasMessages: messages.length > 0,
    isStreaming: streaming,
    composerHeight,
    messageCount: messages.length,
    lastMessageContent: lastMessage?.content,
    lastEventCount: lastMessage?.events?.length,
  })
  useEffect(() => {
    if (!streaming) return
    shouldAutoScrollRef.current = true
    const el = containerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [containerRef, shouldAutoScrollRef, streaming])

  const activity = useMemo(() => buildSessionActivity(messages), [messages])
  const quote = thread.quote || anchorText || ''
  const anchorKind = blockKind(thread.blockId)
  const starters = thread.quote ? ABOUT_SELECTION : isCard(anchorKind) ? ABOUT_CARD : ABOUT_LINE
  const focusText = focus ? blockText(focus) : null
  const focusTarget =
    focus && focusText !== null
      ? { label: focusText || t('Empty line'), kind: blockKind(focus) }
      : null
  // Opened from a block's "Regenerate…": the first make is that block again.
  const [make, setMake] = useState<string | null>(thread.regenerate?.kind ?? null)
  const [again, setAgain] = useState(Boolean(thread.regenerate))
  return (
    <aside className="dt-note-companion" aria-label={t('Dito')}>
      <header className="dt-note-companion-head">
        <Sparkles
          size={15}
          strokeWidth={1.8}
          className="shrink-0 text-[var(--primary)]"
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <h2 className="truncate">{current?.title || t('Dito')}</h2>
          <p>
            {streaming
              ? t('Working…')
              : current
                ? relativeTime(current.updated_at, state.language || 'en')
                : t('New conversation')}
          </p>
        </div>
        <ThreadSwitcher
          threads={threads}
          currentId={thread.sessionId}
          blockText={blockText}
          onSelect={onSelect}
        />
        <Tooltip label={t('New conversation at this line')} side="bottom">
          <button
            className="dt-note-icon-button"
            aria-label={t('New conversation at this line')}
            disabled={!messages.length}
            onClick={onNewHere}
          >
            <Plus size={16} strokeWidth={1.7} />
          </button>
        </Tooltip>
        <Tooltip label={t('Fold into the page')} side="bottom">
          <button className="dt-note-icon-button" aria-label={t('Close')} onClick={onClose}>
            <X size={16} strokeWidth={1.7} />
          </button>
        </Tooltip>
      </header>
      <button
        className="dt-note-anchor"
        data-gone={anchorText === null || undefined}
        onClick={onJump}
        disabled={anchorText === null}
      >
        <BlockIcon kind={thread.quote ? null : anchorKind} />
        <span>
          {anchorText === null
            ? t('The line this was about has been deleted')
            : quote || t('Empty line')}
        </span>
      </button>
      <div
        ref={containerRef}
        data-chat-scroll-root="true"
        className="dt-note-companion-thread"
        onScroll={() => {
          const el = containerRef.current
          if (!el) return
          if (el.scrollHeight - el.scrollTop - el.clientHeight < 80)
            shouldAutoScrollRef.current = true
          else if (!streaming) handleScroll()
        }}
        style={{ WebkitMaskImage: COMPOSER_FADE, maskImage: COMPOSER_FADE }}
      >
        {messages.length ? (
          <ChatMessageList
            messages={messages}
            isStreaming={streaming}
            sessionId={state.sessionId}
            language={state.language}
            onCopyAssistantMessage={content => copyText(content)}
            onRegenerateMessage={onRegenerate}
            onDeleteTurn={deleteTurn}
            selectedBranches={state.selectedBranches}
            onEditMessage={editMessage}
            onSwitchBranch={switchBranch}
            onSubmitUserReply={submitUserReply}
            onConfirmOutline={confirmResearchOutline}
            onPreviewAttachment={(attachment: MessageAttachment) => {
              setViewerOpen(true)
              viewerPanelRef.current?.openFileTab(attachment)
            }}
            onLoadMessageTrace={messageId =>
              state.sessionId ? loadMessageTrace(state.sessionId, messageId) : Promise.resolve()
            }
            onReleaseMessageTrace={messageId => {
              if (state.sessionId) releaseMessageTrace(state.sessionId, messageId)
            }}
            showModeBadge={false}
            compactActions
            assistantActions={replyActions}
          />
        ) : (
          <div className="dt-note-companion-welcome">
            <div className="dt-note-starters">
              {starters.map(({ label, prompt, Icon }) => (
                <button key={label} disabled={!bound} onClick={() => submit(t(prompt), null)}>
                  <Icon size={15} strokeWidth={1.7} />
                  {t(label)}
                </button>
              ))}
            </div>
            <p className="dt-note-make-title">{t('Make something here')}</p>
            <div className="dt-note-make-chips">
              {MAKE_KINDS.slice(0, 6).map(kind => (
                <button
                  key={kind.kind}
                  aria-pressed={make === kind.kind}
                  onClick={() => {
                    setMake(kind.kind)
                    setAgain(false)
                  }}
                >
                  <kind.Icon size={13} strokeWidth={1.8} />
                  {t(kind.label)}
                </button>
              ))}
            </div>
          </div>
        )}
        {savedPage && (
          <Link className="dt-note-companion-link" href={`/co-writer/${savedPage}`}>
            {t('Open saved subpage')} →
          </Link>
        )}
        {error && (
          <p role="alert" className="dt-note-companion-error">
            {error}
          </p>
        )}
        <div ref={endRef} className="h-px" />
      </div>
      <div ref={composerBoxRef} className="dt-note-companion-composer">
        <ThreadComposer
          key={thread.key}
          disabled={!bound}
          streaming={streaming}
          awaitingUserReply={awaitingUserReply}
          hasQuote={Boolean(thread.quote)}
          aboutCard={isCard(anchorKind)}
          focus={focusTarget}
          onAskFocus={onAskFocus}
          onDismissFocus={onDismissFocus}
          prefill={prefill}
          make={make}
          again={again && make === thread.regenerate?.kind}
          onMake={kind => {
            setMake(kind)
            if (kind === null) setAgain(false)
          }}
          llmSelection={state.llmSelection}
          onLLMSelectionChange={setLLMSelection}
          onSubmit={(content, kind) => {
            submit(content, kind, again && kind === thread.regenerate?.kind)
            setMake(null)
            setAgain(false)
          }}
          onStop={cancelStreamingTurn}
        />
      </div>
      <SessionViewerPanel
        ref={viewerPanelRef}
        open={viewerOpen}
        sessionId={state.sessionId}
        activity={activity}
        onClose={() => setViewerOpen(false)}
        onAutoOpen={() => setViewerOpen(true)}
      />
      <ChatViewerBridges viewerPanelRef={viewerPanelRef} />
    </aside>
  )
}

/** Every conversation on the page; picking one scrolls the page to its line. */
function ThreadSwitcher({
  threads,
  currentId,
  blockText,
  onSelect,
}: {
  threads: NoteThreadView[]
  currentId: string | null
  blockText: (blockId: string) => string | null
  onSelect: (sessionId: string) => void
}) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const menu = useMenuPopover<HTMLDivElement>(open, value => {
    setOpen(value)
    if (!value) setQuery('')
  })
  const needle = query.trim().toLowerCase()
  const rows = [...threads]
    .sort((a, b) => b.updated_at - a.updated_at)
    .filter(
      thread =>
        !needle ||
        [thread.label, thread.quote, thread.last_message, blockText(thread.block_id) || '']
          .join(' ')
          .toLowerCase()
          .includes(needle)
    )
  // Positioned against the panel header, not the button: the list must fit
  // inside the panel whatever sits to the button's right.
  return (
    <div ref={menu}>
      <Tooltip label={t('Conversations on this page')} side="bottom" suppressed={open}>
        <button
          className="dt-note-thread-switch"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          <MessagesSquare size={15} strokeWidth={1.7} />
          {threads.length > 0 && <span>{threads.length}</span>}
        </button>
      </Tooltip>
      {open && (
        <div
          className="dt-popover dt-note-thread-list"
          role="dialog"
          aria-label={t('Conversations on this page')}
        >
          <label className="dt-note-thread-search">
            <Search size={13} strokeWidth={1.8} aria-hidden />
            <input
              autoFocus
              value={query}
              placeholder={t('Search conversations on this page…')}
              onChange={e => setQuery(e.target.value)}
            />
          </label>
          <div className="dt-note-thread-list-rows">
            {rows.map(thread => {
              const line = blockText(thread.block_id)
              return (
                <button
                  key={thread.session_id}
                  className="dt-note-thread-row-main"
                  aria-current={thread.session_id === currentId || undefined}
                  onClick={() => {
                    setOpen(false)
                    setQuery('')
                    onSelect(thread.session_id)
                  }}
                >
                  <span className="dt-note-thread-row-head">
                    <span className="dt-note-orb is-static" data-state={thread.state} aria-hidden />
                    <strong>{thread.label}</strong>
                    <time>{relativeTime(thread.updated_at, i18n.language)}</time>
                  </span>
                  <span className="dt-note-thread-row-line">
                    {line === null ? t('Deleted line') : thread.quote || line || t('Empty line')}
                  </span>
                </button>
              )
            })}
            {!rows.length && (
              <p className="dt-note-menu-empty">
                {t(
                  threads.length ? 'No matching conversations' : 'No conversations on this page yet'
                )}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/** The notebook's composer: say what you want here, or make something here. */
function ThreadComposer({
  disabled,
  streaming,
  awaitingUserReply,
  hasQuote,
  aboutCard,
  focus,
  onAskFocus,
  onDismissFocus,
  prefill,
  make,
  again,
  onMake,
  llmSelection,
  onLLMSelectionChange,
  onSubmit,
  onStop,
}: {
  disabled: boolean
  streaming: boolean
  awaitingUserReply: boolean
  hasQuote: boolean
  aboutCard: boolean
  focus: { label: string; kind: string | null } | null
  onAskFocus: (draft: string) => void
  onDismissFocus: () => void
  prefill: { id: number; text: string } | null
  make: string | null
  /** The make fills the block being regenerated, not a new one below. */
  again: boolean
  onMake: (kind: string | null) => void
  llmSelection: LLMSelection | null
  onLLMSelectionChange: (value: LLMSelection | null) => void
  onSubmit: (content: string, make: string | null) => void
  onStop: () => void
}) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const input = useRef<HTMLTextAreaElement>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const menu = useMenuPopover<HTMLDivElement>(menuOpen, setMenuOpen)
  const [options, setOptions] = useState<LLMOption[]>([])
  const [activeDefault, setActiveDefault] = useState<LLMSelection | null>(null)
  const [optionsState, setOptionsState] = useState<'loading' | 'error' | 'ready'>('loading')
  const fetchOptions = useCallback(
    () =>
      listLLMOptions()
        .then(payload => {
          setOptions(payload.options)
          setActiveDefault(payload.active)
          setOptionsState('ready')
        })
        .catch(() => setOptionsState('error')),
    []
  )
  useEffect(() => {
    void fetchOptions()
  }, [fetchOptions])
  // A prompt handed over from the page lands in the box once, to be finished.
  const [prefilled, setPrefilled] = useState<number | null>(null)
  if (prefill && prefill.id !== prefilled) {
    setPrefilled(prefill.id)
    setText(prefill.text)
  }
  useEffect(() => {
    if (prefill) requestAnimationFrame(() => input.current?.focus())
  }, [prefill])
  useEffect(() => {
    if (!disabled) requestAnimationFrame(() => input.current?.focus({ preventScroll: true }))
  }, [disabled])
  useEffect(() => {
    if (make) input.current?.focus()
  }, [make])
  // Grow with the text up to a third of the panel.
  useEffect(() => {
    const el = input.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`
  }, [text])
  const target = make ? learningKind(make) : null
  const canSend =
    !disabled && (text.trim().length > 0 || Boolean(make)) && (!streaming || awaitingUserReply)
  const submit = () => {
    if (!canSend) return
    onSubmit(text.trim(), make)
    setText('')
  }
  return (
    <div className="dt-note-composer" data-disabled={disabled || undefined}>
      {focus && !target && (
        <div className="dt-note-composer-focus">
          <button
            className="dt-note-composer-focus-ask"
            onClick={() => {
              onAskFocus(text.trim())
              setText('')
            }}
          >
            <BlockIcon kind={focus.kind} />
            <span className="dt-note-composer-focus-label">{focus.label}</span>
            <span className="dt-note-composer-focus-cta">{t('Ask about this')}</span>
          </button>
          <button aria-label={t('Dismiss')} onClick={onDismissFocus}>
            <X size={12} strokeWidth={2} />
          </button>
        </div>
      )}
      {target && (
        <div className="dt-note-composer-target">
          <target.Icon size={13} strokeWidth={1.8} aria-hidden />
          <span>
            {again
              ? t('Regenerate this {{kind}}', { kind: t(target.label) })
              : t('Make a {{kind}} below this line', { kind: t(target.label) })}
          </span>
          <button aria-label={t('Cancel')} onClick={() => onMake(null)}>
            <X size={12} strokeWidth={2} />
          </button>
        </div>
      )}
      <textarea
        ref={input}
        rows={1}
        value={text}
        disabled={disabled}
        aria-label={t('Message Dito')}
        placeholder={t(
          target
            ? target.placeholder
            : awaitingUserReply
              ? 'Answer Dito…'
              : hasQuote
                ? 'Ask about the selection, or say how to change it…'
                : aboutCard
                  ? 'Ask about this block, or say how to change it…'
                  : 'Ask about this line, or tell Dito what to write…'
        )}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            submit()
          }
          if (e.key === 'Backspace' && !text && make) onMake(null)
        }}
      />
      <div className="dt-note-composer-bar">
        <div ref={menu} className="relative">
          <button
            className="dt-note-composer-make"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-pressed={Boolean(make)}
            disabled={disabled}
            onClick={() => setMenuOpen(!menuOpen)}
          >
            <WandSparkles size={14} strokeWidth={1.8} />
            {t('Make')}
          </button>
          {menuOpen && (
            <div className="dt-popover dt-note-kind-menu is-up" role="menu">
              <p className="dt-note-kind-menu-title">{t('Make below this line')}</p>
              {MAKE_KINDS.map(kind => (
                <button
                  key={kind.kind}
                  role="menuitemradio"
                  aria-checked={make === kind.kind}
                  className="dt-menu-item"
                  onClick={() => {
                    setMenuOpen(false)
                    onMake(kind.kind)
                  }}
                >
                  <kind.Icon size={14} strokeWidth={1.8} />
                  <span className="flex-1">{t(kind.label)}</span>
                  {make === kind.kind && <Check size={13} />}
                </button>
              ))}
            </div>
          )}
        </div>
        <span className="flex-1" />
        <ModelSelector
          options={options}
          activeDefault={activeDefault}
          value={llmSelection}
          loading={optionsState === 'loading'}
          error={optionsState === 'error'}
          onChange={onLLMSelectionChange}
          onRefresh={() => {
            setOptionsState('loading')
            void fetchOptions()
          }}
        />
        {streaming && !awaitingUserReply ? (
          <Tooltip label={t('Stop')}>
            <button
              className="dt-note-composer-send is-stop"
              aria-label={t('Stop')}
              onClick={onStop}
            >
              <Square size={11} fill="currentColor" />
            </button>
          </Tooltip>
        ) : (
          <button
            className="dt-note-composer-send"
            aria-label={t(make ? 'Make' : 'Send')}
            disabled={!canSend}
            onClick={submit}
          >
            {make ? <Sparkles size={14} /> : <ArrowUp size={15} strokeWidth={2} />}
          </button>
        )}
      </div>
    </div>
  )
}
