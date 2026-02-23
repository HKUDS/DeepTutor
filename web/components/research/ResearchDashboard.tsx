/* eslint-disable react-hooks/exhaustive-deps */

import React, { useState, useEffect } from 'react'
import { ResearchState } from '../../types/research'
import { TaskGrid } from './TaskGrid'
import { ActiveTaskDetail } from './ActiveTaskDetail'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeRaw from 'rehype-raw'
import 'katex/dist/katex.min.css'
import { Mermaid } from '../Mermaid'
import {
  GitBranch,
  Zap,
  PenTool,
  CheckCircle2,
  Loader2,
  LayoutDashboard,
  Activity,
  FileText,
  ListTree,
  Sparkles,
  BarChart3,
  FileOutput,
  Search,
  Clock,
  Book,
  Download,
  FileDown,
} from 'lucide-react'
import { useGlobal } from '@/context/GlobalContext'
import { getTranslation } from '@/lib/i18n'

type ProcessTab = 'planning' | 'researching' | 'reporting'

type PptStyleTemplate = {
  id: string
  label: string
  prompt: string
}

const PPT_STYLE_TEMPLATES: PptStyleTemplate[] = [
  {
    id: 'corporate-minimal',
    label: 'Corporate (Minimal)',
    prompt:
      '干净的商务风格幻灯片。使用浅色背景与充足留白。偏好扁平图形、细分隔线与轻微阴影。主题：背景 #FFFFFF，强调色 #2563EB，标题色 #0F172A，正文字色 #334155，字体 Aptos。标题尽量短；要点尽量精炼。',
  },
  {
    id: 'academic-lecture',
    label: 'Academic (Lecture)',
    prompt:
      '学术讲义风格。层级清晰、配色沉稳、排版易读。主题：背景 #FFFFFF，强调色 #4F46E5，标题色 #111827，正文字色 #111827，字体 Aptos。偏好分节页、少装饰，突出定义与关键结论。',
  },
  {
    id: 'dark-tech',
    label: 'Dark (Tech)',
    prompt:
      '现代深色科技风。深色背景、亮色强调、高对比。主题：背景 #0B1220，强调色 #22D3EE，标题色 #E2E8F0，正文字色 #CBD5E1，字体 Aptos。使用简洁线条与轻微渐变；要点短促有力。',
  },
  {
    id: 'data-report',
    label: 'Data (Report)',
    prompt:
      '数据型报告风格。突出数字、强调清晰与结构化要点。主题：背景 #FFFFFF，强调色 #10B981，标题色 #111827，正文字色 #1F2937，字体 Aptos。对指标使用一致的强调方式；分析要点简洁。',
  },
  {
    id: 'storyboard',
    label: 'Narrative (Pitch)',
    prompt:
      '路演/故事板风格。叙事节奏强，章节标题醒目，要点简短。主题：背景 #FFFBEB，强调色 #F97316，标题色 #7C2D12，正文字色 #431407，字体 Aptos。氛围有张力但保持可读性。',
  },
  {
    id: 'chinese-formal',
    label: 'Chinese (Formal)',
    prompt:
      '中文正式/公文风格。版式均衡、配色克制、层级清晰，适合内部汇报。主题：背景 #FFFFFF，强调色 #DC2626，标题色 #111827，正文字色 #1F2937，字体 PingFang SC。避免复杂装饰；要点结构化。',
  },
]

interface ResearchDashboardProps {
  state: ResearchState
  selectedTaskId: string | null
  onTaskSelect: (taskId: string) => void
  onAddToNotebook?: () => void
  onExportMarkdown?: () => void
  onExportPdf?: () => void
  onExportPptx?: () => void
  pptStylePrompt?: string
  onPptStylePromptChange?: (prompt: string) => void
  isExportingPdf?: boolean
  isExportingPptx?: boolean
}

