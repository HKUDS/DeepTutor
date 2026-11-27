'use client'

import { defaultBlockSpecs } from '@blocknote/core'
import { createReactBlockSpec } from '@blocknote/react'
import { FileText, ArrowUpRight } from 'lucide-react'
import { apiUrl } from '@/lib/api'
import { safeNoteUrl } from '../model/urls'

export const noteFile = createReactBlockSpec(defaultBlockSpecs.file.config, {
  render: ({ block }) => {
    const url = safeNoteUrl(block.props.url)
    return (
      <div className="dt-note-file" contentEditable={false}>
        <a href={url ? apiUrl(url) : undefined} target="_blank" rel="noopener noreferrer">
          <FileText size={20} aria-hidden="true" />
          <span>{block.props.name || block.props.url}</span>
          <ArrowUpRight size={16} aria-hidden="true" />
        </a>
        {block.props.caption && <p>{block.props.caption}</p>}
      </div>
    )
  },
})
