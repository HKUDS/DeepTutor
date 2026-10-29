'use client'

import { useEffect, useState } from 'react'
import { createReactBlockSpec, createReactInlineContentSpec } from '@blocknote/react'
import { useTranslation } from 'react-i18next'
import {
  Info,
  Lightbulb,
  AlertTriangle,
  ChevronRight,
  Globe,
  ExternalLink,
  Pencil,
  ListTree,
  FileCode,
} from 'lucide-react'
import dynamic from 'next/dynamic'
import type { NoteBlock } from '@/lib/notes-api'
import { safeNoteUrl } from '../model/urls'

const TaskView = dynamic(() => import('./NoteTaskView'), { ssr: false })

export const callout = createReactBlockSpec(
  { type: 'callout', propSchema: { tone: { default: 'tip' } }, content: 'inline' },
  {
    render: function Callout({ block, editor, contentRef }) {
      const { t } = useTranslation()
      const icons = { tip: Lightbulb, info: Info, warning: AlertTriangle }
      const tone = block.props.tone as keyof typeof icons
      const Icon = icons[tone] || Info
      return (
        <div className="dt-note-callout" data-tone={tone}>
          <button
            contentEditable={false}
            aria-label={t('Change callout style')}
            onClick={() => {
              const tones = Object.keys(icons)
              editor.updateBlock(block, {
                props: { tone: tones[(tones.indexOf(tone) + 1) % tones.length] },
              })
            }}
          >
            <Icon size={20} />
          </button>
          <div ref={contentRef} className="dt-note-callout-text" />
        </div>
      )
    },
  }
)

export const toggleHeading = createReactBlockSpec(
  {
    type: 'toggleHeading',
    propSchema: { level: { default: 2 }, collapsed: { default: false } },
    content: 'inline',
  },
  {
    render: ({ block, contentRef }) => (
      <div
        role="heading"
        aria-level={block.props.level}
        className={`dt-note-toggle-title level-${block.props.level}`}
        ref={contentRef}
      />
    ),
    renderFrame: function Toggle({ block, editor, slotRef }) {
      const { t } = useTranslation()
      return (
        <div className="dt-note-toggle" data-collapsed={block.props.collapsed}>
          <button
            contentEditable={false}
            aria-label={t(block.props.collapsed ? 'Expand' : 'Collapse')}
            aria-expanded={!block.props.collapsed}
            onClick={() =>
              editor.updateBlock(block, { props: { collapsed: !block.props.collapsed } })
            }
          >
            <ChevronRight size={17} />
          </button>
          <div className="dt-note-toggle-body" ref={slotRef} />
        </div>
      )
    },
  }
)
export const noteColumn = createReactBlockSpec(
  { type: 'noteColumn', content: 'none', propSchema: {}, layoutOnly: true, placeable: 'namedOnly' },
  { renderFrame: ({ slotRef }) => <div className="dt-note-column" ref={slotRef} /> }
)
export const noteColumns = createReactBlockSpec(
  {
    type: 'noteColumns',
    content: 'none',
    propSchema: {},
    layoutOnly: true,
    children: { allow: ['noteColumn'], min: 2, dissolve: true },
  },
  { renderFrame: ({ slotRef }) => <div className="dt-note-columns" ref={slotRef} /> }
)
export const tableOfContents = createReactBlockSpec(
  { type: 'tableOfContents', content: 'none', propSchema: {} },
  {
    render: function Contents({ editor }) {
      const { t } = useTranslation()
      const [headings, setHeadings] = useState<NoteBlock[]>([])
      useEffect(() => {
        const refresh = () => {
          const result: NoteBlock[] = []
          const walk = (blocks: NoteBlock[]) =>
            blocks.forEach(b => {
              if (b.type === 'heading' || b.type === 'toggleHeading') result.push(b)
              walk(b.children || [])
            })
          walk(editor.document as NoteBlock[])
          setHeadings(result)
        }
        refresh()
        return editor.onChange(refresh)
      }, [editor])
      return (
        <nav className="dt-note-toc" contentEditable={false} aria-label={t('Table of contents')}>
          <div className="dt-note-block-label">
            <ListTree size={15} />
            {t('Table of contents')}
          </div>
          {headings.length ? (
            headings.map(h => (
              <a
                key={h.id}
                href={`#${h.id}`}
                style={{ paddingInlineStart: `${(Number(h.props.level || 1) - 1) * 14}px` }}
                onClick={e => {
                  e.preventDefault()
                  editor.setTextCursorPosition(h.id, 'start')
                  editor.domElement
                    ?.querySelector(`[data-id="${CSS.escape(h.id)}"]`)
                    ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
                  history.replaceState(history.state, '', `#${h.id}`)
                }}
              >
                {Array.isArray(h.content)
                  ? h.content.map(c => c.text || c.props?.title || '').join('') || t('Untitled')
                  : t('Untitled')}
              </a>
            ))
          ) : (
            <p>{t('Headings in this page appear here automatically')}</p>
          )}
        </nav>
      )
    },
  }
)