export const ResearchDashboard: React.FC<ResearchDashboardProps> = ({
  state,
  selectedTaskId,
  onTaskSelect,
  onAddToNotebook,
  onExportMarkdown,
  onExportPdf,
  onExportPptx,
  pptStylePrompt = '',
  onPptStylePromptChange,
  isExportingPdf = false,
  isExportingPptx = false,
}) => {
  const { global, tasks, activeTaskIds, planning, reporting } = state
  const { uiSettings } = useGlobal()
  const t = (key: string, ...args: any[]) => {
    let text = getTranslation(uiSettings.language, key)
    if (args.length > 0) {
      args.forEach((arg, index) => {
        text = text.replace(`{${index}}`, String(arg))
      })
    }
    return text
  }

  const [activeView, setActiveView] = useState<'process' | 'report'>('process')
  const [activeProcessTab, setActiveProcessTab] = useState<ProcessTab>('planning')
  const [selectedPptTemplateId, setSelectedPptTemplateId] = useState<string>('custom')

  useEffect(() => {
    if (selectedPptTemplateId === 'custom') return
    const tmpl = PPT_STYLE_TEMPLATES.find(t => t.id === selectedPptTemplateId)
    if (!tmpl) return
    if (pptStylePrompt !== tmpl.prompt) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedPptTemplateId('custom')
    }
  }, [pptStylePrompt, selectedPptTemplateId])

  const steps: { id: ProcessTab; label: string; icon: React.ElementType }[] = [
    { id: 'planning', label: t('Planning'), icon: GitBranch },
    { id: 'researching', label: t('Researching'), icon: Zap },
    { id: 'reporting', label: t('Reporting'), icon: PenTool },
  ]

  const stageOrder: Record<string, number> = {
    idle: -1,
    planning: 0,
    researching: 1,
    reporting: 2,
    completed: 3,
  }

  const currentStageIndex = stageOrder[global.stage] ?? -1
  const isCompleted = global.stage === 'completed'

  // Check if a tab has content (has been reached)
  const isTabAvailable = (tabId: ProcessTab): boolean => {
    const tabIndex = steps.findIndex(s => s.id === tabId)
    return currentStageIndex >= tabIndex
  }

  // Check if a tab is currently active (the system is in this stage)
  const isTabCurrentlyActive = (tabId: ProcessTab): boolean => {
    return global.stage === tabId
  }

  // Auto-switch to current stage tab when stage changes
  useEffect(() => {
    if (global.stage === 'planning') {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActiveProcessTab('planning')
    } else if (global.stage === 'researching') {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActiveProcessTab('researching')
    } else if (global.stage === 'reporting') {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActiveProcessTab('reporting')
    }
    // When completed, stay on current tab (user can browse freely)
  }, [global.stage])

  // Auto-switch to report view when research completes and report is available
  useEffect(() => {
    if (global.stage === 'completed' && reporting.generatedReport && activeView === 'process') {
      const timer = setTimeout(() => {
        setActiveView('report')
      }, 1500)
      return () => clearTimeout(timer)
    }
  }, [global.stage, reporting.generatedReport])

  // Reset to process view when a new research starts
  useEffect(() => {
    if (global.stage === 'planning') {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActiveView('process')
    }
  }, [global.stage])

  // Clickable Step Tabs
  const renderStepTabs = () => (
    <div className="flex items-center gap-1 bg-slate-100/80 dark:bg-slate-800/80 backdrop-blur-sm p-1 rounded-xl border border-slate-200/50 dark:border-slate-700/50 shadow-sm">
      {steps.map((step, idx) => {
        const available = isTabAvailable(step.id)
        const isCurrentStage = isTabCurrentlyActive(step.id)
        const isSelected = activeProcessTab === step.id
        const isPassed = currentStageIndex > idx || isCompleted

        return (
          <button
            key={step.id}
            onClick={() => available && setActiveProcessTab(step.id)}
            disabled={!available}
            className={`
              flex items-center gap-2 px-4 py-2 rounded-lg transition-all relative
              ${
                isSelected
                  ? 'bg-white dark:bg-slate-700 shadow-sm border border-slate-200 dark:border-slate-600 text-indigo-700 dark:text-indigo-300'
                  : available
                    ? 'hover:bg-white/50 dark:hover:bg-slate-700/50 text-slate-600 dark:text-slate-300'
                    : 'text-slate-300 dark:text-slate-600 cursor-not-allowed'
              }
            `}
          >
            {/* Status indicator */}
            {isPassed ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-500" />
            ) : isCurrentStage ? (
              <Loader2 className="w-4 h-4 text-indigo-500 animate-spin" />
            ) : available ? (
              <step.icon className="w-4 h-4" />
            ) : (
              <Clock className="w-4 h-4 text-slate-300" />
            )}
            <span className="text-sm font-medium">{step.label}</span>

            {/* Active indicator dot */}
            {isCurrentStage && !isCompleted && (
              <span className="absolute -top-1 -right-1 flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-indigo-500"></span>
              </span>
            )}
          </button>
        )
      })}
    </div>
  )

  // Planning Content
  const renderPlanningContent = () => {
    const isActive = global.stage === 'planning'

    return (
      <div className="flex-1 flex items-center justify-center">
        <div
          className={`bg-white dark:bg-slate-800 rounded-xl border shadow-sm p-8 flex flex-col items-center justify-center text-center max-w-2xl w-full ${
            isActive
              ? 'border-blue-200 dark:border-blue-800'
              : 'border-slate-200 dark:border-slate-700'
          }`}
        >
          <div
            className={`w-16 h-16 rounded-full flex items-center justify-center mb-4 ${
              isActive ? 'bg-blue-50 dark:bg-blue-900/40' : 'bg-slate-50 dark:bg-slate-700'
            }`}
          >
            <GitBranch
              className={`w-8 h-8 ${isActive ? 'text-blue-500 dark:text-blue-400' : 'text-slate-400 dark:text-slate-500'}`}
            />
          </div>

          {isActive && (
            <Loader2 className="w-6 h-6 text-blue-500 dark:text-blue-400 animate-spin mb-4" />
          )}
          {!isActive && currentStageIndex > 0 && (
            <CheckCircle2 className="w-6 h-6 text-emerald-500 dark:text-emerald-400 mb-4" />
          )}

          <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100 mb-2">
            {isActive ? t('Planning Research Strategy') : t('Research Plan')}
          </h3>

          {isActive && (
            <p className="text-slate-500 dark:text-slate-400 text-sm mb-4">
              {planning.progress || t('Initializing...')}
            </p>
          )}

          {/* Topic Info */}
          {(planning.originalTopic || planning.optimizedTopic) && (
            <div className="w-full mt-4 bg-slate-50 dark:bg-slate-700 rounded-lg p-4 border border-slate-100 dark:border-slate-600 text-left">
              {planning.originalTopic && (
                <div className="mb-3">
                  <p className="text-xs font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-1">
                    {t('Original Topic')}
                  </p>
                  <p className="text-sm text-slate-700 dark:text-slate-200">
                    {planning.originalTopic}
                  </p>
                </div>
              )}
              {planning.optimizedTopic && planning.optimizedTopic !== planning.originalTopic && (
                <div>
                  <p className="text-xs font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-1">
                    {t('Optimized Topic')}
                  </p>
                  <p className="text-sm text-slate-700 dark:text-slate-200">
                    {planning.optimizedTopic}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Sub Topics */}
          {planning.subTopics.length > 0 && (
            <div className="w-full mt-4">
              <p className="text-xs font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-3 text-left">
                {t('Research Sub-topics')}（{planning.subTopics.length}）
              </p>
              <div className="flex flex-wrap gap-2">
                {planning.subTopics.map((topic, i) => (
                  <span
                    key={i}
                    className="px-3 py-1.5 bg-blue-50 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 text-xs rounded-lg border border-blue-100 dark:border-blue-800 font-medium"
                  >
                    {topic.sub_topic}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  // Researching Content
  const renderResearchingContent = () => {
    const isActive = global.stage === 'researching'
    const hasContent = Object.keys(tasks).length > 0

    if (!hasContent) {
      return (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center text-slate-400 dark:text-slate-500">
            <Zap className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p>{t('No research data')}</p>
          </div>
        </div>
      )
    }

    return (
      <div className="flex-1 min-h-0 flex gap-6">
        {/* Left: Task Grid - flex-[3] means 3 parts of available space */}
        <div className="flex-[3] min-w-[200px] flex flex-col gap-4 overflow-hidden">
          <div className="flex items-center justify-between shrink-0">
            <h3 className="font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2">
              <Zap className="w-4 h-4 text-amber-500 dark:text-amber-400" />
              {t('Research Tasks')}
              {!isActive && (
                <span className="text-xs font-normal text-slate-400 dark:text-slate-500 ml-2">
                  {t('(History)')}
                </span>
              )}
            </h3>
            <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
              {isActive && (
                <span className="text-indigo-600 dark:text-indigo-400 font-medium">
                  {t('{0} active', state.activeTaskIds.length)}
                </span>
              )}
              <span>
                {t('Completed {0} / {1} topics', global.completedBlocks, global.totalBlocks)}
              </span>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto pr-2">
            <TaskGrid
              tasks={tasks}
              activeTaskIds={isActive ? activeTaskIds : []}
              selectedTaskId={selectedTaskId}
              onTaskSelect={onTaskSelect}
            />
          </div>
        </div>

        {/* Right: Active Details - flex-[2] means 2 parts of available space */}
        {/* Both sides shrink proportionally (3:2 ratio) when space is limited */}
        <div className="flex-[2] min-w-[280px] flex flex-col gap-4 overflow-hidden">
          <h3 className="font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2 shrink-0">
            <Activity className="w-4 h-4 text-indigo-500 dark:text-indigo-400" />
            {isActive ? t('Live Execution') : t('Execution History')}
          </h3>
          <div className="flex-1 min-h-0 overflow-hidden">
            <ActiveTaskDetail task={selectedTaskId ? tasks[selectedTaskId] : null} />
          </div>
        </div>
      </div>
    )
  }

  // Reporting Content
  const renderReportingContent = () => {
    const isActive = global.stage === 'reporting'

    return (
      <div className="flex-1 flex items-center justify-center">
        <div
          className={`bg-white dark:bg-slate-800 rounded-xl border shadow-sm p-8 flex flex-col items-center justify-center text-center max-w-lg w-full ${
            isActive
              ? 'border-purple-200 dark:border-purple-800'
              : isCompleted
                ? 'border-emerald-200 dark:border-emerald-800'
                : 'border-slate-200 dark:border-slate-700'
          }`}
        >
          <div
            className={`w-16 h-16 rounded-full flex items-center justify-center mb-4 ${
              isActive
                ? 'bg-purple-50 dark:bg-purple-900/40'
                : isCompleted
                  ? 'bg-emerald-50 dark:bg-emerald-900/40'
                  : 'bg-slate-50 dark:bg-slate-700'
            }`}
          >
            {isCompleted ? (
              <Sparkles className="w-8 h-8 text-emerald-500 dark:text-emerald-400" />
            ) : (
              <PenTool
                className={`w-8 h-8 ${isActive ? 'text-purple-500 dark:text-purple-400' : 'text-slate-400 dark:text-slate-500'}`}
              />
            )}
          </div>

          {isActive && (
            <Loader2 className="w-6 h-6 text-purple-500 dark:text-purple-400 animate-spin mb-4" />
          )}
          {isCompleted && (
            <CheckCircle2 className="w-6 h-6 text-emerald-500 dark:text-emerald-400 mb-4" />
          )}

          <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100 mb-2">
            {isCompleted
              ? t('Report Generated!')
              : isActive
                ? t('Generating Report...')
                : t('Report Generation')}
          </h3>

          {/* Current Section Being Written */}
          {isActive && reporting.currentSection && (
            <div className="bg-purple-50 dark:bg-purple-900/30 border border-purple-100 dark:border-purple-800 rounded-lg px-4 py-2 mb-4 w-full">
              <p className="text-xs text-purple-600 dark:text-purple-400 font-medium uppercase tracking-wider mb-1">
                {t('Writing')}
              </p>
              <p className="text-purple-800 dark:text-purple-200 font-semibold">
                {reporting.currentSection}
              </p>
              {reporting.totalSections && reporting.sectionIndex !== undefined && (
                <p className="text-xs text-purple-500 dark:text-purple-400 mt-1">
                  {t('Section {0} / {1}', reporting.sectionIndex + 1, reporting.totalSections)}
                </p>
              )}
            </div>
          )}

          {/* Progress Bar */}
          {isActive && reporting.totalSections && reporting.sectionIndex !== undefined && (
            <div className="w-full mb-4">
              <div className="h-2 bg-purple-100 dark:bg-purple-900/40 rounded-full overflow-hidden">
                <div
                  className="h-full bg-purple-500 rounded-full transition-all duration-500"
                  style={{
                    width: `${((reporting.sectionIndex + 1) / reporting.totalSections) * 100}%`,
                  }}
                />
              </div>
              <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
                {t(
                  '{0}% Completed',
                  Math.round(((reporting.sectionIndex + 1) / reporting.totalSections) * 100)
                )}
              </p>
            </div>
          )}

          {isActive && (
            <p className="text-slate-500 dark:text-slate-400 text-sm mb-4">
              {reporting.progress || t('Synthesizing research results...')}
            </p>
          )}

          {/* Stats */}
          <div className="flex items-center gap-6 text-sm text-slate-600 dark:text-slate-300 mt-2">
            {global.totalBlocks > 0 && (
              <div className="flex items-center gap-1.5">
                <ListTree
                  className={`w-4 h-4 ${isCompleted ? 'text-emerald-500 dark:text-emerald-400' : 'text-slate-400 dark:text-slate-500'}`}
                />
                <span>{t('{0} topics', global.totalBlocks)}</span>
              </div>
            )}
            {reporting.wordCount && (
              <div className="flex items-center gap-1.5">
                <FileText
                  className={`w-4 h-4 ${isCompleted ? 'text-emerald-500 dark:text-emerald-400' : 'text-slate-400 dark:text-slate-500'}`}
                />
                <span>
                  {reporting.wordCount.toLocaleString()} {t('chars')}
                </span>
              </div>
            )}
            {reporting.outline && reporting.outline.sections.length > 0 && (
              <div className="flex items-center gap-1.5">
                <FileText className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                <span>
                  {reporting.outline.sections.length}{' '}
                  {t('Section {0} / {1}', '', '')
                    .replace('/', '')
                    .replace('0', '')
                    .replace('1', '')
                    .trim() || 'sections'}
                </span>
              </div>
            )}
          </div>

          {/* Outline Preview */}
          {reporting.outline && reporting.outline.sections.length > 0 && (
            <div className="mt-6 w-full text-left bg-slate-50 dark:bg-slate-700 rounded-lg p-4 border border-slate-100 dark:border-slate-600 max-h-[200px] overflow-y-auto">
              <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-3">
                {t('Report Outline')}
              </p>
              <ul className="space-y-2">
                {reporting.outline.sections.map((section, i) => (
                  <li
                    key={i}
                    className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300"
                  >
                    <span
                      className={`w-5 h-5 rounded text-xs flex items-center justify-center font-medium shrink-0 ${
                        isActive &&
                        reporting.sectionIndex !== undefined &&
                        i + 1 === reporting.sectionIndex
                          ? 'bg-purple-500 text-white animate-pulse'
                          : isCompleted ||
                              (reporting.sectionIndex !== undefined &&
                                i + 1 < reporting.sectionIndex)
                            ? 'bg-emerald-100 dark:bg-emerald-900/50 text-emerald-600 dark:text-emerald-400'
                            : 'bg-purple-100 dark:bg-purple-900/50 text-purple-600 dark:text-purple-400'
                      }`}
                    >
                      {isCompleted ||
                      (reporting.sectionIndex !== undefined && i + 1 < reporting.sectionIndex)
                        ? '✓'
                        : i + 1}
                    </span>
                    <span
                      className={`line-clamp-1 ${
                        isActive &&
                        reporting.sectionIndex !== undefined &&
                        i + 1 === reporting.sectionIndex
                          ? 'text-purple-700 dark:text-purple-300 font-medium'
                          : ''
                      }`}
                    >
                      {section.title.replace(/^##\s*\d*\.?\s*/, '')}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* View Report Button (when completed) */}
          {isCompleted && reporting.generatedReport && (
            <button
              onClick={() => setActiveView('report')}
              className="mt-6 flex items-center justify-center gap-2 w-full py-3 px-4 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-medium transition-colors shadow-sm"
            >
              <FileText className="w-4 h-4" />
              {t('View Full Report')}
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-slate-50/50 dark:bg-slate-900/50">
      {/* Top Bar: Progress & Global Status */}
      <div className="bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 px-6 py-4 flex items-center justify-between shadow-sm shrink-0 z-20 relative">
        <div className="flex items-center gap-4">
          <div
            className={`p-2 rounded-lg ${
              global.stage === 'idle'
                ? 'bg-slate-100 dark:bg-slate-700 text-slate-400 dark:text-slate-500'
                : global.stage === 'completed'
                  ? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400'
                  : 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-400'
            }`}
          >
            {isCompleted ? (
              <CheckCircle2 className="w-5 h-5" />
            ) : (
              <LayoutDashboard className="w-5 h-5" />
            )}
          </div>
          <div>
            <h2 className="text-lg font-bold text-slate-800 dark:text-slate-100">
              {global.stage === 'idle'
                ? t('Ready to Start Research')
                : global.stage === 'completed'
                  ? t('Research Completed')
                  : planning.optimizedTopic || planning.originalTopic || t('Research Dashboard')}
            </h2>
            <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              <span
                className={`uppercase font-bold tracking-wider ${isCompleted ? 'text-emerald-600 dark:text-emerald-400' : ''}`}
              >
                {global.stage === 'idle'
                  ? t('Idle')
                  : global.stage === 'planning'
                    ? t('Planning')
                    : global.stage === 'researching'
                      ? t('Researching')
                      : global.stage === 'reporting'
                        ? t('Reporting')
                        : global.stage === 'completed'
                          ? t('Completed')
                          : global.stage}
              </span>
              {global.totalBlocks > 0 && (
                <>
                  <span>•</span>
                  <span>
                    {t('Completed {0} / {1} topics', global.completedBlocks, global.totalBlocks)}
                  </span>
                </>
              )}
              {state.executionMode === 'parallel' && (
                <>
                  <span>•</span>
                  <span className="text-violet-600 dark:text-violet-400 font-medium">
                    {t('Parallel Mode')}
                  </span>
                </>
              )}
            </div>
          </div>
        </div>

        {/* View Switcher */}
        <div className="flex bg-slate-100 dark:bg-slate-700 p-1 rounded-lg border border-slate-200 dark:border-slate-600">
          <button
            onClick={() => setActiveView('process')}
            className={`flex items-center gap-2 px-4 py-1.5 rounded-md text-sm font-medium transition-all ${
              activeView === 'process'
                ? 'bg-white dark:bg-slate-600 text-indigo-600 dark:text-indigo-300 shadow-sm border border-slate-100 dark:border-slate-500'
                : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
            }`}
          >
            <BarChart3 className="w-4 h-4" />
            {t('Process')}
          </button>
          <button
            onClick={() => setActiveView('report')}
            disabled={!reporting.generatedReport && global.stage !== 'completed'}
            className={`flex items-center gap-2 px-4 py-1.5 rounded-md text-sm font-medium transition-all ${
              activeView === 'report'
                ? 'bg-white dark:bg-slate-600 text-indigo-600 dark:text-indigo-300 shadow-sm border border-slate-100 dark:border-slate-500'
                : !reporting.generatedReport && global.stage !== 'completed'
                  ? 'text-slate-300 dark:text-slate-600 cursor-not-allowed'
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
            }`}
          >
            <FileOutput className="w-4 h-4" />
            {t('Report')}
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      {activeView === 'process' ? (
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          {/* Idle State */}
          {global.stage === 'idle' ? (
            <div className="flex-1 flex items-center justify-center p-6">
              <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm p-8 flex flex-col items-center justify-center text-center max-w-lg w-full">
                <div className="w-16 h-16 bg-slate-100 dark:bg-slate-700 rounded-full flex items-center justify-center mb-4">
                  <Search className="w-8 h-8 text-slate-400 dark:text-slate-500" />
                </div>
                <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100 mb-2">
                  {t('Ready to Start Research')}
                </h3>
                <p className="text-slate-500 dark:text-slate-400 text-sm">
                  {t('Enter a topic in the sidebar to start deep research.')}
                </p>
              </div>
            </div>
          ) : (
            <>
              {/* Step Tabs */}
              <div className="px-6 pt-4 pb-2 flex justify-center shrink-0">{renderStepTabs()}</div>

              {/* Tab Content */}
              <div className="flex-1 overflow-hidden p-6 flex flex-col">
                {activeProcessTab === 'planning' && renderPlanningContent()}
                {activeProcessTab === 'researching' && renderResearchingContent()}
                {activeProcessTab === 'reporting' && renderReportingContent()}
              </div>
            </>
          )}
        </div>
      ) : (
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          {/* Report Toolbar */}
          <div className="px-6 py-3 border-b border-slate-100 dark:border-slate-700 flex justify-end items-center bg-white dark:bg-slate-800 shrink-0">
            <div className="flex gap-2">
              {onAddToNotebook && (
                <button
                  onClick={onAddToNotebook}
                  className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg hover:bg-indigo-50 dark:hover:bg-indigo-900/30 transition-all"
                >
                  <Book className="w-4 h-4" /> {t('Add to Notebook')}
                </button>
              )}
              {onExportMarkdown && (
                <button
                  onClick={onExportMarkdown}
                  className="text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-all"
                >
                  <Download className="w-4 h-4" /> {t('Export Markdown')}
                </button>
              )}
              {onExportPdf && (
                <button
                  onClick={onExportPdf}
                  disabled={isExportingPdf}
                  className="text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-all disabled:opacity-50"
                >
                  {isExportingPdf ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <FileDown className="w-4 h-4" />
                  )}{' '}
                  {t('Export PDF')}
                </button>
              )}
              {onExportPptx && (
                <div className="flex items-center gap-2">
                  {onPptStylePromptChange && (
                    <select
                      value={selectedPptTemplateId}
                      onChange={e => {
                        const nextId = e.target.value
                        setSelectedPptTemplateId(nextId)
                        if (nextId === 'custom') return
                        const tmpl = PPT_STYLE_TEMPLATES.find(t => t.id === nextId)
                        if (!tmpl) return
                        onPptStylePromptChange(tmpl.prompt)
                      }}
                      className="text-sm px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200"
                    >
                      <option value="custom">{t('Custom')}</option>
                      {PPT_STYLE_TEMPLATES.map(tmpl => (
                        <option key={tmpl.id} value={tmpl.id}>
                          {t(tmpl.label)}
                        </option>
                      ))}
                    </select>
                  )}
                  {onPptStylePromptChange && (
                    <input
                      value={pptStylePrompt}
                      onChange={e => onPptStylePromptChange(e.target.value)}
                      placeholder={t('PPT Style Prompt (Optional)')}
                      className="text-sm px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 w-72"
                    />
                  )}
                  <button
                    onClick={onExportPptx}
                    disabled={isExportingPptx}
                    className="text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-all disabled:opacity-50"
                  >
                    {isExportingPptx ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <FileDown className="w-4 h-4" />
                    )}{' '}
                    {t('Export PPTX')}
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Report Content */}
          <div
            className="flex-1 overflow-y-auto bg-slate-50/30 dark:bg-slate-900/30 p-8"
            id="report-scroll-container"
          >
            <div className="max-w-4xl mx-auto bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 p-12 min-h-[500px]">
              {reporting.generatedReport ? (
                <article className="prose prose-slate dark:prose-invert max-w-none prose-headings:text-slate-800 dark:prose-headings:text-slate-100 prose-p:text-slate-600 dark:prose-p:text-slate-300 prose-a:text-indigo-600 dark:prose-a:text-indigo-400 prose-img:rounded-xl prose-table:border-collapse prose-th:border prose-th:border-slate-300 dark:prose-th:border-slate-600 prose-th:bg-slate-50 dark:prose-th:bg-slate-700 prose-th:p-2 prose-td:border prose-td:border-slate-200 dark:prose-td:border-slate-600 prose-td:p-2">
                  {/* Add scroll-margin-top style for anchor targets */}
                  <style>{`
                    [id^="ref-"] { scroll-margin-top: 20px; }
                  `}</style>
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm, remarkMath]}
                    rehypePlugins={[rehypeKatex, rehypeRaw]}
                    components={{
                      h1: ({ ...props }) => (
                        <h1
                          className="text-3xl font-bold mb-6 pb-2 border-b border-slate-200 dark:border-slate-700"
                          {...props}
                        />
                      ),
                      h2: ({ ...props }) => (
                        <h2
                          className="text-2xl font-bold mt-8 mb-4 text-indigo-900 dark:text-indigo-300"
                          {...props}
                        />
                      ),
                      h3: ({ ...props }) => (
                        <h3
                          className="text-xl font-semibold mt-6 mb-3 text-slate-800 dark:text-slate-200"
                          {...props}
                        />
                      ),
                      p: ({ ...props }) => (
                        <p
                          className="leading-relaxed mb-4 text-slate-600 dark:text-slate-300"
                          {...props}
                        />
                      ),
                      li: ({ ...props }) => <li className="mb-2" {...props} />,
                      table: ({ ...props }) => (
                        <div className="overflow-x-auto my-6">
                          <table
                            className="min-w-full border-collapse border border-slate-300 dark:border-slate-600 text-sm"
                            {...props}
                          />
                        </div>
                      ),
                      thead: ({ ...props }) => (
                        <thead className="bg-slate-50 dark:bg-slate-700" {...props} />
                      ),
                      th: ({ ...props }) => (
                        <th
                          className="border border-slate-300 dark:border-slate-600 px-4 py-2 text-left font-semibold text-slate-700 dark:text-slate-200"
                          {...props}
                        />
                      ),
                      td: ({ ...props }) => (
                        <td
                          className="border border-slate-200 dark:border-slate-600 px-4 py-2 text-slate-600 dark:text-slate-300"
                          {...props}
                        />
                      ),
                      blockquote: ({ ...props }) => (
                        <blockquote
                          className="border-l-4 border-indigo-300 dark:border-indigo-600 pl-4 py-2 my-4 bg-indigo-50/50 dark:bg-indigo-900/30 text-slate-600 dark:text-slate-300 italic"
                          {...props}
                        />
                      ),
                      a: ({ href, ...props }) => {
                        // Handle internal anchor links for smooth scrolling within the container
                        const handleClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
                          if (href?.startsWith('#')) {
                            e.preventDefault()
                            const targetId = href.slice(1)
                            const targetElement = document.getElementById(targetId)
                            const scrollContainer =
                              document.getElementById('report-scroll-container')
                            if (targetElement && scrollContainer) {
                              // Calculate scroll position within the container
                              const containerRect = scrollContainer.getBoundingClientRect()
                              const targetRect = targetElement.getBoundingClientRect()
                              const offset =
                                targetRect.top - containerRect.top + scrollContainer.scrollTop - 20
                              scrollContainer.scrollTo({
                                top: offset,
                                behavior: 'smooth',
                              })
                            }
                          }
                        }
                        return (
                          <a
                            href={href}
                            onClick={handleClick}
                            className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 underline decoration-indigo-300 dark:decoration-indigo-600 hover:decoration-indigo-500 dark:hover:decoration-indigo-400"
                            {...props}
                          />
                        )
                      },
                      code: ({ className, children, ...props }) => {
                        const match = /language-(\w+)/.exec(className || '')
                        const language = match ? match[1] : ''
                        const isInline = !match

                        // Handle Mermaid diagrams
                        if (language === 'mermaid') {
                          const chartCode = String(children).replace(/\n$/, '')
                          return <Mermaid chart={chartCode} />
                        }

                        return isInline ? (
                          <code
                            className="bg-slate-100 dark:bg-slate-700 text-slate-800 dark:text-slate-200 px-1.5 py-0.5 rounded text-sm font-mono"
                            {...props}
                          >
                            {children}
                          </code>
                        ) : (
                          <code
                            className={`${className} block bg-slate-900 text-slate-100 p-4 rounded-lg overflow-x-auto text-sm`}
                            {...props}
                          >
                            {children}
                          </code>
                        )
                      },
                      pre: ({ children, ...props }) => {
                        // Check if this pre contains a mermaid code block
                        const child = React.Children.toArray(children)[0] as React.ReactElement<{
                          className?: string
                        }>
                        if (child?.props?.className?.includes('language-mermaid')) {
                          // Mermaid is rendered by the code component, so just return children without pre wrapper
                          return <>{children}</>
                        }
                        return (
                          <pre className="bg-slate-900 rounded-lg overflow-hidden my-4" {...props}>
                            {children}
                          </pre>
                        )
                      },
                    }}
                  >
                    {reporting.generatedReport}
                  </ReactMarkdown>
                </article>
              ) : (
                <div className="flex flex-col items-center justify-center h-64 text-slate-400 dark:text-slate-500">
                  <Loader2 className="w-8 h-8 mb-4 animate-spin opacity-50" />
                  <p>{t('Generating report preview...')}</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
