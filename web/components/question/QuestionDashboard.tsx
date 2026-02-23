import React, { useState, useEffect } from 'react'
import { QuestionState, QuestionTokenStats, QuestionTask } from '../../types/question'
import { QuestionTaskGrid } from './QuestionTaskGrid'
import { ActiveQuestionDetail } from './ActiveQuestionDetail'
import {
  GitBranch,
  Zap,
  CheckCircle2,
  Loader2,
  LayoutDashboard,
  Activity,
  Clock,
  Search,
  FileQuestion,
  Target,
  AlertCircle,
  DollarSign,
  Cpu,
  Database,
  RefreshCw,
  Sparkles,
} from 'lucide-react'
import { useGlobal } from '@/context/GlobalContext'
import { getTranslation } from '@/lib/i18n'

type ProcessTab = 'planning' | 'generating'

// Progress info from GlobalContext
interface GlobalContextProgress {
  stage:
    | 'planning'
    | 'researching'
    | 'generating'
    | 'validating'
    | 'complete'
    // Mimic mode stages
    | 'uploading'
    | 'parsing'
    | 'extracting'
    | null
  progress: {
    current?: number
    total?: number
    round?: number
    max_rounds?: number
    status?: string
  }
  subFocuses?: Array<{ id: string; focus: string; scenario_hint?: string }>
  activeQuestions?: string[]
  completedQuestions?: number
  failedQuestions?: number
  extendedQuestions?: number
}

// Logs from GlobalContext
interface LogEntry {
  type: string
  content: string
  timestamp?: number
  level?: string
}

interface QuestionDashboardProps {
  // Support both QuestionState (from reducer) and GlobalContext data
  state?: QuestionState
  // GlobalContext data (alternative to state)
  globalProgress?: GlobalContextProgress
  globalLogs?: LogEntry[]
  globalResults?: any[]
  globalTopic?: string
  globalDifficulty?: string
  globalType?: string
  globalCount?: number
  globalStep?: 'config' | 'generating' | 'result'
  globalMode?: 'custom' | 'mimic' // Mode for different progress display
  // Common props
  selectedTaskId: string | null
  onTaskSelect: (taskId: string) => void
  tokenStats?: QuestionTokenStats
}

