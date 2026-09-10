'use client'

import { browserStorage } from '@/shared/storage'

import { useCallback, useEffect, useRef, useState } from 'react'

interface ReadingPanelState {
  companionOpen: boolean
  navigatorOpen: boolean
}

const READING_LEARNING_KEY = 'reading-learning'

/** Learning mode owns the entry-time panel state, not just the boolean. */
function restoreReadingLearning(
  value: string | null,
  workspaceId: string
): ReadingPanelState | null {
  if (!value) return null
  try {
    const preference = JSON.parse(value) as {
      panels?: Partial<ReadingPanelState> & {
        navigatorCollapsed?: boolean
      }
      workspaceId?: string
    }
    const panels = preference.workspaceId === workspaceId ? preference.panels : null
    if (!panels || typeof panels !== 'object') return null

    // Normalize the previous two-flag session schema to one panel state.
    return {
      companionOpen: panels.companionOpen === true,
      navigatorOpen: panels.navigatorOpen === true || panels.navigatorCollapsed === false,
    }
  } catch {
    return null
  }
}

export function useReadingLearningMode(workspaceId: string) {
  const [learning, setLearning] = useState(
    () =>
      restoreReadingLearning(
        browserStorage.readRaw('session', READING_LEARNING_KEY),
        workspaceId
      ) !== null
  )
  const [learningSnapshot, setLearningSnapshot] = useState<ReadingPanelState | null>(() =>
    restoreReadingLearning(browserStorage.readRaw('session', READING_LEARNING_KEY), workspaceId)
  )
  const [companionOpen, setCompanionOpen] = useState(() =>
    learning ? false : (learningSnapshot?.companionOpen ?? true)
  )
  const [navigatorOpen, setNavigatorOpen] = useState(() =>
    learning ? true : (learningSnapshot?.navigatorOpen ?? true)
  )
  const mainRef = useRef<HTMLElement | null>(null)

  const openLearning = useCallback(() => {
    const snapshot: ReadingPanelState = {
      companionOpen,
      navigatorOpen,
    }
    setLearningSnapshot(snapshot)
    browserStorage.writeRaw(
      'session',
      READING_LEARNING_KEY,
      JSON.stringify({ panels: snapshot, workspaceId })
    )
    setLearning(true)
    setCompanionOpen(false)
    setNavigatorOpen(true)
  }, [companionOpen, navigatorOpen, workspaceId])

  const closeLearning = useCallback(() => {
    browserStorage.removeRaw('session', READING_LEARNING_KEY)
    setLearning(false)
    setLearningSnapshot(null)
    if (learningSnapshot) {
      setCompanionOpen(learningSnapshot.companionOpen)
      setNavigatorOpen(learningSnapshot.navigatorOpen)
    }
  }, [learningSnapshot])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || !learning || document.fullscreenElement) return
      const hasVisibleDialog = Array.from(
        document.querySelectorAll<HTMLElement>('[role="dialog"],[role="alertdialog"]')
      ).some(
        dialog =>
          dialog.getBoundingClientRect().width > 0 &&
          getComputedStyle(dialog).visibility !== 'hidden'
      )
      if (hasVisibleDialog) return
      closeLearning()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [closeLearning, learning])

  useEffect(() => {
    if (!learning) return
    const root = mainRef.current
    if (!root) return

    const siblings = new Map<HTMLElement, boolean>()
    const isolate = () => {
      let node: HTMLElement = root
      while (node.parentElement && node.parentElement !== document.body) {
        for (const sibling of Array.from(node.parentElement.children)) {
          if (sibling !== node && sibling instanceof HTMLElement) {
            if (!siblings.has(sibling)) siblings.set(sibling, sibling.inert)
            sibling.inert = true
          }
        }
        node = node.parentElement
      }
      return siblings
    }
    isolate()
    const observer = new MutationObserver(isolate)
    observer.observe(document.body, { childList: true, subtree: true })

    return () => {
      observer.disconnect()
      for (const [element, inert] of siblings) element.inert = inert
    }
  }, [learning])

  return {
    closeLearning,
    companionOpen,
    learning,
    mainRef,
    navigatorOpen,
    openLearning,
    setCompanionOpen,
    setNavigatorOpen,
  }
}