export const webCard = createReactBlockSpec(
  {
    type: 'webCard',
    content: 'none',
    propSchema: {
      url: { default: '' },
      title: { default: '' },
      description: { default: '' },
      mode: { default: 'bookmark' },
    },
  },
  {
    render: function WebCard({ block, editor }) {
      const { t } = useTranslation()
      const [edit, setEdit] = useState(!block.props.url)
      const [url, setUrl] = useState(block.props.url)
      const [title, setTitle] = useState(block.props.title)
      const [description, setDescription] = useState(block.props.description)
      const [error, setError] = useState('')
      const safe = safeNoteUrl(block.props.url)
      const host = safe && /^https?:/.test(safe) ? new URL(safe).hostname : ''
      return (
        <div contentEditable={false} className="dt-note-web-card">
          {edit ? (
            <form
              onSubmit={e => {
                e.preventDefault()
                const normalized = url.trim()
                if (!safeNoteUrl(normalized) || !/^https?:/i.test(normalized)) {
                  setError(t('Enter an HTTP or HTTPS URL'))
                  return
                }
                editor.updateBlock(block, {
                  props: { url: normalized, title: title.trim(), description: description.trim() },
                })
                setEdit(false)
                setError('')
              }}
            >
              <label>
                {t('Link URL')}
                <input
                  autoFocus
                  type="url"
                  required
                  value={url}
                  onChange={e => setUrl(e.target.value)}
                  placeholder={t('https://')}
                />
              </label>
              <label>
                {t('Title')}
                <input value={title} onChange={e => setTitle(e.target.value)} />
              </label>
              <label>
                {t('Description')}
                <input value={description} onChange={e => setDescription(e.target.value)} />
              </label>
              {error && <p role="alert">{error}</p>}
              <div className="dt-note-form-actions">
                {block.props.url && (
                  <button className="dt-note-action" type="button" onClick={() => setEdit(false)}>
                    {t('Cancel')}
                  </button>
                )}
                <button className="dt-note-action is-primary" type="submit">
                  {t('Save')}
                </button>
              </div>
            </form>
          ) : (
            <>
              <div className="dt-note-web-card-header">
                <Globe size={22} />
                <a href={safe || undefined} target="_blank" rel="noopener noreferrer">
                  <strong>{block.props.title || host}</strong>
                  <span>{block.props.description || block.props.url}</span>
                  <small>
                    {host} <ExternalLink size={11} />
                  </small>
                </a>
                <button aria-label={t('Edit link')} onClick={() => setEdit(true)}>
                  <Pencil size={14} />
                </button>
              </div>
              {block.props.mode === 'embed' && safe && (
                <>
                  <iframe
                    title={block.props.title || host}
                    src={safe}
                    sandbox="allow-scripts allow-presentation"
                    referrerPolicy="no-referrer"
                    loading="lazy"
                  />
                  <p className="dt-note-hint">
                    {t('If the site blocks embedding, open the link above')}
                  </p>
                </>
              )}
            </>
          )}
        </div>
      )
    },
  }
)
export const htmlEmbed = createReactBlockSpec(
  { type: 'htmlEmbed', content: 'none', propSchema: { source: { default: '' } } },
  {
    render: function HtmlEmbed({ block, editor }) {
      const { t } = useTranslation()
      const [editing, setEditing] = useState(!block.props.source)
      return (
        <div contentEditable={false} className="dt-note-html">
          <div className="dt-note-block-label">
            <FileCode size={14} aria-hidden />
            <span>{t('HTML')}</span>
            <span className="dt-note-segment" role="group" aria-label={t('HTML')}>
              <button aria-pressed={editing} onClick={() => setEditing(true)}>
                {t('Edit')}
              </button>
              <button aria-pressed={!editing} disabled={!block.props.source.trim()} onClick={() => setEditing(false)}>
                {t('Preview')}
              </button>
            </span>
          </div>
          {editing ? (
            <textarea
              autoFocus
              aria-label={t('HTML source')}
              value={block.props.source}
              onChange={e => editor.updateBlock(block, { props: { source: e.target.value } })}
              spellCheck={false}
              placeholder={t('<h2>...</h2>')}
            />
          ) : (
            <iframe
              title={t('HTML preview')}
              sandbox=""
              srcDoc={`<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https: data:; style-src 'unsafe-inline';"><style>body{font:15px system-ui;line-height:1.6;padding:16px;overflow-wrap:anywhere}</style>${block.props.source}`}
            />
          )}
        </div>
      )
    },
  }
)
export const taskView = createReactBlockSpec(
  { type: 'taskView', content: 'none', propSchema: { view: { default: 'table' } } },
  {
    render: ({ block, editor }) => (
      <div contentEditable={false} className="dt-note-data-view">
        <TaskView
          view={block.props.view}
          onViewChange={view => editor.updateBlock(block, { props: { view } })}
        />
      </div>
    ),
  }
)
export const noteDate = createReactInlineContentSpec(
  { type: 'noteDate', content: 'none', propSchema: { date: { default: '' } } },
  {
    render: function DateInline({ inlineContent, updateInlineContent }) {
      const { t } = useTranslation()
      return (
        <input
          className="dt-note-date"
          contentEditable={false}
          aria-label={t('Date')}
          type="date"
          value={inlineContent.props.date}
          onChange={e => updateInlineContent({ type: 'noteDate', props: { date: e.target.value } })}
        />
      )
    },
  }
)
