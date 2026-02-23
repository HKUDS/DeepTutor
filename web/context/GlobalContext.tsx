'use client'

import React, { createContext, useContext, useRef, useState, useEffect } from 'react'
import { wsUrl, apiUrl } from '@/lib/api'
import { initializeTheme, setTheme, getStoredTheme } from '@/lib/theme'

// --- Types ---
interface LogEntry {
  type: string
  content: string
  timestamp?: number
  level?: string
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  outputDir?: string
}

// Agent Status
interface AgentStatus {
  [key: string]: 'pending' | 'running' | 'done' | 'error'
}

// Token Stats
interface TokenStats {
  model: string
  calls: number
  tokens: number
  input_tokens: number
  output_tokens: number
  cost: number
}

// Progress Info
interface ProgressInfo {
  stage: 'investigate' | 'solve' | 'response' | null
  progress: {
    round?: number
    queries?: string[]
    step_index?: number
    step_id?: string
    step_target?: string
  }
}

// Solver State
interface SolverState {
  isSolving: boolean
  logs: LogEntry[]
  messages: ChatMessage[]
  question: string
  selectedKb: string
  agentStatus: AgentStatus
  tokenStats: TokenStats
  progress: ProgressInfo
}

// Question Progress Info
interface QuestionProgressInfo {
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
  // Parallel generation info
  subFocuses?: Array<{ id: string; focus: string; scenario_hint?: string }>
  activeQuestions?: string[]
  completedQuestions?: number
  failedQuestions?: number
  extendedQuestions?: number // Count of extended questions
}

// Question Agent Status
interface QuestionAgentStatus {
  [key: string]: 'pending' | 'running' | 'done' | 'error'
}

// Question Token Stats
interface QuestionTokenStats {
  model: string
  calls: number
  tokens: number
  input_tokens: number
  output_tokens: number
  cost: number
}

// Question State
interface QuestionState {
  step: 'config' | 'generating' | 'result'
  mode: 'knowledge' | 'mimic' // Two modes: KB-based generation vs upload exam mimic
  logs: LogEntry[]
  results: any[] // Array of QuestionResult
  topic: string
  difficulty: string
  type: string
  count: number
  selectedKb: string
  progress: QuestionProgressInfo
  agentStatus: QuestionAgentStatus
  tokenStats: QuestionTokenStats
  // Upload exam mode related
  uploadedFile: File | null
  paperPath: string
}

// Active Task Info (for parallel mode)
interface ActiveTaskInfo {
  block_id: string
  sub_topic: string
  status: string
  iteration: number
  max_iterations?: number
  current_tool?: string
  current_query?: string
  tools_used?: string[]
}

// Query Info (for tracking all queries)
interface QueryInfo {
  query: string
  tool_type: string
  rationale?: string
  iteration: number
}

// Research Progress
interface ResearchProgress {
  stage: 'planning' | 'researching' | 'reporting' | null
  status: string
  // Execution mode
  executionMode?: 'series' | 'parallel'
  // Planning details
  totalBlocks?: number
  // Researching details
  currentBlock?: number
  currentSubTopic?: string
  currentBlockId?: string
  iterations?: number
  maxIterations?: number
  toolsUsed?: string[]
  // Current action details (for real-time display)
  currentTool?: string
  currentQuery?: string
  currentRationale?: string
  queriesUsed?: QueryInfo[]
  // Parallel mode specific
  activeTasks?: ActiveTaskInfo[]
  activeCount?: number
  completedCount?: number
  // Reporting details
  keptBlocks?: number
  sections?: number
  wordCount?: number
  citations?: number
}

// Research State
interface ResearchState {
  status: 'idle' | 'running' | 'completed'
  logs: LogEntry[]
  report: string | null
  topic: string
  selectedKb: string
  progress: ResearchProgress
}

// IdeaGen Types
interface ResearchIdea {
  id: string
  knowledge_point: string
  description: string
  research_ideas: string[]
  statement: string
  expanded: boolean
  selected: boolean
}

interface IdeaGenState {
  isGenerating: boolean
  generationStatus: string
  generatedIdeas: ResearchIdea[]
  progress: { current: number; total: number } | null
}

interface GlobalContextType {
  // Solver
  solverState: SolverState
  setSolverState: React.Dispatch<React.SetStateAction<SolverState>>
  startSolver: (question: string, kb: string) => void
  stopSolver: () => void

  // Question
  questionState: QuestionState
  setQuestionState: React.Dispatch<React.SetStateAction<QuestionState>>
  startQuestionGen: (topic: string, diff: string, type: string, count: number, kb: string) => void
  startMimicQuestionGen: (
    file: File | null,
    paperPath: string,
    kb: string,
    maxQuestions?: number
  ) => void
  resetQuestionGen: () => void

