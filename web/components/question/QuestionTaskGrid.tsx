import React from 'react'
import { QuestionTask } from '../../types/question'
import {
  CheckCircle2,
  Loader2,
  Clock,
  AlertCircle,
  Activity,
  FileQuestion,
  Search,
  Zap,
  BookOpen,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { processLatexContent } from '@/lib/latex'
import { useGlobal } from '@/context/GlobalContext'
import { getTranslation } from '@/lib/i18n'

interface QuestionTaskGridProps {
  tasks: Record<string, QuestionTask>
  activeTaskIds: string[]
  selectedTaskId: string | null
  onTaskSelect: (taskId: string) => void
  mode?: 'custom' | 'mimic'
}

export const QuestionTaskGrid: React.FC<QuestionTaskGridProps> = ({
  tasks,
  activeTaskIds,
  selectedTaskId,
  onTaskSelect,
  mode = 'custom',
}) => {
  const { uiSettings } = useGlobal()
  const t = (key: string) => getTranslation(uiSettings.language, key)
  const isMimicMode = mode === 'mimic'

  const getStatusLabel = (status: QuestionTask['status'], extended?: boolean) => {
    if (status === 'done' && extended) return t('Extension')
    switch (status) {
      case 'done':
        return t('Completed')
      case 'generating':
        return t('Generating')
      case 'analyzing':
        return t('Analyzing')
      case 'validating':
        return t('Validating')
      case 'error':
        return t('Error')
      default:
        return t('Pending')
    }
  }

  const getStatusIcon = (status: QuestionTask['status'], extended?: boolean) => {
    if (status === 'done' && extended) {
      return <Zap className="w-4 h-4 text-amber-500" />
    }
    switch (status) {
      case 'done':
        return <CheckCircle2 className="w-4 h-4 text-emerald-500" />
      case 'generating':
        return <Loader2 className="w-4 h-4 text-indigo-500 animate-spin" />
      case 'analyzing':
        return <Search className="w-4 h-4 text-purple-500 animate-pulse" />
      case 'validating':
        return <Search className="w-4 h-4 text-amber-500 animate-pulse" />
      case 'error':
        return <AlertCircle className="w-4 h-4 text-red-500" />
      default:
        return <Clock className="w-4 h-4 text-slate-400" />
    }
  }

  const getStatusColor = (status: QuestionTask['status'], extended?: boolean) => {
    if (status === 'done' && extended) {
      return 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300'
    }
    switch (status) {
      case 'done':
        return 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300'
      case 'generating':
        return 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300'
      case 'analyzing':
        return 'bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300'
      case 'validating':
        return 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300'
      case 'error':
        return 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300'
      default:
        return 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400'
    }
  }

  // Sort tasks: Active first, then by status
  const sortedTasks = Object.values(tasks).sort((a, b) => {
    const score = (task: QuestionTask) => {
      if (activeTaskIds.includes(task.id)) return 4
      if (
        task.status === 'generating' ||
        task.status === 'analyzing' ||
        task.status === 'validating'
      )
        return 3
      if (task.status === 'pending') return 2
      return 1
    }
    return score(b) - score(a)
  })

  if (sortedTasks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-8 text-slate-400 dark:text-slate-500 border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-xl">
        <Activity className="w-8 h-8 mb-2 opacity-50" />
        <p className="text-sm">{t('No questions initialized')}</p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      {sortedTasks.map(task => {
        const isActive = activeTaskIds.includes(task.id)
        const isSelected = selectedTaskId === task.id

        return (
          <div
            key={task.id}
            onClick={() => onTaskSelect(task.id)}
            className={`
              relative p-4 rounded-xl border cursor-pointer transition-all duration-200
              hover:shadow-md flex flex-col gap-3
              ${
                isSelected
                  ? 'bg-indigo-50/50 dark:bg-indigo-900/30 border-indigo-500 ring-1 ring-indigo-500'
                  : 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:border-indigo-300 dark:hover:border-indigo-500'
              }
              ${isActive ? 'shadow-sm' : 'opacity-90'}
            `}
          >
            {/* Active Indicator Pulse */}
            {isActive && (
              <div className="absolute top-4 right-4 flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
              </div>
            )}

            <div className="flex items-start gap-3">
              <div
                className={`p-2 rounded-lg shrink-0 ${
                  task.status === 'done' && task.extended
                    ? 'bg-amber-50 dark:bg-amber-900/30'
                    : task.status === 'done'
                      ? 'bg-emerald-50 dark:bg-emerald-900/30'
                      : task.status === 'error'
                        ? 'bg-red-50 dark:bg-red-900/30'
                        : isActive
                          ? 'bg-indigo-50 dark:bg-indigo-900/30'
                          : 'bg-slate-100 dark:bg-slate-700'
                }`}
              >
                {getStatusIcon(task.status, task.extended)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-2">
                  <h4
                    className="text-sm font-semibold text-slate-800 dark:text-slate-200 line-clamp-1 pr-4"
                    title={task.id}
                  >
                    {task.id}
                  </h4>
                </div>
                <div className="flex items-center gap-2 mt-1.5">
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded-full font-medium uppercase tracking-wide ${getStatusColor(task.status, task.extended)}`}
                  >
                    {getStatusLabel(task.status, task.extended)}
                  </span>
                  {task.round && task.maxRounds && (
                    <span className="text-[10px] text-slate-400 dark:text-slate-500 font-medium">
                      {t('Round')} {task.round} / {task.maxRounds}
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Focus / Origin Question */}
            <div
              className={`bg-slate-50 dark:bg-slate-700 rounded-lg p-2.5 border border-slate-100 dark:border-slate-600 ${isMimicMode ? 'min-h-[80px]' : 'min-h-[48px]'}`}
            >
              {isMimicMode ? (
                <div className="text-xs text-slate-600 dark:text-slate-400">
                  <div className="flex items-center gap-1 mb-2">
                    <BookOpen className="w-3 h-3 text-amber-500 dark:text-amber-400" />
                    <span className="font-semibold text-amber-600 dark:text-amber-400">
                      {t('Origin Question:')}
                    </span>
                  </div>
                  <div className="prose prose-xs dark:prose-invert max-w-none leading-relaxed text-slate-700 dark:text-slate-300">
                    {task.focus ? (
                      <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
                        {processLatexContent(task.focus)}
                      </ReactMarkdown>
                    ) : (
                      <span className="text-slate-400 dark:text-slate-500 italic">
                        {t('Waiting to start...')}
                      </span>
                    )}
                  </div>
                </div>
              ) : (
                <p className="text-xs text-slate-600 dark:text-slate-400 line-clamp-2 leading-relaxed">
                  <span className="font-medium text-slate-400 dark:text-slate-500 mr-1">
                    {t('Focus:')}
                  </span>
                  {task.focus || t('Waiting to start...')}
                </p>
              )}
            </div>

            {/* Result preview or error */}
            {task.result?.question && (
              <div
                className={`flex items-center gap-1.5 text-xs ${task.extended ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}`}
              >
                {task.extended ? <Zap className="w-3 h-3" /> : <FileQuestion className="w-3 h-3" />}
                <span className="line-clamp-1">
                  {task.result.question.question?.slice(0, 50)}...
                </span>
              </div>
            )}
            {task.error && (
              <div className="flex items-center gap-1.5 text-xs text-red-600 dark:text-red-400">
                <AlertCircle className="w-3 h-3" />
                <span className="line-clamp-1">{task.error}</span>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
