'use client'
import dynamic from 'next/dynamic'
import Image from 'next/image'
import { useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  favoriteAnswer,
  favoriteHeadings,
  favoriteKind,
  favoriteMedia,
  favoriteTranscript,
} from '@/lib/favorite-content'

const Markdown = dynamic(() => import('@/components/common/MarkdownRenderer'), { ssr: false })

const ROLE: Record<string, string> = {
  user: 'user',
  assistant: 'assistant',
  system: 'system',
  用户: 'user',
  助手: 'assistant',
  系统: 'system',
}

/** Read-only source content. Opening a favorite never starts an AI run or changes the archive. */
export default function NotebookFavoriteContent({
  type,
  markdown,
  metadata = {},
}: {
  type: string
  markdown: string
  metadata?: Record<string, unknown>
}) {
  const { t } = useTranslation()
  const root = useRef<HTMLDivElement>(null)
  const mediaRef = useRef<HTMLVideoElement>(null)
  const kind = favoriteKind(type, metadata)
  const transcript = ['chat', 'tutorbot'].includes(kind) ? favoriteTranscript(markdown) : []
  const answer = ['question', 'solve'].includes(kind) ? favoriteAnswer(markdown) : null
  const media = favoriteMedia(metadata)
  const chapters =
    kind === 'video_learning'
      ? [...markdown.matchAll(/^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)$/gm)]
      : []
  const article = ['research', 'reading', 'co_writer', 'guided_learning'].includes(kind)
  const headingLines = article ? favoriteHeadings(markdown) : []
  return (
    <div ref={root} className={`dt-favorite-content dt-favorite-content-${kind}`}>
      {media?.kind === 'video' && (
        <video
          ref={mediaRef}
          controls
          preload="metadata"
          src={media.url}
          className="w-full rounded-lg"
        />
      )}
      {media?.kind === 'audio' && (
        <audio controls preload="metadata" src={media.url} className="w-full" />
      )}
      {media?.kind === 'image' && (
        <Image
          unoptimized
          src={media.url}
          width={960}
          height={640}
          alt={String(metadata.caption || '')}
          className="h-auto max-w-full rounded-lg"
        />
      )}
      {chapters.length > 0 && media?.kind === 'video' && (
        <div className="dt-fav-chapters" aria-label={t('Video chapters')}>
          {chapters.map((chapter, index) => (
            <button
              key={index}
              type="button"
              className="dt-fav-chapter"
              onClick={() => {
                if (mediaRef.current)
                  mediaRef.current.currentTime = chapter[1]
                    .split(':')
                    .reduce((time, part) => time * 60 + Number(part), 0)
              }}
            >
              {chapter[1]} · {chapter[2]}
            </button>
          ))}
        </div>
      )}
      {headingLines.length > 2 && (
        <details className="dt-fav-toc">
          <summary>{t('Contents')}</summary>
          <nav aria-label={t('Contents')}>
            {headingLines.map((line, i) => (
              <button
                key={i}
                type="button"
                onClick={() => {
                  root.current
                    ?.querySelectorAll(
                      '[data-favorite-document] h1, [data-favorite-document] h2, [data-favorite-document] h3'
                    )
                    [i]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
                }}
              >
                {line}
              </button>
            ))}
          </nav>
        </details>
      )}
      <div data-favorite-document>
        {transcript.length ? (
          // Drawn the way the conversation looked: the learner's turns as
          // bubbles on the right, the replies as the page they were.
          <div className="dt-fav-transcript">
            {transcript.map((turn, i) => {
              const role = ROLE[turn.role.toLowerCase()] || ''
              return role === 'user' ? (
                <div key={i} className="dt-fav-turn is-user">
                  <Markdown content={turn.content.trim()} variant="compact" />
                </div>
              ) : (
                <section key={i} className="dt-fav-turn is-assistant">
                  {role === 'system' && <div className="dt-fav-turn-role">{t('System')}</div>}
                  <Markdown content={turn.content} />
                </section>
              )
            })}
          </div>
        ) : answer ? (
          <>
            <Markdown content={answer.question} />
            <details className="dt-fav-answer">
              <summary>{t('Show answer and explanation')}</summary>
              <div className="dt-fav-answer-body">
                <Markdown content={answer.answer} />
              </div>
            </details>
          </>
        ) : (
          <Markdown content={markdown} />
        )}
      </div>
    </div>
  )
}
