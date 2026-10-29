'use client'

import Image from 'next/image'
import { useTranslation } from 'react-i18next'
import {
  ArrowDown,
  ArrowUpRight,
  BookOpen,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronRight,
  FileText,
  Globe,
  Lightbulb,
  Pause,
  Play,
  Sparkles,
  Volume2,
} from 'lucide-react'
import type { BlockPreviewKind } from '../model/block-previews'
import NoteMath from './NoteMath'

/** Non-interactive samples: previews never create tasks, fetch media, or run AI. */
export default function NoteBlockPreview({
  kind,
  title,
}: {
  kind: BlockPreviewKind
  title?: string
}) {
  const { t } = useTranslation()
  const heading = (level: number, toggle = false) => (
    <div className="dt-note-preview-section">
      <div className={`dt-note-preview-heading level-${level}`}>
        {toggle && <ChevronDown size={15} />}
        {t(`Heading ${level}`)}
      </div>
      <p className={toggle ? 'dt-note-preview-toggle-body' : ''}>
        {t('Give this section a clear place in your notes.')}
      </p>
    </div>
  )
  const tasks = [t('Review the concept'), t('Try an example')]
  const checklist = (
    <div className="dt-note-preview-checks">
      {tasks.map((task, i) => (
        <div key={task} className={i === 0 ? 'done' : ''}>
          <span className="dt-note-preview-checkbox">{i === 0 && <Check size={10} />}</span>
          <span>{task}</span>
        </div>
      ))}
    </div>
  )
  const diagram = (
    <div className="dt-note-preview-diagram">
      <span>{t('Question')}</span>
      <ArrowDown size={16} />
      <span>{t('Explore the details')}</span>
      <ArrowDown size={16} />
      <span>{t('Key idea')}</span>
    </div>
  )
  const audio = (
    <div className="dt-note-preview-player">
      <Play size={15} />
      <span>0:00 / 3:24</span>
      <i />
      <Volume2 size={14} />
    </div>
  )
  const image = (
    <div className="dt-note-preview-image">
      <Image src="/brand/color-full.png" alt="" width={1600} height={313} unoptimized />
      <small>{t('Image caption')}</small>
    </div>
  )
  switch (kind) {
    case 'paragraph':
      return (
        <p className="dt-note-preview-paragraph">
          {t('Write a thought, connect it to what you know, and let the next idea follow.')}
        </p>
      )
    case 'heading':
      return heading(1)
    case 'heading_2':
      return heading(2)
    case 'heading_3':
      return heading(3)
    case 'heading_4':
      return heading(4)
    case 'toggle_heading_1':
      return heading(1, true)
    case 'toggle_heading_2':
      return heading(2, true)
    case 'toggle_heading_3':
      return heading(3, true)
    case 'bullet_list':
    case 'numbered_list': {
      const List = kind === 'numbered_list' ? 'ol' : 'ul'
      return (
        <List>
          <li>{t('Ask a question')}</li>
          <li>{t('Connect the ideas')}</li>
          <li>{t('Test your understanding')}</li>
        </List>
      )
    }
    case 'check_list':
      return checklist
    case 'toggle_list':
      return (
        <>
          <p className="dt-note-preview-row">
            <ChevronDown size={14} />
            {t('Explore the details')}
          </p>
          <div className="dt-note-preview-toggle-body">
            {t('Hide supporting notes until you need them.')}
          </div>
        </>
      )
    case 'quote':
      return <blockquote>{t('A useful passage, kept in context.')}</blockquote>
    case 'table':
      return (
        <table>
          <thead>
            <tr>
              <th>{t('Concept')}</th>
              <th>{t('Notes')}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{t('Fourier transform')}</td>
              <td>{t('Frequency')}</td>
            </tr>
            <tr>
              <td>{t('Derivative')}</td>
              <td>{t('Rate of change')}</td>
            </tr>
          </tbody>
        </table>
      )
    case 'divider':
      return (
        <>
          <p>{t('Key idea')}</p>
          <hr />
          <p className="dt-note-preview-muted">{t('Try an example')}</p>
        </>
      )
    case 'code_block':
      return (
        <div className="dt-note-preview-code">
          <small>{'Python'}</small>
          <pre>
            <code>{'def learn(topic):\n    return explore(topic)'}</code>
          </pre>
        </div>
      )
    case 'callout':
      return (
        <div className="dt-note-callout" data-tone="tip">
          <Lightbulb size={19} />
          <p>{t('Keep the key idea in sight.')}</p>
        </div>
      )
    case 'pageLink':
      return (
        <>
          <div className="dt-note-preview-page-link">
            <FileText size={17} />
            <span>{title || t('Fourier transform')}</span>
            <ArrowUpRight size={13} />
          </div>
          <small className="dt-note-preview-muted">{t('Open linked page')}</small>
        </>
      )
    case 'image':
      return image
    case 'video':
      return (
        <>
          <div className="dt-note-preview-video">
            <Play size={25} />
            <span>{t('Learning video')}</span>
          </div>
          <div className="dt-note-preview-player">
            <Play size={12} />
            <i />
            <span>0:00</span>
          </div>
        </>
      )
    case 'audio':
      return (
        <>
          <strong>{t('Audio recording')}</strong>
          {audio}
        </>
      )
    case 'file':
      return (
        <div className="dt-note-preview-file">
          <FileText size={26} />
          <div>
            <strong>
              {t('Notes')}
              {'.pdf'}
            </strong>
            <small>{'PDF · 2.4 MB'}</small>
          </div>
          <ArrowUpRight size={14} />
        </div>
      )
    case 'bookmark':
      return (
        <div className="dt-note-preview-bookmark">
          <strong>{t('Fourier transform')}</strong>
          <p>{t('From signals to frequencies.')}</p>
          <small>
            <Globe size={12} />
            {'wikipedia.org'}
            <ArrowUpRight size={11} />
          </small>
        </div>
      )
    case 'embed':
      return (
        <div className="dt-note-preview-window">
          <small>
            <Globe size={12} />
            {t('Embedded page')}
          </small>
          <div>{diagram}</div>
        </div>
      )
    case 'htmlEmbed':
      return (
        <div className="dt-note-preview-window">
          <small>
            {'HTML · '}
            {t('Preview')}
          </small>
          <div>
            <h3>{t('Key idea')}</h3>
            <p>{t('From signals to frequencies.')}</p>
            <span className="dt-note-preview-tag">{'f(x) → F(ω)'}</span>
          </div>
        </div>
      )
    case 'task_table':
      return (
        <table>
          <thead>
            <tr>
              <th>{t('Task')}</th>
              <th>{t('Status')}</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task, i) => (
              <tr key={task}>
                <td>{task}</td>
                <td>
                  <span className="dt-note-preview-tag">{t(i ? 'To do' : 'Done')}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )
    case 'task_board':
      return (
        <div className="dt-note-preview-board">
          {tasks.map((task, i) => (
            <div key={task}>
              <small>{t(i ? 'Done' : 'To do')} · 1</small>
              <article>{task}</article>
            </div>
          ))}
        </div>
      )
    case 'task_list':
      return (
        <div className="dt-note-preview-task-list">
          {checklist}
          <small>{t('Add task')}</small>
        </div>
      )
    case 'toc':
      return (
        <div className="dt-note-preview-toc">
          <strong>{t('Table of contents')}</strong>
          <span>{t('Fourier transform')}</span>
          <span>{t('Key idea')}</span>
          <span>{t('Try an example')}</span>
        </div>
      )
    case 'math':
      return <NoteMath formula="f(x) = x^2 + 2x + 1" display />
    case 'inlineMath':
      return (
        <p>
          {t('For example')}, <NoteMath formula="x^2 + y^2 = r^2" />.
        </p>
      )
    case 'columns_2':
    case 'columns_3':
    case 'columns_4':
    case 'columns_5':
      return (
        <div
          className="dt-note-preview-columns"
          style={{ gridTemplateColumns: `repeat(${kind.slice(-1)}, minmax(0, 1fr))` }}
        >
          {Array.from({ length: Number(kind.slice(-1)) }, (_, i) => (
            <div key={i}>
              <strong>{String.fromCharCode(65 + i)}</strong>
              <p>{['x + y', 'a² + b²', 'f(x)', '2πr', 'E = mc²'][i]}</p>
            </div>
          ))}
        </div>
      )
    case 'date':
      return (
        <p>
          {t('Review on')}{' '}
          <span className="dt-note-preview-date">
            <CalendarDays size={13} />
            2026-10-17
          </span>
        </p>
      )
    case 'mermaid':
      return diagram
    case 'quiz':
      return (
        <div className="dt-note-preview-quiz">
          <strong>{t('What does a derivative measure?')}</strong>
          <div>
            <span>A</span>
            {t('Frequency')}
          </div>
          <div className="answer">
            <span>B</span>
            {t('Rate of change')}
            <Check size={12} />
          </div>
          <small>{t('Check answer')}</small>
        </div>
      )
    case 'flashcards':
      return (
        <div className="dt-note-preview-flashcard">
          <small>1 / 8</small>
          <strong>{t('Fourier transform')}</strong>
          <span>{t('Tap to reveal the answer')}</span>
        </div>
      )
    case 'timeline':
      return (
        <div className="dt-note-preview-timeline">
          {['1807', '1822', '1965'].map((year, i) => (
            <div key={year}>
              <b>{year}</b>
              <span>{['Fourier', t('Heat theory'), 'FFT'][i]}</span>
            </div>
          ))}
        </div>
      )
    case 'research':
      return (
        <div className="dt-note-preview-research">
          <strong>{t('Fourier transform')}</strong>
          <p>
            {t('From signals to frequencies.')} <sup>[1]</sup>
          </p>
          <hr />
          <small>[1] {t('Sources and references')}</small>
        </div>
      )
    case 'task':
      return (
        <>
          <div className="dt-note-preview-row">
            <Check size={15} />
            <strong>{t('Study plan')}</strong>
          </div>
          {checklist}
          <small className="dt-note-preview-muted">
            {t('To do')} · {t('Task')}
          </small>
        </>
      )
    case 'animation':
      return (
        <>
          <div className="dt-note-preview-animation">
            <NoteMath formula="y = \sin(x)" />
            <div className="dt-note-preview-wave" />
          </div>
          <div className="dt-note-preview-player">
            <Pause size={13} />
            <i />
            <span>0:06 / 0:30</span>
          </div>
        </>
      )
    case 'concept_map':
      return (
        <div className="dt-note-preview-concepts">
          <strong>{t('Fourier transform')}</strong>
          <div>
            <span>{t('Frequency')}</span>
            <span>{t('Signals')}</span>
          </div>
        </div>
      )
    case 'geogebra':
      return (
        <div className="dt-note-preview-geometry">
          <svg viewBox="0 0 180 110" aria-hidden="true">
            <path d="M15 90H170M35 105V5" stroke="currentColor" opacity=".35" />
            <path d="M45 90L145 90L95 3.4Z" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <text x="33" y="85">
              A
            </text>
            <text x="148" y="85">
              B
            </text>
            <text x="100" y="10">
              C
            </text>
          </svg>
          <small>{'AB = AC = BC'}</small>
        </div>
      )
    case 'generated_image':
      return (
        <>
          {image}
          <small className="dt-note-preview-row">
            <Sparkles size={12} />
            {t('Generate image')}
          </small>
        </>
      )
    case 'podcast':
      return (
        <>
          <strong>{t('Fourier transform')}</strong>
          <small className="dt-note-preview-muted">{t('Podcast')} · 3:24</small>
          {audio}
          <p className="dt-note-preview-transcript">{t('From signals to frequencies.')}</p>
        </>
      )
    case 'ai':
      return (
        <div className="dt-note-preview-ai">
          <p>{t('Photosynthesis turns light into chemical energy.')}</p>
          <p className="is-suggested">
            {t('Plants capture light in chlorophyll, then use it to build sugar from water and carbon dioxide.')}
          </p>
          <small className="dt-note-preview-row">
            <Sparkles size={12} />
            {t('Dito suggests · you accept or dismiss')}
          </small>
        </div>
      )
    case 'source':
      return (
        <>
          <blockquote>{t('A useful passage, kept in context.')}</blockquote>
          <small className="dt-note-preview-row">
            <BookOpen size={13} />
            {t('Source')} · {t('Page')} 12
          </small>
        </>
      )
    case 'favorite':
      return (
        <div className="dt-note-preview-research">
          <small>
            {t('Chat')} · {t('Saved original')}
          </small>
          <div className="dt-note-preview-row">
            <ChevronRight size={14} />
            <strong>{t('Saved answer')}</strong>
          </div>
          <p>{t('Keep the key idea in sight.')}</p>
          <small>
            {t('Show original content')} · {t('Return to source')}
          </small>
        </div>
      )
    default: {
      const exhaustive: never = kind
      return exhaustive
    }
  }
}
