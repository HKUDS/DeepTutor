'use client'

import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { createPortal } from 'react-dom'
import { closeHistory } from '@tiptap/pm/history'
import { SideMenuExtension } from '@blocknote/core/extensions'
import type { BlockNoteEditor, BlockSchema, InlineContentSchema, StyleSchema } from '@blocknote/core'
import type { NoteBlock } from '@/lib/notes-api'
import { canMoveNoteBlock, moveNoteBlock } from '../model/move-block'

type Drop = { id: string; side: 'before' | 'after'; x: number; y: number; width: number }

export default function useNoteBlockDrag<B extends BlockSchema, I extends InlineContentSchema, S extends StyleSchema>(editor: BlockNoteEditor<B, I, S>) {
  const gesture = useRef<{ id: string; x: number; y: number; moved: boolean } | null>(null)
  const suppressClick = useRef(false)
  const [drop, setDrop] = useState<Drop | null>(null)
  const menu = editor.getExtension(SideMenuExtension)
  const cancel = () => { gesture.current = null; setDrop(null); menu?.unfreezeMenu() }
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && gesture.current) {
        gesture.current = null
        setDrop(null)
        menu?.unfreezeMenu()
      }
    }
    window.addEventListener('keydown', escape)
    return () => {
      window.removeEventListener('keydown', escape)
      if (gesture.current) menu?.unfreezeMenu()
    }
  }, [menu])
  const destination = (event: PointerEvent<HTMLButtonElement>): Drop | null => {
    const element = document.elementFromPoint(event.clientX, event.clientY)
      ?.closest<HTMLElement>('.bn-block-outer[data-id]')
    if (!element || !editor.domElement?.contains(element)) return null
    const id = element.dataset.id!
    const content = element.querySelector<HTMLElement>('.bn-block-content') || element
    const rect = content.getBoundingClientRect()
    const side = event.clientY < rect.top + rect.height / 2 ? 'before' : 'after'
    if (!gesture.current || !canMoveNoteBlock(editor.document as NoteBlock[], gesture.current.id, id)) return null
    return { id, side, x: rect.left, y: side === 'before' ? rect.top : element.getBoundingClientRect().bottom, width: rect.width }
  }
  return {
    consumeClick: () => {
      const suppressed = suppressClick.current
      suppressClick.current = false
      return suppressed
    },
    start: (event: PointerEvent<HTMLButtonElement>, id: string) => {
      if (event.button !== 0 || !editor.isEditable) return
      gesture.current = { id, x: event.clientX, y: event.clientY, moved: false }
      suppressClick.current = false
      menu?.freezeMenu()
      event.currentTarget.setPointerCapture(event.pointerId)
      event.preventDefault()
    },
    move: (event: PointerEvent<HTMLButtonElement>) => {
      const current = gesture.current
      if (!current) return
      if (Math.hypot(event.clientX - current.x, event.clientY - current.y) < 5 && !current.moved) return
      current.moved = true
      suppressClick.current = true
      setDrop(destination(event))
      const scroller = editor.domElement?.closest('main')
      if (scroller) {
        const rect = scroller.getBoundingClientRect()
        if (event.clientY < rect.top + 36) scroller.scrollTop -= 18
        if (event.clientY > rect.bottom - 36) scroller.scrollTop += 18
      }
    },
    end: (event: PointerEvent<HTMLButtonElement>) => {
      const current = gesture.current
      const target = current?.moved ? destination(event) : null
      if (current && target) {
        const blocks = moveNoteBlock(editor.document as NoteBlock[], current.id, target.id, target.side)
        if (blocks) {
          editor.transact(tr => closeHistory(tr))
          editor.replaceBlocks(editor.document, blocks as typeof editor.document)
          editor.transact(tr => closeHistory(tr))
          editor.setTextCursorPosition(current.id, 'start')
        }
      }
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
      gesture.current = null
      setDrop(null)
      if (current?.moved) menu?.unfreezeMenu()
    },
    cancel,
    indicator: drop && createPortal(<div className="dt-note-drop-line" style={{ left: drop.x, top: drop.y, width: drop.width }} />, document.body),
  }
}
