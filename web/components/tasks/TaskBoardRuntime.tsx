'use client'

import { useEffect, type ReactNode } from 'react'
import { startTaskBoardSync } from '@/lib/task-board-store'

export default function TaskBoardRuntime({ children }: { children: ReactNode }) {
  useEffect(startTaskBoardSync, [])
  return children
}
