'use client'

import { useSyncExternalStore } from 'react'
import {
  getTaskBoard,
  normalizeTaskBoard,
  subscribeTaskBoardChanges,
  taskBoardUrl,
  type TaskBoard,
} from './task-board-api'

interface State {
  board: TaskBoard | null
  error: boolean
}
const empty: State = { board: null, error: false }
let state = empty
const listeners = new Set<() => void>()
let generation = 0
let refreshing: Promise<void> | undefined
let owners = 0
let stop: (() => void) | undefined

function accept(board: TaskBoard) {
  // A delayed GET or mutation must not roll back a newer streamed snapshot.
  if (state.board && board.revision < state.board.revision) return
  state = { board: normalizeTaskBoard(board), error: false }
  listeners.forEach(listener => listener())
}
export async function refreshTaskBoard() {
  if (refreshing) return refreshing
  const currentGeneration = generation
  refreshing = (async () => {
    try {
      const board = await getTaskBoard()
      if (generation === currentGeneration) accept(board)
    } catch {
      if (generation === currentGeneration) {
        state = { ...state, error: true }
        listeners.forEach(listener => listener())
      }
    } finally {
      if (generation === currentGeneration) refreshing = undefined
    }
  })()
  return refreshing
}

/** One account-level connection, owned by the workspace shell, outside its scope reset. */
export function startTaskBoardSync() {
  if (++owners === 1) {
    const unsubscribe = subscribeTaskBoardChanges(accept)
    void refreshTaskBoard()
    const source =
      typeof EventSource !== 'undefined'
        ? new EventSource(taskBoardUrl('/events'), { withCredentials: true })
        : null
    let fallback: ReturnType<typeof setInterval> | undefined
    const startFallback = () => {
      fallback ??= setInterval(() => {
        if (!document.hidden) void refreshTaskBoard()
      }, 3000)
    }
    if (source) {
      source.onmessage = event => {
        try {
          accept(JSON.parse(event.data))
        } catch {
          void refreshTaskBoard()
        }
      }
      source.onerror = startFallback
      source.onopen = () => {
        clearInterval(fallback)
        fallback = undefined
      }
    } else startFallback()
    const focus = () => {
      if (!document.hidden) void refreshTaskBoard()
    }
    window.addEventListener('focus', focus)
    document.addEventListener('visibilitychange', focus)
    stop = () => {
      unsubscribe()
      source?.close()
      clearInterval(fallback)
      window.removeEventListener('focus', focus)
      document.removeEventListener('visibilitychange', focus)
    }
  }
  return () => {
    if (--owners === 0) {
      stop?.()
      stop = undefined
      state = empty
      generation++
      refreshing = undefined
    }
  }
}
function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
export function useTaskBoard() {
  return useSyncExternalStore(
    subscribe,
    () => state,
    () => empty
  )
}
