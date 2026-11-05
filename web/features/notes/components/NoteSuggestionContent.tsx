'use client'

import dynamic from 'next/dynamic'
import type { NoteBlock } from '@/lib/notes-api'
import { blockPreview } from '../model/blocks'
const Learning = dynamic(() => import('./NoteLearningContent'), { ssr: false })
const Markdown = dynamic(() => import('@/components/common/MarkdownRenderer'), { ssr: false })

export default function NoteSuggestionContent({
  blocks,
  markdown,
}: {
  blocks?: NoteBlock[] | null
  markdown: string
}) {
  if (!blocks?.length) return <Markdown content={markdown} />
  return (
    <>
      {blocks.map(block =>
        block.type === 'learning' ? (
          <Learning
            key={block.id}
            id={`review-${block.id}`}
            kind={String(block.props.kind || '')}
            prompt=""
            markdown={String(block.props.markdown || '')}
            data={String(block.props.data || '{}')}
            sourceUrl={String(block.props.sourceUrl || '')}
            readOnly
            onChange={() => {}}
          />
        ) : (
          <Markdown key={block.id} content={blockPreview(block)} />
        )
      )}
    </>
  )
}