export const QuestionDashboard: React.FC<QuestionDashboardProps> = ({
  state,
  globalProgress,
  globalLogs = [],
  globalResults = [],
  globalTopic = '',
  globalDifficulty = '',
  globalType = '',
  globalCount = 0,
  globalStep = 'config',
  globalMode = 'custom',
  selectedTaskId,
  onTaskSelect,
  tokenStats,
}) => {
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

  // Determine if using QuestionState or GlobalContext data
  const useGlobalContext = !state || state.global.stage === 'idle'

  // Extract data from either source
  const stage = useGlobalContext
    ? globalProgress?.stage ||
      (globalStep === 'generating' ? 'generating' : globalStep === 'result' ? 'complete' : 'idle')
    : state!.global.stage

  const isIdle = stage === 'idle' || stage === null
  const isCompleted = stage === 'complete' || globalStep === 'result'
  const isPlanning = stage === 'planning'
  const isResearching = stage === 'researching'
  const isGenerating = stage === 'generating' || stage === 'validating'

  // Mimic mode stages
  const isUploading = stage === 'uploading'
  const isParsing = stage === 'parsing'
  const isExtracting = stage === 'extracting'
  const isMimicMode = globalMode === 'mimic'
  const isMimicPlanning = isUploading || isParsing || isExtracting

  const completedQuestions = useGlobalContext
    ? globalProgress?.completedQuestions || globalResults.length
    : state!.global.completedQuestions

  const totalQuestions = useGlobalContext
    ? globalProgress?.progress?.total || globalCount
    : state!.global.totalQuestions

  const failedQuestions = useGlobalContext
    ? globalProgress?.failedQuestions || 0
    : state!.global.failedQuestions

  const extendedCount = useGlobalContext
    ? globalProgress?.extendedQuestions || globalResults.filter((r: any) => r.extended).length
    : state!.global.extendedQuestions || 0

  const subFocuses = useGlobalContext ? globalProgress?.subFocuses || [] : state!.subFocuses

  const logs = useGlobalContext ? globalLogs : state!.logs
  const results = useGlobalContext ? globalResults : state!.results

  // Build tasks from results when using GlobalContext
  const tasks = useGlobalContext
    ? buildTasksFromResults(globalResults, globalProgress, globalMode)
    : state!.tasks

  const activeTaskIds = useGlobalContext
    ? globalProgress?.activeQuestions || []
    : state!.activeTaskIds

  const [activeProcessTab, setActiveProcessTab] = useState<ProcessTab>('planning')

  const steps: { id: ProcessTab; label: string; icon: React.ElementType }[] = [
    { id: 'planning', label: t('Planning'), icon: GitBranch },
    { id: 'generating', label: t('Generate'), icon: Zap },
  ]

  const stageOrder: Record<string, number> = {
    idle: -1,
    planning: 0,
    researching: 0,
    // Mimic mode stages map to planning
    uploading: 0,
    parsing: 0,
    extracting: 0,
    generating: 1,
    validating: 1,
    complete: 2,
  }

  const currentStageIndex = stageOrder[stage || 'idle'] ?? -1

  const getStageLabel = (s?: string | null) => {
    switch (s) {
      case 'planning':
        return t('Planning')
      case 'researching':
        return t('Retrieving')
      case 'uploading':
        return t('Uploading')
      case 'parsing':
        return t('Parsing')
      case 'extracting':
        return t('Extracting')
      case 'generating':
        return t('Generating')
      case 'validating':
        return t('Validating')
      case 'complete':
        return t('Completed')
      case 'idle':
      default:
        return t('Idle')
    }
  }

  // Check if a tab has content
  const isTabAvailable = (tabId: ProcessTab): boolean => {
    const tabIndex = steps.findIndex(s => s.id === tabId)
    return currentStageIndex >= tabIndex
  }

  // Check if a tab is currently active
  const isTabCurrentlyActive = (tabId: ProcessTab): boolean => {
    if (tabId === 'planning') {
      return isPlanning || isResearching || isMimicPlanning
    }
    return isGenerating
  }

  // Auto-switch to current stage tab when stage changes
  useEffect(() => {
    if (isPlanning || isResearching || isMimicPlanning) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActiveProcessTab('planning')
    } else if (isGenerating) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActiveProcessTab('generating')
    }
  }, [isPlanning, isResearching, isGenerating, isMimicPlanning])

  // Clickable Step Tabs
  const renderStepTabs = () => (
    <div className="flex items-center gap-1 bg-slate-100/80 dark:bg-slate-700/80 backdrop-blur-sm p-1 rounded-xl border border-slate-200/50 dark:border-slate-600/50 shadow-sm">
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
                  ? 'bg-white dark:bg-slate-600 shadow-sm border border-slate-200 dark:border-slate-500 text-indigo-700 dark:text-indigo-300'
                  : available
                    ? 'hover:bg-white/50 dark:hover:bg-slate-600/50 text-slate-600 dark:text-slate-300'
                    : 'text-slate-300 dark:text-slate-500 cursor-not-allowed'
              }
            `}
          >
            {/* Status indicator */}
            {isPassed ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
            ) : isCurrentStage ? (
              <Loader2 className="w-4 h-4 text-indigo-500 dark:text-indigo-400 animate-spin" />
            ) : available ? (
              <step.icon className="w-4 h-4" />
            ) : (
              <Clock className="w-4 h-4 text-slate-300 dark:text-slate-500" />
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

  // Planning Content with Timeline
  const renderPlanningContent = () => {
    const progressStatus = globalProgress?.progress?.status

    // Custom mode steps
    const customModeSteps = [
      {
        id: 'init',
        label: t('Initialization'),
        icon: Sparkles,
        active: isPlanning && !progressStatus,
        done:
          isResearching ||
          progressStatus === 'generating_queries' ||
          progressStatus === 'retrieving' ||
          progressStatus === 'creating_plan' ||
          progressStatus === 'plan_ready' ||
          isGenerating ||
          isCompleted,
      },
      {
        id: 'query',
        label: t('Generate Retrieval Queries'),
        icon: Search,
        active: progressStatus === 'generating_queries' || progressStatus === 'splitting_queries',
        done:
          isResearching ||
          progressStatus === 'retrieving' ||
          progressStatus === 'creating_plan' ||
          progressStatus === 'plan_ready' ||
          isGenerating ||
          isCompleted,
      },
      {
        id: 'research',
        label: t('Retrieve Background Knowledge'),
        icon: Database,
        active: isResearching || progressStatus === 'retrieving',
        done:
          progressStatus === 'creating_plan' ||
          progressStatus === 'plan_ready' ||
          progressStatus === 'completed' ||
          isGenerating ||
          isCompleted,
      },
      {
        id: 'plan',
        label: t('Create Question Plan'),
        icon: Target,
        active: progressStatus === 'creating_plan' || progressStatus === 'planning_focuses',
        done:
          progressStatus === 'plan_ready' || subFocuses.length > 0 || isGenerating || isCompleted,
      },
    ]

    // Mimic mode steps - use stage directly for clearer logic
    const mimicModeSteps = [
      {
        id: 'upload',
        label: t('Upload PDF'),
        icon: Sparkles,
        active: isUploading,
        done: isParsing || isExtracting || isGenerating || isCompleted,
      },
      {
        id: 'parse',
        label: t('Parse PDF (MinerU)'),
        icon: RefreshCw,
        active: isParsing,
        done: isExtracting || isGenerating || isCompleted,
      },
      {
        id: 'extract',
        label: t('Extract Reference Questions'),
        icon: Search,
        active: isExtracting,
        done: isGenerating || isCompleted,
      },
      {
        id: 'ready',
        label: t('Ready to Generate'),
        icon: Target,
        active: false,
        done: isGenerating || isCompleted,
      },
    ]

    const planningSteps = isMimicMode ? mimicModeSteps : customModeSteps

    return (
      <div className="flex-1 flex gap-6 overflow-hidden">
        {/* Left: Timeline */}
        <div className="flex-1 bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm p-6 overflow-y-auto">
          <h3 className="font-bold text-slate-700 dark:text-slate-200 mb-6 flex items-center gap-2">
            <GitBranch className="w-5 h-5 text-indigo-500 dark:text-indigo-400" />
            {t('Planning Progress')}
          </h3>

          {/* Topic Info - Custom Mode */}
          {!isMimicMode && globalTopic && (
            <div className="mb-6 p-4 bg-indigo-50 dark:bg-indigo-900/30 rounded-lg border border-indigo-100 dark:border-indigo-800">
              <div className="flex items-center gap-3 mb-2">
                <div className="text-xs font-bold text-indigo-500 dark:text-indigo-400 uppercase tracking-wider">
                  {t('Topic')}
                </div>
              </div>
              <p className="text-sm text-indigo-900 dark:text-indigo-200 font-medium">
                {globalTopic}
              </p>
              <div className="flex gap-4 mt-2 text-xs text-indigo-600 dark:text-indigo-400">
                <span>
                  {t('Difficulty')}： <strong className="capitalize">{globalDifficulty}</strong>
                </span>
                <span>
                  {t('Type')}：<strong className="capitalize">{globalType}</strong>
                </span>
                <span>
                  {t('Count')}：<strong>{globalCount}</strong>
                </span>
              </div>
            </div>
          )}

          {/* Mode Info - Mimic Mode */}
          {isMimicMode && (
            <div className="mb-6 p-4 bg-amber-50 dark:bg-amber-900/30 rounded-lg border border-amber-100 dark:border-amber-800">
              <div className="flex items-center gap-3 mb-2">
                <div className="text-xs font-bold text-amber-600 dark:text-amber-400 uppercase tracking-wider">
                  {t('Exam Mimic Mode')}
                </div>
              </div>
              <p className="text-sm text-amber-900 dark:text-amber-200 font-medium">
                {t('Generate questions based on reference paper')}
              </p>
              {totalQuestions > 0 && (
                <div className="flex gap-4 mt-2 text-xs text-amber-700 dark:text-amber-400">
                  <span>
                    {t('Reference Questions Count')}：<strong>{totalQuestions}</strong>
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Timeline Steps */}
          <div className="space-y-4">
            {planningSteps.map(step => (
              <div key={step.id} className="flex items-start gap-3">
                <div
                  className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
                    step.done
                      ? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400'
                      : step.active
                        ? 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-400'
                        : 'bg-slate-100 dark:bg-slate-700 text-slate-400 dark:text-slate-500'
                  }`}
                >
                  {step.done ? (
                    <CheckCircle2 className="w-4 h-4" />
                  ) : step.active ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <step.icon className="w-4 h-4" />
                  )}
                </div>
                <div className="flex-1 pt-1">
                  <p
                    className={`text-sm font-medium ${
                      step.done
                        ? 'text-emerald-700 dark:text-emerald-300'
                        : step.active
                          ? 'text-indigo-700 dark:text-indigo-300'
                          : 'text-slate-400 dark:text-slate-500'
                    }`}
                  >
                    {step.label}
                  </p>
                  {step.active && (
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 animate-pulse">
                      {t('Processing...')}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Sub-Focuses Preview */}
          {subFocuses.length > 0 && (
            <div className="mt-6 pt-4 border-t border-slate-100 dark:border-slate-700">
              <p className="text-xs font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-3">
                {t('Question Focuses')}（{subFocuses.length}）
              </p>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {subFocuses.map((focus: any) => (
                  <div
                    key={focus.id}
                    className="px-3 py-2 bg-slate-50 dark:bg-slate-700 text-slate-700 dark:text-slate-300 text-xs rounded-lg border border-slate-100 dark:border-slate-600"
                  >
                    <div className="flex items-center gap-2 font-semibold text-indigo-600 dark:text-indigo-400">
                      <Target className="w-3 h-3" />
                      {focus.id}
                    </div>
                    <p className="mt-1 text-slate-600 dark:text-slate-400">{focus.focus}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right: Live Logs */}
        <div className="w-[350px] bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm flex flex-col">
          <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between">
            <h3 className="font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2">
              <Activity className="w-4 h-4 text-indigo-500 dark:text-indigo-400" />
              {t('Live Logs')}
            </h3>
            <span className="text-xs text-slate-400 dark:text-slate-500">
              {logs.length} {t('records')}
            </span>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {logs.length === 0 ? (
              <div className="text-center text-slate-400 dark:text-slate-500 py-8">
                <Activity className="w-8 h-8 mx-auto mb-2 opacity-30" />
                <p className="text-xs">{t('Waiting for logs...')}</p>
              </div>
            ) : (
              logs.slice(-50).map((log: any, idx: number) => (
                <div
                  key={idx}
                  className={`text-xs px-2 py-1.5 rounded ${
                    log.type === 'error'
                      ? 'bg-red-50 dark:bg-red-900/40 text-red-700 dark:text-red-300'
                      : log.type === 'success'
                        ? 'bg-emerald-50 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300'
                        : 'bg-slate-50 dark:bg-slate-700 text-slate-600 dark:text-slate-400'
                  }`}
                >
                  {log.content}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    )
  }

  // Generating Content with Question Progress
  const renderGeneratingContent = () => {
    const hasContent = Object.keys(tasks).length > 0 || results.length > 0

    if (!hasContent) {
      return (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <Loader2 className="w-12 h-12 mx-auto mb-3 text-indigo-500 dark:text-indigo-400 animate-spin" />
            <p className="text-slate-600 dark:text-slate-300 font-medium">
              {t('Initializing generation...')}
            </p>
            <p className="text-slate-400 dark:text-slate-500 text-sm mt-1">
              {t('Preparing tasks...')}
            </p>
          </div>
        </div>
      )
    }

    return (
      <div className="flex-1 min-h-0 flex gap-6">
        {/* Left: Task Grid */}
        <div className="flex-[3] min-w-0 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2">
              <FileQuestion className="w-4 h-4 text-amber-500 dark:text-amber-400" />
              题目任务
              {isCompleted && (
                <span className="text-xs font-normal text-slate-400 dark:text-slate-500 ml-2">
                  （已完成）
                </span>
              )}
            </h3>
            <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
              {isGenerating && activeTaskIds.length > 0 && (
                <span className="text-indigo-600 dark:text-indigo-400 font-medium">
                  {t('{0} active', activeTaskIds.length)}
                </span>
              )}
              <span>
                {completedQuestions} / {totalQuestions} {t('Completed')}
              </span>
              {extendedCount > 0 && (
                <span className="text-amber-600 dark:text-amber-400">
                  {extendedCount} {t('Extended')}
                </span>
              )}
              {failedQuestions > 0 && (
                <span className="text-red-500 dark:text-red-400">
                  {failedQuestions} {t('Failed')}
                </span>
              )}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto pr-2">
            <QuestionTaskGrid
              tasks={tasks}
              activeTaskIds={isGenerating ? activeTaskIds : []}
              selectedTaskId={selectedTaskId}
              onTaskSelect={onTaskSelect}
              mode={globalMode}
            />
          </div>
        </div>

        {/* Right: Active Details */}
        <div className="flex-[2] min-w-[400px] flex flex-col gap-4">
          <h3 className="font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2">
            <Activity className="w-4 h-4 text-indigo-500 dark:text-indigo-400" />
            {isGenerating ? t('Active Questions') : t('Question Details')}
          </h3>
          <div className="flex-1 min-h-0">
            <ActiveQuestionDetail
              task={selectedTaskId ? tasks[selectedTaskId] : null}
              mode={globalMode}
            />
          </div>
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
              isIdle
                ? 'bg-slate-100 dark:bg-slate-700 text-slate-400 dark:text-slate-500'
                : isCompleted
                  ? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400'
                  : 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-400'
            }`}
          >
            {isCompleted ? (
              <CheckCircle2 className="w-5 h-5" />
            ) : isIdle ? (
              <FileQuestion className="w-5 h-5" />
            ) : (
              <LayoutDashboard className="w-5 h-5" />
            )}
          </div>
          <div>
            <h2 className="text-lg font-bold text-slate-800 dark:text-slate-100">
              {isIdle
                ? t('Ready to Generate')
                : isCompleted
                  ? t('Generation Completed')
                  : t('Question Generation')}
            </h2>
            <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              <span
                className={`uppercase font-bold tracking-wider ${isCompleted ? 'text-emerald-600 dark:text-emerald-400' : ''}`}
              >
                {getStageLabel(stage || 'idle')}
              </span>
              {totalQuestions > 0 && (
                <>
                  <span>•</span>
                  <span>
                    {completedQuestions} / {totalQuestions} {t('Questions')}
                  </span>
                </>
              )}
              {extendedCount > 0 && (
                <>
                  <span>•</span>
                  <span className="text-amber-600 dark:text-amber-400 flex items-center gap-1">
                    <Zap className="w-3 h-3" />
                    {extendedCount} {t('Extended')}
                  </span>
                </>
              )}
              {failedQuestions > 0 && (
                <>
                  <span>•</span>
                  <span className="text-red-500 dark:text-red-400 flex items-center gap-1">
                    <AlertCircle className="w-3 h-3" />
                    {failedQuestions} {t('Failed')}
                  </span>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Performance & Cost Stats */}
        <div className="flex items-center gap-4">
          {tokenStats && tokenStats.calls > 0 && (
            <div className="flex items-center gap-4 px-4 py-2 bg-slate-50 dark:bg-slate-700 rounded-lg border border-slate-200 dark:border-slate-600">
              <div className="flex items-center gap-2">
                <Cpu className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  <span className="font-medium text-slate-700 dark:text-slate-300">
                    {tokenStats.model}
                  </span>
                </span>
              </div>
              <div className="h-4 w-px bg-slate-200 dark:bg-slate-600" />
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {t('Calls')}：{' '}
                <span className="font-medium text-slate-700 dark:text-slate-300">
                  {tokenStats.calls}
                </span>
              </div>
              <div className="h-4 w-px bg-slate-200 dark:bg-slate-600" />
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {t('Tokens')}：{' '}
                <span className="font-medium text-slate-700 dark:text-slate-300">
                  {tokenStats.tokens.toLocaleString()}
                </span>
              </div>
              <div className="h-4 w-px bg-slate-200 dark:bg-slate-600" />
              <div className="flex items-center gap-1">
                <DollarSign className="w-3 h-3 text-amber-500" />
                <span className="text-xs font-semibold text-amber-600 dark:text-amber-400">
                  ${tokenStats.cost.toFixed(4)}
                </span>
              </div>
            </div>
          )}

          {/* Results Summary (when complete) */}
          {isCompleted && results.length > 0 && (
            <div className="flex items-center gap-2 bg-emerald-50 dark:bg-emerald-900/30 px-4 py-2 rounded-lg border border-emerald-100 dark:border-emerald-800">
              <CheckCircle2 className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
              <span className="text-sm font-medium text-emerald-700 dark:text-emerald-300">
                {t('Generated {0} questions', results.length)}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        {/* Idle State */}
        {isIdle ? (
          <div className="flex-1 flex items-center justify-center p-6">
            <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm p-8 flex flex-col items-center justify-center text-center max-w-lg w-full">
              <div className="w-16 h-16 bg-slate-100 dark:bg-slate-700 rounded-full flex items-center justify-center mb-4">
                <FileQuestion className="w-8 h-8 text-slate-400 dark:text-slate-500" />
              </div>
              <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100 mb-2">
                {t('Ready to generate questions')}
              </h3>
              <p className="text-slate-500 dark:text-slate-400 text-sm">
                {t('Configure requirements and click Generate to start.')}
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
              {activeProcessTab === 'generating' && renderGeneratingContent()}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// Helper function to build tasks from results
function buildTasksFromResults(
  results: any[],
  progress?: GlobalContextProgress,
  mode?: 'custom' | 'mimic'
): Record<string, QuestionTask> {
  const tasks: Record<string, QuestionTask> = {}
  const isMimicMode = mode === 'mimic'

  // First, create tasks from subFocuses if available (custom mode)
  if (progress?.subFocuses && !isMimicMode) {
    progress.subFocuses.forEach((focus, idx) => {
      tasks[focus.id] = {
        id: focus.id,
        focus: focus.focus,
        scenarioHint: focus.scenario_hint,
        status: idx < results.length ? 'done' : 'pending',
        result:
          idx < results.length
            ? {
                success: true,
                question_id: focus.id,
                question: results[idx]?.question,
                validation: results[idx]?.validation,
                rounds: results[idx]?.rounds || 1,
                extended: results[idx]?.extended,
              }
            : undefined,
        extended: results[idx]?.extended,
        lastUpdate: Date.now(),
      }
    })
  }

  // If no subFocuses or mimic mode, create tasks from results directly
  if (Object.keys(tasks).length === 0 && results.length > 0) {
    results.forEach((result: any, idx: number) => {
      const id = `q_${idx + 1}`
      // For mimic mode, use reference_question as focus (full original question)
      // For custom mode fallback, use generated question preview
      const focus = isMimicMode
        ? result.reference_question || `Reference Question ${idx + 1}`
        : result.question?.question?.slice(0, 50) + '...' || `Question ${idx + 1}`

      tasks[id] = {
        id,
        focus,
        status: 'done',
        result: {
          success: true,
          question_id: id,
          question: result.question,
          validation: result.validation,
          rounds: result.rounds || 1,
          extended: result.extended,
        },
        extended: result.extended,
        lastUpdate: Date.now(),
      }
    })
  }

  return tasks
}