  // Research
  researchState: ResearchState
  setResearchState: React.Dispatch<React.SetStateAction<ResearchState>>
  startResearch: (
    topic: string,
    kb: string,
    planMode?: string,
    enabledTools?: string[],
    skipRephrase?: boolean
  ) => void

  // IdeaGen
  ideaGenState: IdeaGenState
  setIdeaGenState: React.Dispatch<React.SetStateAction<IdeaGenState>>

  // Chat (used by history page to navigate to a session)
  loadChatSession: (sessionId: string) => Promise<void>

  // UI Settings
  uiSettings: { theme: 'light' | 'dark'; language: 'en' | 'zh' }
  refreshSettings: () => Promise<void>

  // Sidebar
  sidebarWidth: number
  setSidebarWidth: (width: number) => void
  sidebarCollapsed: boolean
  setSidebarCollapsed: (collapsed: boolean) => void
  toggleSidebar: () => void
}

const GlobalContext = createContext<GlobalContextType | undefined>(undefined)

export function GlobalProvider({ children }: { children: React.ReactNode }) {
  // --- UI Settings Logic ---
  const [uiSettings, setUiSettings] = useState<{
    theme: 'light' | 'dark'
    language: 'en' | 'zh'
  }>({ theme: 'light', language: 'zh' })

  const [isInitialized, setIsInitialized] = useState(false)

  const refreshSettings = async () => {
    try {
      const res = await fetch(apiUrl('/api/v1/settings'))
      if (res.ok) {
        const data = await res.json()
        if (data.ui) {
          // localStorage takes priority over backend
          const storedTheme = getStoredTheme()
          const themeToUse = storedTheme || data.ui.theme

          setUiSettings({
            theme: themeToUse,
            language: 'zh',
          })
          // Apply and persist theme
          setTheme(themeToUse)
        }
      }
    } catch {
      // Fall back to localStorage theme on error
      const stored = getStoredTheme()
      if (stored) {
        setUiSettings(prev => ({ ...prev, theme: stored }))
      }
    }
  }

  useEffect(() => {
    // Initialize theme immediately on first render
    if (!isInitialized) {
      const initialTheme = initializeTheme()
      setUiSettings(prev => ({ ...prev, theme: initialTheme }))
      setIsInitialized(true)

      // Then fetch from backend and sync
      refreshSettings()
    }
  }, [isInitialized])

  // --- Sidebar State ---
  const SIDEBAR_MIN_WIDTH = 64
  const SIDEBAR_MAX_WIDTH = 320
  const SIDEBAR_DEFAULT_WIDTH = 256
  const [sidebarWidth, setSidebarWidthState] = useState<number>(SIDEBAR_DEFAULT_WIDTH)
  const [sidebarCollapsed, setSidebarCollapsedState] = useState<boolean>(false)

  // Initialize sidebar state from localStorage
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const storedWidth = localStorage.getItem('sidebarWidth')
      const storedCollapsed = localStorage.getItem('sidebarCollapsed')

      if (storedWidth) {
        const width = parseInt(storedWidth, 10)
        if (!isNaN(width) && width >= SIDEBAR_MIN_WIDTH && width <= SIDEBAR_MAX_WIDTH) {
          setSidebarWidthState(width)
        }
      }

      if (storedCollapsed) {
        setSidebarCollapsedState(storedCollapsed === 'true')
      }
    }
  }, [])

  const setSidebarWidth = (width: number) => {
    const clampedWidth = Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, width))
    setSidebarWidthState(clampedWidth)
    if (typeof window !== 'undefined') {
      localStorage.setItem('sidebarWidth', clampedWidth.toString())
    }
  }

  const setSidebarCollapsed = (collapsed: boolean) => {
    setSidebarCollapsedState(collapsed)
    if (typeof window !== 'undefined') {
      localStorage.setItem('sidebarCollapsed', collapsed.toString())
    }
  }

  const toggleSidebar = () => {
    setSidebarCollapsed(!sidebarCollapsed)
  }

  // --- Solver Logic ---
  const [solverState, setSolverState] = useState<SolverState>({
    isSolving: false,
    logs: [],
    messages: [],
    question: '',
    selectedKb: '',
    agentStatus: {
      InvestigateAgent: 'pending',
      NoteAgent: 'pending',
      ManagerAgent: 'pending',
      SolveAgent: 'pending',
      ToolAgent: 'pending',
      ResponseAgent: 'pending',
      PrecisionAnswerAgent: 'pending',
    },
    tokenStats: {
      model: 'Unknown',
      calls: 0,
      tokens: 0,
      input_tokens: 0,
      output_tokens: 0,
      cost: 0.0,
    },
    progress: {
      stage: null,
      progress: {},
    },
  })
  const solverWs = useRef<WebSocket | null>(null)

  const startSolver = (question: string, kb: string) => {
    if (solverWs.current) solverWs.current.close()

    setSolverState(prev => ({
      ...prev,
      isSolving: true,
      logs: [],
      messages: [...prev.messages, { role: 'user', content: question }],
      question,
      selectedKb: kb,
      agentStatus: {
        InvestigateAgent: 'pending',
        NoteAgent: 'pending',
        ManagerAgent: 'pending',
        SolveAgent: 'pending',
        ToolAgent: 'pending',
        ResponseAgent: 'pending',
        PrecisionAnswerAgent: 'pending',
      },
      tokenStats: {
        model: 'Unknown',
        calls: 0,
        tokens: 0,
        input_tokens: 0,
        output_tokens: 0,
        cost: 0.0,
      },
      progress: {
        stage: null,
        progress: {},
      },
    }))

    const ws = new WebSocket(wsUrl('/api/v1/solve'))
    solverWs.current = ws

    ws.onopen = () => {
      ws.send(JSON.stringify({ question, kb_name: kb }))
      addSolverLog({ type: 'system', content: 'Initializing connection...' })
    }

    ws.onmessage = event => {
      const data = JSON.parse(event.data)
      if (data.type === 'log') {
        addSolverLog(data)
      } else if (data.type === 'agent_status') {
        setSolverState(prev => ({
          ...prev,
          agentStatus: data.all_agents || {
            ...prev.agentStatus,
            [data.agent]: data.status,
          },
        }))
      } else if (data.type === 'token_stats') {
        setSolverState(prev => ({
          ...prev,
          tokenStats: data.stats || prev.tokenStats,
        }))
      } else if (data.type === 'progress') {
        setSolverState(prev => ({
          ...prev,
          progress: {
            stage: data.stage,
            progress: data.progress || {},
          },
        }))
      } else if (data.type === 'result') {
        // Extract relative path from output_dir if possible, or just store the full path name
        // data.output_dir is likely absolute path on server.
        // We need the directory name to construct URL: /api/outputs/solve/{dir_name}/...
        // Assuming output_dir ends with "solve_YYYYMMDD_HHMMSS"
        let dirName = ''
        if (data.output_dir) {
          const parts = data.output_dir.split(/[/\\]/)
          dirName = parts[parts.length - 1]
        }

        setSolverState(prev => ({
          ...prev,
          messages: [
            ...prev.messages,
            {
              role: 'assistant',
              content: data.final_answer,
              outputDir: dirName,
            },
          ],
          isSolving: false,
        }))
        ws.close()
      } else if (data.type === 'error') {
        addSolverLog({
          type: 'error',
          content: `Error: ${data.content || data.message || 'Unknown error'}`,
        })
        setSolverState(prev => ({ ...prev, isSolving: false }))
      }
    }

    ws.onerror = () => {
      addSolverLog({ type: 'error', content: 'Connection error' })
      setSolverState(prev => ({
        ...prev,
        isSolving: false,
        agentStatus: {
          InvestigateAgent: 'error',
          NoteAgent: 'error',
          ManagerAgent: 'error',
          SolveAgent: 'error',
          ToolAgent: 'error',
          ResponseAgent: 'error',
          PrecisionAnswerAgent: 'error',
        },
        progress: {
          stage: null,
          progress: {},
        },
      }))
    }

    ws.onclose = () => {
      // Clean up WebSocket reference on close
      if (solverWs.current === ws) {
        solverWs.current = null
      }
    }
  }

  // Stop the current solving process
  const stopSolver = () => {
    if (solverWs.current) {
      // Close the WebSocket to signal cancellation to backend
      solverWs.current.close()
      solverWs.current = null
    }
    // Reset solving state but keep logs for user reference if desired
    setSolverState(prev => ({
      ...prev,
      isSolving: false,
      // Optionally clear logs or keep them; here we keep existing logs
    }))
    addSolverLog({ type: 'system', content: 'Solver stopped by user.' })
  }

  const addSolverLog = (log: LogEntry) => {
    setSolverState(prev => ({ ...prev, logs: [...prev.logs, log] }))
  }

  // --- Question Logic ---
  const [questionState, setQuestionState] = useState<QuestionState>({
    step: 'config',
    mode: 'knowledge',
    logs: [],
    results: [],
    topic: '',
    difficulty: 'medium',
    type: 'choice',
    count: 1,
    selectedKb: '',
    progress: {
      stage: null,
      progress: {},
      subFocuses: [],
      activeQuestions: [],
      completedQuestions: 0,
      failedQuestions: 0,
    },
    agentStatus: {
      QuestionGenerationAgent: 'pending',
      ValidationWorkflow: 'pending',
      RetrievalTool: 'pending',
    },
    tokenStats: {
      model: 'Unknown',
      calls: 0,
      tokens: 0,
      input_tokens: 0,
      output_tokens: 0,
      cost: 0.0,
    },
    uploadedFile: null,
    paperPath: '',
  })
  const questionWs = useRef<WebSocket | null>(null)

  const startQuestionGen = (
    topic: string,
    diff: string,
    type: string,
    count: number,
    kb: string
  ) => {
    if (questionWs.current) questionWs.current.close()

    setQuestionState(prev => ({
      ...prev,
      step: 'generating',
      mode: 'knowledge',
      logs: [],
      results: [],
      topic,
      difficulty: diff,
      type,
      count,
      selectedKb: kb,
      progress: {
        stage: count > 1 ? 'planning' : 'generating',
        progress: { current: 0, total: count },
        subFocuses: [],
        activeQuestions: [],
        completedQuestions: 0,
        failedQuestions: 0,
      },
      agentStatus: {
        QuestionGenerationAgent: 'pending',
        ValidationWorkflow: 'pending',
        RetrievalTool: 'pending',
      },
      tokenStats: {
        model: 'Unknown',
        calls: 0,
        tokens: 0,
        input_tokens: 0,
        output_tokens: 0,
        cost: 0.0,
      },
    }))

    const ws = new WebSocket(wsUrl('/api/v1/question/generate'))
    questionWs.current = ws

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          requirement: {
            knowledge_point: topic,
            difficulty: diff,
            question_type: type,
            additional_requirements: 'Ensure clarity and academic rigor.',
          },
          count: count,
          kb_name: kb,
        })
      )
      addQuestionLog({ type: 'system', content: 'Initializing Generator...' })
    }

    ws.onmessage = event => {
      const data = JSON.parse(event.data)
      if (data.type === 'log') {
        addQuestionLog(data)
        // Parse progress info from log content (fallback for any remaining print statements)
        if (data.content.includes('Generating question')) {
          const match = data.content.match(/(\d+)\/(\d+)/)
          if (match) {
            setQuestionState(prev => ({
              ...prev,
              progress: {
                stage: 'generating',
                progress: {
                  current: parseInt(match[1]),
                  total: parseInt(match[2]),
                },
              },
            }))
          }
        }
        if (data.content.includes('Round') || data.content.includes('round')) {
          const match = data.content.match(/Round\s+(\d+)/i)
          if (match) {
            setQuestionState(prev => ({
              ...prev,
              progress: {
                ...prev.progress,
                progress: {
                  ...prev.progress.progress,
                  round: parseInt(match[1]),
                },
              },
            }))
          }
        }
        if (data.content.includes('Validation') || data.content.includes('validation')) {
          setQuestionState(prev => ({
            ...prev,
            progress: {
              stage: 'validating',
              progress: prev.progress.progress,
            },
          }))
        }
      } else if (data.type === 'agent_status') {
        // Handle agent status updates
        setQuestionState(prev => ({
          ...prev,
          agentStatus: data.all_agents || {
            ...prev.agentStatus,
            [data.agent]: data.status,
          },
        }))
      } else if (data.type === 'token_stats') {
        // Handle token statistics updates
        setQuestionState(prev => ({
          ...prev,
          tokenStats: data.stats || prev.tokenStats,
        }))
      } else if (data.type === 'progress') {
        // Handle structured progress updates (including parallel generation stages)
        setQuestionState(prev => ({
          ...prev,
          progress: {
            stage: data.stage || prev.progress.stage,
            progress: {
              ...prev.progress.progress,
              ...data.progress,
              total: data.total ?? prev.progress.progress.total,
            },
            subFocuses: data.focuses || data.sub_focuses || prev.progress.subFocuses,
            activeQuestions: prev.progress.activeQuestions,
            completedQuestions: data.completed ?? prev.progress.completedQuestions,
            failedQuestions: data.failed ?? prev.progress.failedQuestions,
          },
        }))
      } else if (data.type === 'question_update') {
        // Handle individual question updates (custom mode)
        const statusLabel =
          data.status === 'analyzing'
            ? 'Analyzing relevance'
            : data.status === 'generating'
              ? 'Generating'
              : data.status === 'done'
                ? 'Completed'
                : data.status
        addQuestionLog({
          type: data.status === 'done' ? 'success' : 'system',
          content: `[${data.question_id}] ${statusLabel}${data.focus ? `: ${data.focus.slice(0, 50)}...` : ''}`,
        })
      } else if (data.type === 'question_error') {
        // Handle individual question errors in parallel mode
        addQuestionLog({
          type: 'error',
          content: `[${data.question_id}] Error: ${data.error}${data.reason ? ` - ${data.reason}` : ''}`,
        })
      } else if (data.type === 'knowledge_saved') {
        // Handle knowledge saved event (custom mode)
        addQuestionLog({
          type: 'success',
          content: `Background knowledge retrieved (${data.queries?.length || 0} queries)`,
        })
      } else if (data.type === 'plan_ready') {
        // Handle plan ready event (custom mode)
        const focuses = data.focuses || data.plan?.focuses || []
        setQuestionState(prev => ({
          ...prev,
          progress: {
            ...prev.progress,
            stage: 'planning',
            subFocuses: focuses,
            progress: {
              ...prev.progress.progress,
              status: 'plan_ready',
            },
          },
        }))
        addQuestionLog({
          type: 'success',
          content: `Question plan created with ${focuses.length} focuses`,
        })
      } else if (data.type === 'batch_summary') {
        // Handle batch summary from custom mode generation
        setQuestionState(prev => ({
          ...prev,
          progress: {
            ...prev.progress,
            subFocuses: data.sub_focuses || data.plan?.focuses || prev.progress.subFocuses,
            completedQuestions: data.completed || prev.results.length,
            failedQuestions: data.failed || 0,
            progress: {
              ...prev.progress.progress,
              current: data.completed || prev.results.length,
              total: data.requested || prev.count,
            },
          },
        }))
        addQuestionLog({
          type: 'success',
          content: `Generation complete: ${data.completed}/${data.requested} questions generated${data.failed > 0 ? `, ${data.failed} failed` : ''}`,
        })
      } else if (data.type === 'result') {
        const isExtended = data.extended || data.validation?.decision === 'extended'
        const questionPreview = data.question?.question?.slice(0, 50) || 'Unknown'
        addQuestionLog({
          type: 'success',
          content: `Question ${data.question_id || (data.index !== undefined ? `#${data.index + 1}` : '')} generated: ${questionPreview}...`,
        })
        setQuestionState(prev => ({
          ...prev,
          results: [
            ...prev.results,
            {
              question: data.question,
              validation: data.validation,
              rounds: data.rounds || 1,
              extended: isExtended,
            },
          ],
          progress: {
            ...prev.progress,
            stage: 'generating',
            completedQuestions: prev.results.length + 1,
            progress: {
              ...prev.progress.progress,
              current: prev.results.length + 1,
              total: prev.count,
              round: data.rounds || 1,
            },
            extendedQuestions: (prev.progress.extendedQuestions || 0) + (isExtended ? 1 : 0),
          },
        }))
      } else if (data.type === 'complete') {
        setQuestionState(prev => ({
          ...prev,
          step: 'result',
          progress: {
            ...prev.progress,
            stage: 'complete',
            completedQuestions: prev.results.length,
          },
        }))
        ws.close()
      } else if (data.type === 'error') {
        addQuestionLog({
          type: 'error',
          content: `Error: ${data.content || data.message || 'Unknown error'}`,
        })
        setQuestionState(prev => ({
          ...prev,
          progress: {
            stage: null,
            progress: {},
          },
        }))
      }
    }

    ws.onerror = () => {
      addQuestionLog({ type: 'error', content: 'WebSocket connection error' })
      setQuestionState(prev => ({
        ...prev,
        step: 'config',
        progress: {
          stage: null,
          progress: {},
        },
        agentStatus: {
          QuestionGenerationAgent: 'pending',
          ValidationWorkflow: 'pending',
          RetrievalTool: 'pending',
        },
      }))
    }

    ws.onclose = () => {
      // Clean up WebSocket reference on close
      if (questionWs.current === ws) {
        questionWs.current = null
      }
    }
  }

  const startMimicQuestionGen = async (
    file: File | null,
    paperPath: string,
    kb: string,
    maxQuestions?: number
  ) => {
    if (questionWs.current) questionWs.current.close()

    // Support two modes: PDF upload or pre-parsed directory
    const hasFile = file !== null
    const hasParsedPath = paperPath && paperPath.trim() !== ''

    if (!hasFile && !hasParsedPath) {
      addQuestionLog({
        type: 'error',
        content: 'Please upload a PDF file or provide a parsed exam directory',
      })
      return
    }

    setQuestionState(prev => ({
      ...prev,
      step: 'generating',
      mode: 'mimic',
      logs: [],
      results: [],
      selectedKb: kb,
      uploadedFile: file,
      paperPath: paperPath,
      progress: {
        stage: hasFile ? 'uploading' : 'parsing', // Start with uploading for PDF, parsing for pre-parsed
        progress: { current: 0, total: maxQuestions || 1 },
      },
      agentStatus: {
        QuestionGenerationAgent: 'pending',
        ValidationWorkflow: 'pending',
        RetrievalTool: 'pending',
      },
      tokenStats: {
        model: 'Unknown',
        calls: 0,
        tokens: 0,
        input_tokens: 0,
        output_tokens: 0,
        cost: 0.0,
      },
    }))

    const ws = new WebSocket(wsUrl('/api/v1/question/mimic'))
    questionWs.current = ws

    ws.onopen = async () => {
      if (hasFile && file) {
        // Convert file to base64
        addQuestionLog({
          type: 'system',
          content: 'Preparing to upload PDF file...',
        })
        const reader = new FileReader()
        reader.onload = () => {
          const base64Data = (reader.result as string).split(',')[1] // Remove data:application/pdf;base64, prefix
          ws.send(
            JSON.stringify({
              mode: 'upload',
              pdf_data: base64Data,
              pdf_name: file.name,
              kb_name: kb,
              max_questions: maxQuestions,
            })
          )
          addQuestionLog({
            type: 'system',
            content: `Uploaded: ${file.name}, parsing...`,
          })
        }
        reader.readAsDataURL(file)
      } else {
        // Use pre-parsed directory
        ws.send(
          JSON.stringify({
            mode: 'parsed',
            paper_path: paperPath,
            kb_name: kb,
            max_questions: maxQuestions,
          })
        )
        addQuestionLog({
          type: 'system',
          content: 'Initializing Mimic Generator...',
        })
      }
    }

    ws.onmessage = event => {
      const data = JSON.parse(event.data)

      if (data.type === 'log') {
        addQuestionLog(data)
      } else if (data.type === 'status') {
        // Status updates for mimic mode stages
        const stageMap: Record<string, string> = {
          init: 'uploading',
          upload: 'uploading',
          parsing: 'parsing',
          processing: 'extracting',
        }
        const mappedStage = stageMap[data.stage] || data.stage

        addQuestionLog({
          type: 'system',
          content: data.content || data.message || `Stage: ${data.stage}`,
        })

        // Update progress stage based on status event
        if (mappedStage) {
          setQuestionState(prev => ({
            ...prev,
            progress: {
              ...prev.progress,
              stage: mappedStage,
            },
          }))
        }
      } else if (data.type === 'progress') {
        // Progress updates for mimic mode (parsing, extracting, generating)
        const stage = data.stage || 'generating'
        const message = data.message || ''

        addQuestionLog({
          type: 'system',
          content: message,
        })

        setQuestionState(prev => ({
          ...prev,
          progress: {
            ...prev.progress,
            stage: stage,
            progress: {
              ...prev.progress.progress,
              current: data.current ?? prev.progress.progress.current,
              total: data.total_questions ?? data.total ?? prev.progress.progress.total,
              status: data.status,
            },
          },
        }))

        // Store reference questions info when extracting is complete
        if (stage === 'extracting' && data.status === 'complete' && data.reference_questions) {
          setQuestionState(prev => ({
            ...prev,
            progress: {
              ...prev.progress,
              progress: {
                ...prev.progress.progress,
                total: data.total_questions || data.reference_questions.length,
              },
            },
          }))
        }
      } else if (data.type === 'question_update') {
        // Individual question status update during generation
        const statusMessage =
          data.status === 'generating'
            ? `Generating mimic question ${data.index}...`
            : data.status === 'failed'
              ? `Question ${data.index} failed: ${data.error}`
              : `Question ${data.index}: ${data.status}`

        addQuestionLog({
          type: data.status === 'failed' ? 'warning' : 'system',
          content: statusMessage,
        })

        if (data.current !== undefined) {
          setQuestionState(prev => ({
            ...prev,
            progress: {
              ...prev.progress,
              progress: {
                ...prev.progress.progress,
                current: data.current,
              },
            },
          }))
        }
      } else if (data.type === 'result') {
        // Single question result
        const isExtended = data.extended || data.validation?.decision === 'extended'

        addQuestionLog({
          type: 'success',
          content: `✅ Question ${data.index || (data.current ?? 0)} generated successfully`,
        })

        setQuestionState(prev => ({
          ...prev,
          results: [
            ...prev.results,
            {
              question: data.question,
              validation: data.validation,
              rounds: data.rounds || 1,
              reference_question: data.reference_question,
              extended: isExtended,
            },
          ],
          progress: {
            ...prev.progress,
            stage: 'generating',
            progress: {
              ...prev.progress.progress,
              current: data.current ?? prev.results.length + 1,
              total: data.total ?? prev.progress.progress.total ?? 1,
            },
            extendedQuestions: (prev.progress.extendedQuestions || 0) + (isExtended ? 1 : 0),
          },
        }))
      } else if (data.type === 'summary') {
        // Final summary for mimic mode
        addQuestionLog({
          type: 'success',
          content: `Generation complete: ${data.successful}/${data.total_reference} succeeded`,
        })

        setQuestionState(prev => ({
          ...prev,
          progress: {
            ...prev.progress,
            stage: 'generating',
            progress: {
              current: data.successful,
              total: data.total_reference,
            },
            completedQuestions: data.successful,
            failedQuestions: data.failed,
          },
        }))
      } else if (data.type === 'complete') {
        addQuestionLog({
          type: 'success',
          content: '✅ Mimic generation completed!',
        })

        setQuestionState(prev => ({
          ...prev,
          step: 'result',
          progress: {
            ...prev.progress,
            stage: 'complete',
            completedQuestions: prev.results.length,
          },
        }))
        ws.close()
      } else if (data.type === 'error') {
        addQuestionLog({
          type: 'error',
          content: `Error: ${data.content || data.message || 'Unknown error'}`,
        })
        setQuestionState(prev => ({
          ...prev,
          step: 'config',
          progress: {
            stage: null,
            progress: {},
          },
        }))
      }
    }

    ws.onerror = () => {
      addQuestionLog({ type: 'error', content: 'WebSocket connection error' })
      setQuestionState(prev => ({ ...prev, step: 'config' }))
    }
  }

  const resetQuestionGen = () => {
    setQuestionState(prev => ({
      ...prev,
      step: 'config',
      results: [],
      logs: [],
      progress: {
        stage: null,
        progress: {},
        subFocuses: [],
        activeQuestions: [],
        completedQuestions: 0,
        failedQuestions: 0,
      },
      agentStatus: {
        QuestionGenerationAgent: 'pending',
        ValidationWorkflow: 'pending',
        RetrievalTool: 'pending',
      },
      tokenStats: {
        model: 'Unknown',
        calls: 0,
        tokens: 0,
        input_tokens: 0,
        output_tokens: 0,
        cost: 0.0,
      },
      uploadedFile: null,
      paperPath: '',
    }))
  }

  const addQuestionLog = (log: LogEntry) => {
    setQuestionState(prev => ({ ...prev, logs: [...prev.logs, log] }))
  }

  // --- Research Logic ---
  const [researchState, setResearchState] = useState<ResearchState>({
    status: 'idle',
    logs: [],
    report: null,
    topic: '',
    selectedKb: '',
    progress: {
      stage: null,
      status: '',
      executionMode: undefined,
      totalBlocks: undefined,
      currentBlock: undefined,
      currentSubTopic: undefined,
      currentBlockId: undefined,
      iterations: undefined,
      maxIterations: undefined,
      toolsUsed: undefined,
      currentTool: undefined,
      currentQuery: undefined,
      currentRationale: undefined,
      queriesUsed: undefined,
      activeTasks: undefined,
      activeCount: undefined,
      completedCount: undefined,
      keptBlocks: undefined,
      sections: undefined,
      wordCount: undefined,
      citations: undefined,
    },
  })
  const researchWs = useRef<WebSocket | null>(null)

  const startResearch = (
    topic: string,
    kb: string,
    planMode: string = 'medium',
    enabledTools: string[] = ['RAG'],
    skipRephrase: boolean = false
  ) => {
    if (researchWs.current) researchWs.current.close()

    setResearchState(prev => ({
      ...prev,
      status: 'running',
      logs: [],
      report: null,
      topic,
      selectedKb: kb,
      progress: {
        stage: null,
        status: '',
        executionMode: undefined,
        totalBlocks: undefined,
        currentBlock: undefined,
        currentSubTopic: undefined,
        currentBlockId: undefined,
        iterations: undefined,
        maxIterations: undefined,
        toolsUsed: undefined,
        currentTool: undefined,
        currentQuery: undefined,
        currentRationale: undefined,
        queriesUsed: undefined,
        activeTasks: undefined,
        activeCount: undefined,
        completedCount: undefined,
        keptBlocks: undefined,
        sections: undefined,
        wordCount: undefined,
        citations: undefined,
      },
    }))

    const ws = new WebSocket(wsUrl('/api/v1/research/run'))
    researchWs.current = ws

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          topic,
          kb_name: kb,
          plan_mode: planMode,
          enabled_tools: enabledTools,
          skip_rephrase: skipRephrase,
        })
      )
      addResearchLog({
        type: 'system',
        content: `Starting Research Pipeline (Plan: ${planMode}, Tools: ${enabledTools.join('+')}, Optimization: ${!skipRephrase ? 'On' : 'Off/Pre-done'})...`,
      })
    }

    ws.onmessage = event => {
      const data = JSON.parse(event.data)
      if (data.type === 'log') {
        addResearchLog(data)
      } else if (data.type === 'progress') {
        // Handle structured progress messages with enhanced fields
        setResearchState(prev => {
          // Parse active tasks for parallel mode
          const activeTasks: ActiveTaskInfo[] =
            data.active_tasks?.map((t: any) => ({
              block_id: t.block_id,
              sub_topic: t.sub_topic,
              status: t.status,
              iteration: t.iteration || 0,
              max_iterations: t.max_iterations,
              current_tool: t.current_tool,
              current_query: t.current_query,
              tools_used: t.tools_used,
            })) ?? prev.progress.activeTasks

          // Parse queries used
          const queriesUsed: QueryInfo[] =
            data.queries_used?.map((q: any) => ({
              query: q.query,
              tool_type: q.tool_type,
              rationale: q.rationale,
              iteration: q.iteration,
            })) ?? prev.progress.queriesUsed

          return {
            ...prev,
            progress: {
              stage: data.stage,
              status: data.status,
              // Execution mode
              executionMode: data.execution_mode ?? prev.progress.executionMode,
              // Planning details
              totalBlocks: data.total_blocks ?? prev.progress.totalBlocks,
              // Researching details
              currentBlock: data.current_block ?? prev.progress.currentBlock,
              currentSubTopic: data.sub_topic ?? prev.progress.currentSubTopic,
              currentBlockId: data.block_id ?? prev.progress.currentBlockId,
              iterations: data.iteration ?? data.iterations ?? prev.progress.iterations,
              maxIterations: data.max_iterations ?? prev.progress.maxIterations,
              toolsUsed: data.tools_used ?? prev.progress.toolsUsed,
              // Current action details
              currentTool: data.tool_type ?? prev.progress.currentTool,
              currentQuery: data.query ?? prev.progress.currentQuery,
              currentRationale: data.rationale ?? prev.progress.currentRationale,
              queriesUsed: queriesUsed,
              // Parallel mode specific
              activeTasks: activeTasks,
              activeCount: data.active_count ?? prev.progress.activeCount,
              completedCount: data.completed_count ?? prev.progress.completedCount,
              // Reporting details
              keptBlocks: data.kept_blocks ?? prev.progress.keptBlocks,
              sections: data.sections ?? prev.progress.sections,
              wordCount: data.word_count ?? prev.progress.wordCount,
              citations: data.citations ?? prev.progress.citations,
            },
          }
        })
      } else if (data.type === 'result') {
        setResearchState(prev => ({
          ...prev,
          status: 'completed',
          report: data.report,
        }))
        ws.close()
      } else if (data.type === 'error') {
        addResearchLog({
          type: 'error',
          content: `Error: ${data.content || data.message || 'Unknown error'}`,
        })
        setResearchState(prev => ({ ...prev, status: 'idle' }))
      }
    }

    ws.onerror = () => {
      addResearchLog({ type: 'error', content: 'WebSocket connection error' })
      setResearchState(prev => ({
        ...prev,
        status: 'idle',
        progress: {
          stage: null,
          status: '',
          executionMode: undefined,
          activeTasks: undefined,
        },
      }))
    }

    ws.onclose = () => {
      // Clean up WebSocket reference on close
      if (researchWs.current === ws) {
        researchWs.current = null
      }
    }
  }

  const addResearchLog = (log: LogEntry) => {
    setResearchState(prev => ({ ...prev, logs: [...prev.logs, log] }))
  }

  // --- IdeaGen Logic ---
  const [ideaGenState, setIdeaGenState] = useState<IdeaGenState>({
    isGenerating: false,
    generationStatus: '',
    generatedIdeas: [],
    progress: null,
  })

  // --- Chat (simplified: only session loading for history page) ---
  const loadChatSession = async (sessionId: string) => {
    // Just return the sessionId — the history page navigates to /chat?session=xxx
    // No need to store state in GlobalContext anymore
    return
  }

  return (
    <GlobalContext.Provider
      value={{
        solverState,
        setSolverState,
        startSolver,
        stopSolver,
        questionState,
        setQuestionState,
        startQuestionGen,
        startMimicQuestionGen,
        resetQuestionGen,
        researchState,
        setResearchState,
        startResearch,
        ideaGenState,
        setIdeaGenState,
        loadChatSession,
        uiSettings,
        refreshSettings,
        sidebarWidth,
        setSidebarWidth,
        sidebarCollapsed,
        setSidebarCollapsed,
        toggleSidebar,
      }}
    >
      {children}
    </GlobalContext.Provider>
  )
}

export const useGlobal = () => {
  const context = useContext(GlobalContext)
  if (!context) throw new Error('useGlobal must be used within GlobalProvider')
  return context
}
