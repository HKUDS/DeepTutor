import React from 'react'
import { QuestionTask } from '../../types/question'
import {
  Terminal,
  FileQuestion,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Search,
  Target,
  Zap,
  Link2,
  Lightbulb,
  BookOpen,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { processLatexContent } from '@/lib/latex'
import { useGlobal } from '@/context/GlobalContext'
import { getTranslation } from '@/lib/i18n'

interface ActiveQuestionDetailProps {
  task: QuestionTask | null
  mode?: 'custom' | 'mimic'
}

export const ActiveQuestionDetail: React.FC<ActiveQuestionDetailProps> = ({
  task,
  mode = 'custom',
}) => {
  const { uiSettings } = useGlobal()
  const t = (key: string) => getTranslation(uiSettings.language, key)
  const isMimicMode = mode === 'mimic'

  const getStatusBadge = (status: QuestionTask['status'], extended?: boolean) => {
    if (status === 'done' && extended) {
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 flex items-center gap-1">
          <Zap className="w-3 h-3" />
          {t('Extension')}
        </span>
      )
    }
    switch (status) {
      case 'done':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300">
            {t('Completed')}
          </span>
        )
      case 'generating':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 flex items-center gap-1">
            <Loader2 className="w-3 h-3 animate-spin" />
            {t('Generating')}
          </span>
        )
      case 'analyzing':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 flex items-center gap-1">
            <Search className="w-3 h-3" />
            {t('Analyzing')}
          </span>
        )
      case 'validating':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3" />
            {t('Validating')}
          </span>
        )
      case 'error':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300">
            {t('Error')}
          </span>
        )
      default:
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400">
            {t('Pending')}
          </span>
        )
    }
  }

  if (!task) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-slate-400 dark:text-slate-500 bg-slate-50/50 dark:bg-slate-800/50 rounded-xl border border-slate-200 dark:border-slate-700">
        <Terminal className="w-12 h-12 mb-3 opacity-20" />
        <p className="text-sm">{t('Select a question task to view details')}</p>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex justify-between items-center">
        <div className="flex items-center gap-2 overflow-hidden">
          <FileQuestion className="w-4 h-4 text-slate-500 dark:text-slate-400 shrink-0" />
          <h3
            className="font-semibold text-slate-800 dark:text-slate-200 text-sm truncate"
            title={task.id}
          >
            {task.id}
          </h3>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {task.round && (
            <span className="text-xs font-mono text-slate-400 dark:text-slate-500">
              {t('Round')} {task.round}
            </span>
          )}
          {getStatusBadge(task.status, task.extended)}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Focus / Origin Question Section */}
        <div
          className={`rounded-lg p-4 border ${isMimicMode ? 'bg-amber-50 dark:bg-amber-900/30 border-amber-100 dark:border-amber-800' : 'bg-indigo-50 dark:bg-indigo-900/30 border-indigo-100 dark:border-indigo-800'}`}
        >
          <div className="flex items-center gap-2 mb-2">
            {isMimicMode ? (
              <>
                <BookOpen className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                <span className="text-xs font-bold uppercase tracking-wider text-amber-700 dark:text-amber-300">
                  {t('Origin Question')}
                </span>
              </>
            ) : (
              <>
                <Target className="w-4 h-4 text-indigo-500 dark:text-indigo-400" />
                <span className="text-xs font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">
                  {t('Focus')}
                </span>
              </>
            )}
          </div>
          {isMimicMode ? (
            <div className="prose prose-sm dark:prose-invert max-w-none text-amber-900 dark:text-amber-200">
              {task.focus ? (
                <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
                  {processLatexContent(task.focus)}
                </ReactMarkdown>
              ) : (
                <span className="text-amber-600 dark:text-amber-400 italic">{t('N/A')}</span>
              )}
            </div>
          ) : (
            <>
              <p className="text-sm text-indigo-800 dark:text-indigo-200">
                {task.focus || t('N/A')}
              </p>
              {task.scenarioHint && (
                <p className="text-xs text-indigo-600 dark:text-indigo-400 mt-2 italic">
                  {t('Hint')}: {task.scenarioHint}
                </p>
              )}
            </>
          )}
        </div>

        {/* Error Section */}
        {task.error && (
          <div className="bg-red-50 dark:bg-red-900/30 rounded-lg p-4 border border-red-100 dark:border-red-800">
            <div className="flex items-center gap-2 mb-2">
              <AlertCircle className="w-4 h-4 text-red-500 dark:text-red-400" />
              <span className="text-xs font-bold uppercase tracking-wider text-red-600 dark:text-red-400">
                {t('Error')}
              </span>
            </div>
            <p className="text-sm text-red-800 dark:text-red-200">{task.error}</p>
          </div>
        )}

        {/* Generated Question */}
        {task.result?.question && (
          <div className="space-y-4">
            {/* Extension Analysis (for extended questions) */}
            {task.extended && task.result.validation && (
              <>
                {task.result.validation.kb_connection && (
                  <div className="bg-amber-50 dark:bg-amber-900/30 rounded-lg p-4 border border-amber-100 dark:border-amber-800">
                    <div className="flex items-center gap-2 mb-2">
                      <Link2 className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                      <span className="text-xs font-bold uppercase tracking-wider text-amber-700 dark:text-amber-300">
                        {t('Knowledge Base Connection')}
                      </span>
                    </div>
                    <p className="text-sm text-amber-800 dark:text-amber-200">
                      {task.result.validation.kb_connection}
                    </p>
                  </div>
                )}
                {task.result.validation.extended_aspect && (
                  <div className="bg-orange-50 dark:bg-orange-900/30 rounded-lg p-4 border border-orange-100 dark:border-orange-800">
                    <div className="flex items-center gap-2 mb-2">
                      <Lightbulb className="w-4 h-4 text-orange-600 dark:text-orange-400" />
                      <span className="text-xs font-bold uppercase tracking-wider text-orange-700 dark:text-orange-300">
                        Extended Aspects
                      </span>
                    </div>
                    <p className="text-sm text-orange-800 dark:text-orange-200">
                      {task.result.validation.extended_aspect}
                    </p>
                  </div>
                )}
              </>
            )}

            <div
              className={`rounded-lg p-4 border ${task.extended ? 'bg-amber-50 dark:bg-amber-900/30 border-amber-100 dark:border-amber-800' : 'bg-emerald-50 dark:bg-emerald-900/30 border-emerald-100 dark:border-emerald-800'}`}
            >
              <div className="flex items-center gap-2 mb-2">
                {task.extended ? (
                  <Zap className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                ) : (
                  <CheckCircle2 className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
                )}
                <span
                  className={`text-xs font-bold uppercase tracking-wider ${task.extended ? 'text-amber-700 dark:text-amber-300' : 'text-emerald-600 dark:text-emerald-400'}`}
                >
                  {task.extended ? 'Extended Question' : 'Generated Question'}
                </span>
              </div>
              <div className="text-sm text-slate-800 dark:text-slate-200 prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
                  {task.result.question.question}
                </ReactMarkdown>
              </div>
            </div>

            {/* Options (for choice questions) */}
            {task.result.question.options && (
              <div className="bg-slate-50 dark:bg-slate-700 rounded-lg p-4 border border-slate-100 dark:border-slate-600">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 block mb-2">
                  Options
                </span>
                <div className="space-y-2">
                  {Object.entries(task.result.question.options).map(([key, value]) => (
                    <div key={key} className="flex items-start gap-2">
                      <span className="font-semibold text-sm text-slate-600 dark:text-slate-400">
                        {key}.
                      </span>
                      <span className="text-sm text-slate-700 dark:text-slate-300">{value}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Answer */}
            <div className="bg-blue-50 dark:bg-blue-900/30 rounded-lg p-4 border border-blue-100 dark:border-blue-800">
              <span className="text-xs font-bold uppercase tracking-wider text-blue-600 dark:text-blue-400 block mb-2">
                正确答案
              </span>
              <div className="text-sm text-slate-800 dark:text-slate-200 prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
                  {task.result.question.correct_answer}
                </ReactMarkdown>
              </div>
            </div>

            {/* Explanation */}
            {task.result.question.explanation && (
              <div className="bg-purple-50 dark:bg-purple-900/30 rounded-lg p-4 border border-purple-100 dark:border-purple-800">
                <span className="text-xs font-bold uppercase tracking-wider text-purple-600 dark:text-purple-400 block mb-2">
                  解析
                </span>
                <div className="text-sm text-slate-700 dark:text-slate-300 prose prose-sm dark:prose-invert max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
                    {task.result.question.explanation}
                  </ReactMarkdown>
                </div>
              </div>
            )}

            {/* Validation Info */}
            {task.result.validation && (
              <div className="bg-slate-50 dark:bg-slate-700 rounded-lg p-4 border border-slate-100 dark:border-slate-600">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 block mb-2">
                  校验摘要
                </span>
                <div className="text-xs text-slate-600 dark:text-slate-400 space-y-1">
                  <p>
                    <strong>状态：</strong>{' '}
                    <span
                      className={
                        task.result.validation.decision === 'approve'
                          ? 'text-emerald-600 dark:text-emerald-400 font-medium'
                          : task.result.validation.decision === 'extended'
                            ? 'text-amber-600 dark:text-amber-400 font-medium'
                            : 'text-amber-600 dark:text-amber-400'
                      }
                    >
                      {task.result.validation.decision === 'extended'
                        ? '拓展（超出知识库范围）'
                        : task.result.validation.decision}
                    </span>
                  </p>
                  <p>
                    <strong>轮次：</strong> {task.result.rounds}
                  </p>
                  {task.result.validation.reasoning && (
                    <p className="mt-2 text-slate-500 dark:text-slate-400 italic">
                      {task.result.validation.reasoning}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Waiting state */}
        {!task.result && !task.error && task.status === 'pending' && (
          <div className="text-center py-10 text-slate-400 dark:text-slate-500 text-xs italic">
            等待开始生成...
          </div>
        )}

        {/* In progress state */}
        {!task.result &&
          !task.error &&
          (task.status === 'generating' ||
            task.status === 'analyzing' ||
            task.status === 'validating') && (
            <div className="flex flex-col items-center justify-center py-10">
              <Loader2 className="w-8 h-8 text-indigo-500 dark:text-indigo-400 animate-spin mb-3" />
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {task.status === 'generating'
                  ? '正在生成题目...'
                  : task.status === 'analyzing'
                    ? '正在分析相关性...'
                    : '正在校验题目...'}
              </p>
              {task.round && (
                <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">轮次 {task.round}</p>
              )}
            </div>
          )}
      </div>
    </div>
  )
}
