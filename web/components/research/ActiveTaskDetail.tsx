import React, { useEffect, useRef } from 'react'
import { TaskState, ThoughtEntry } from '../../types/research'
import { Terminal, BrainCircuit, Search, PenTool, AlertTriangle, Database } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

import { useGlobal } from '@/context/GlobalContext'
import { getTranslation } from '@/lib/i18n'

interface ActiveTaskDetailProps {
  task: TaskState | null
}

export const ActiveTaskDetail: React.FC<ActiveTaskDetailProps> = ({ task }) => {
  const { uiSettings } = useGlobal()
  const t = (key: string) => getTranslation(uiSettings.language, key)
  const scrollRef = useRef<HTMLDivElement>(null)

  const getStatusLabel = (status: TaskState['status']) => {
    switch (status) {
      case 'completed':
        return t('Completed')
      case 'running':
        return t('Running')
      case 'failed':
        return t('Failed')
      default:
        return t('Pending')
    }
  }

  const getThoughtIcon = (type: ThoughtEntry['type']) => {
    switch (type) {
      case 'sufficiency':
        return <BrainCircuit className="w-4 h-4 text-violet-500" />
      case 'plan':
        return <Search className="w-4 h-4 text-blue-500" />
      case 'tool_call':
        return <Database className="w-4 h-4 text-amber-500" />
      case 'note':
        return <PenTool className="w-4 h-4 text-emerald-500" />
      case 'error':
        return <AlertTriangle className="w-4 h-4 text-red-500" />
      default:
        return <Terminal className="w-4 h-4 text-slate-400" />
    }
  }

  const formatTimestamp = (ts: number) => {
    return new Date(ts).toLocaleTimeString(undefined, {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  }

  // Auto-scroll to bottom when new thoughts arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [task?.thoughts.length])

  if (!task) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-slate-400 dark:text-slate-500 bg-slate-50/50 dark:bg-slate-800/50 rounded-xl border border-slate-200 dark:border-slate-700">
        <Terminal className="w-12 h-12 mb-3 opacity-20" />
        <p className="text-sm">{t('Select a task to view details')}</p>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex justify-between items-center">
        <div className="flex items-center gap-2 overflow-hidden">
          <Terminal className="w-4 h-4 text-slate-500 dark:text-slate-400 shrink-0" />
          <h3
            className="font-semibold text-slate-800 dark:text-slate-100 text-sm truncate"
            title={task.topic}
          >
            {task.topic}
          </h3>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs font-mono text-slate-400 dark:text-slate-500">{task.id}</span>
          <div
            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
              task.status === 'running'
                ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300'
                : task.status === 'completed'
                  ? 'bg-emerald-100 dark:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300'
                  : task.status === 'failed'
                    ? 'bg-red-100 dark:bg-red-900/50 text-red-700 dark:text-red-300'
                    : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400'
            }`}
          >
            {getStatusLabel(task.status)}
          </div>
        </div>
      </div>

      {/* Content Stream */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4 font-mono text-sm">
        {task.thoughts.length === 0 ? (
          <div className="text-center py-10 text-slate-400 dark:text-slate-500 text-xs italic">
            {t('Waiting for execution logs...')}
          </div>
        ) : (
          task.thoughts.map((thought, idx) => (
            <div key={idx} className="flex gap-3 animate-fade-in group">
              {/* Timeline Line */}
              <div className="flex flex-col items-center shrink-0 w-8">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center border ${
                    thought.type === 'error'
                      ? 'bg-red-50 dark:bg-red-900/40 border-red-200 dark:border-red-800'
                      : thought.type === 'sufficiency'
                        ? 'bg-violet-50 dark:bg-violet-900/40 border-violet-200 dark:border-violet-800'
                        : thought.type === 'tool_call'
                          ? 'bg-amber-50 dark:bg-amber-900/40 border-amber-200 dark:border-amber-800'
                          : 'bg-slate-50 dark:bg-slate-700 border-slate-200 dark:border-slate-600'
                  }`}
                >
                  {getThoughtIcon(thought.type)}
                </div>
                {idx < task.thoughts.length - 1 && (
                  <div className="w-px h-full bg-slate-100 dark:bg-slate-700 my-1 group-hover:bg-slate-200 dark:group-hover:bg-slate-600 transition-colors" />
                )}
              </div>

              {/* Content Bubble */}
              <div className="flex-1 min-w-0 pb-2">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`text-xs font-bold uppercase tracking-wider ${
                      thought.type === 'error'
                        ? 'text-red-600 dark:text-red-400'
                        : thought.type === 'sufficiency'
                          ? 'text-violet-600 dark:text-violet-400'
                          : thought.type === 'tool_call'
                            ? 'text-amber-600 dark:text-amber-400'
                            : 'text-slate-600 dark:text-slate-400'
                    }`}
                  >
                    {t(thought.type)}
                  </span>
                  <span className="text-[10px] text-slate-400 dark:text-slate-500">
                    {formatTimestamp(thought.timestamp)}
                  </span>
                </div>

                <div className="text-slate-700 dark:text-slate-200 leading-relaxed bg-slate-50/50 dark:bg-slate-700/50 rounded-lg p-3 border border-slate-100/50 dark:border-slate-600/50">
                  <ReactMarkdown
                    components={{
                      p: ({ children }) => <p className="mb-1 last:mb-0 break-words">{children}</p>,
                      code: ({ className, children, ...props }) => {
                        return !className?.includes('language-') ? (
                          <code
                            className="bg-slate-200/50 dark:bg-slate-600/50 px-1 py-0.5 rounded text-xs text-slate-800 dark:text-slate-200"
                            {...props}
                          >
                            {children}
                          </code>
                        ) : (
                          <code className={className} {...props}>
                            {children}
                          </code>
                        )
                      },
                    }}
                  >
                    {thought.content}
                  </ReactMarkdown>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
