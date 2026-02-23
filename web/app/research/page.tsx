'use client'

/* eslint-disable react-hooks/exhaustive-deps */

import React, { useState, useEffect, useRef } from 'react'
import {
  Settings,
  Sparkles,
  Play,
  MessageSquare,
  Send,
  Loader2,
  Database,
  GraduationCap,
  Globe,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeRaw from 'rehype-raw'
import 'katex/dist/katex.min.css'
import { Mermaid } from '@/components/Mermaid'
import { useGlobal } from '@/context/GlobalContext'
import { apiUrl, wsUrl } from '@/lib/api'
import AddToNotebookModal from '@/components/AddToNotebookModal'
import { exportToPdf, preprocessMarkdownForPdf } from '@/lib/pdfExport'
import { useResearchReducer } from '@/hooks/useResearchReducer'
import { ResearchDashboard } from '@/components/research/ResearchDashboard'
import { ResearchEvent } from '@/types/research'

interface ChatMsg {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  type?: 'topic_proposal'
  proposal?: string
  original_topic?: string
  iteration?: number
  isOptimizing?: boolean
}

interface SourceItem {
  id: string
  type: 'web' | 'kb' | 'report'
  title: string
  url?: string
  content?: string
  selected: boolean
  groupId?: string
  groupTitle?: string
  addedAt?: number
}

interface PersistedResearchState {
  research_id?: string
  task_id?: string
  topic?: string
  kb_name?: string
  plan_mode?: string
  enabled_tools?: string[]
  started_at?: number
  report_url?: string
  metadata_url?: string
}

const RESEARCH_STORAGE_KEY = 'deeptutor.research.state'
const RESEARCH_SOURCES_KEY = 'deeptutor.research.sources'

export default function ResearchPage() {
  const { setResearchState: setGlobalResearchState } = useGlobal()

  // Local Reducer State for Deep Research Dashboard
  const [state, dispatch] = useResearchReducer()
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)

  // Config State
  const [selectedKb, setSelectedKb] = useState<string>('')
  const [kbs, setKbs] = useState<string[]>([])
  const [planMode, setPlanMode] = useState<string>('medium')
  const [enabledTools, setEnabledTools] = useState<string[]>(['RAG'])
  const [enableOptimization, setEnableOptimization] = useState<boolean>(true)

  // Chat State
  const [chatHistory, setChatHistory] = useState<ChatMsg[]>([])
  const [inputTopic, setInputTopic] = useState('')
  const [isOptimizing, setIsOptimizing] = useState(false)
  const chatContainerRef = useRef<HTMLDivElement>(null)
  const [sources, setSources] = useState<SourceItem[]>([])
  const [isRestoring, setIsRestoring] = useState(true)
  const [restoreError, setRestoreError] = useState<string | null>(null)

  // Notebook modal state
  const [showNotebookModal, setShowNotebookModal] = useState(false)

  // PDF export state
  const [isExportingPdf, setIsExportingPdf] = useState(false)
  const [isExportingPptx, setIsExportingPptx] = useState(false)
  const [pptStylePrompt, setPptStylePrompt] = useState<string>('')
  const [pptStyleModel, setPptStyleModel] = useState<string>('')
  const [pptApiKey, setPptApiKey] = useState<string>('')
  const [pptBaseUrl, setPptBaseUrl] = useState<string>('')
  // Ref for report content (hidden rendered report for PDF)
  const reportContentRef = useRef<HTMLDivElement>(null)

  // WebSocket Ref
  const wsRef = useRef<WebSocket | null>(null)
  // Track whether a result has been received for the current WebSocket session,
  // so that ws.onclose does not clobber state with a stale restoreResearchState call.
  const resultReceivedRef = useRef(false)

  const readPersistedState = (): PersistedResearchState | null => {
    try {
      const raw = localStorage.getItem(RESEARCH_STORAGE_KEY)
      if (!raw) return null
      return JSON.parse(raw) as PersistedResearchState
    } catch {
      return null
    }
  }

  const writePersistedState = (updates: Partial<PersistedResearchState>) => {
    try {
      const current = readPersistedState() || {}
      const next = { ...current, ...updates }
      localStorage.setItem(RESEARCH_STORAGE_KEY, JSON.stringify(next))
    } catch {
      // Ignore storage failures
    }
  }

  const clearPersistedState = () => {
    try {
      localStorage.removeItem(RESEARCH_STORAGE_KEY)
    } catch {
      // Ignore storage failures
    }
  }

  const sourceKey = (item: SourceItem) =>
    `${item.groupId || 'ungrouped'}:${item.type}:${item.url || item.title || item.id}`

  const mergeSources = (existing: SourceItem[], incoming: SourceItem[]) => {
    const seen = new Set(existing.map(sourceKey))
    const merged = [...existing]
    incoming.forEach(item => {
      const key = sourceKey(item)
      if (seen.has(key)) return
      seen.add(key)
      merged.push(item)
    })
    return merged
  }

  const readStoredSources = (): SourceItem[] => {
    try {
      const raw = localStorage.getItem(RESEARCH_SOURCES_KEY)
      if (!raw) return []
      const parsed = JSON.parse(raw)
      if (!Array.isArray(parsed)) return []
      return parsed as SourceItem[]
    } catch {
      return []
    }
  }

  const writeStoredSources = (nextSources: SourceItem[]) => {
    try {
      localStorage.setItem(RESEARCH_SOURCES_KEY, JSON.stringify(nextSources))
    } catch {
      // Ignore storage failures
    }
  }

  const formatGroupTitle = (topic: string, metadata?: any) => {
    const completedAt = metadata?.completed_at
    if (completedAt) {
      const date = new Date(completedAt)
      if (!Number.isNaN(date.getTime())) {
        return `${topic || '未命名研究'} · ${date.toLocaleString()}`
      }
    }
    return topic || '未命名研究'
  }

  const buildSourcesFromMetadata = (
    metadata: any,
    report: string,
    topic: string,
    researchId?: string
  ): SourceItem[] => {
    const groupId = researchId || metadata?.research_id || 'ungrouped'
    const groupTitle = formatGroupTitle(topic, metadata)
    const addedAt = Date.now()
    const items: SourceItem[] = []
    if (report) {
      items.push({
        id: `report-${Date.now()}`,
        type: 'report',
        title: topic ? `深度研究报告 - ${topic}` : '深度研究报告',
        content: report,
        selected: true,
        groupId,
        groupTitle,
        addedAt,
      })
    }

    const webSources = metadata?.web_sources
    if (Array.isArray(webSources)) {
      webSources.forEach((s: any, idx: number) => {
        items.push({
          id: `web-${Date.now()}-${idx}`,
          type: 'web',
          title: s.title || s.url || `网络来源 ${idx + 1}`,
          url: s.url || '',
          content: s.content || s.snippet || '',
          selected: true,
          groupId,
          groupTitle,
          addedAt,
        })
      })
    }

    const ragSources = metadata?.rag_sources
    if (Array.isArray(ragSources)) {
      ragSources.forEach((s: any, idx: number) => {
        const title = s.title || s.source || s.source_file || s.kb_name || `知识库来源 ${idx + 1}`
        const detailParts: string[] = []
        if (s.page) detailParts.push(`页 ${s.page}`)
        if (s.chunk_id) detailParts.push(`段落 ${s.chunk_id}`)
        const detail = detailParts.join(' · ')
        items.push({
          id: `rag-${Date.now()}-${idx}`,
          type: 'kb',
          title,
          url: detail,
          content: s.content || s.content_preview || '',
          selected: true,
          groupId,
          groupTitle,
          addedAt,
        })
      })
    }

    const miscSources = metadata?.sources
    if (Array.isArray(miscSources)) {
      miscSources.forEach((s: any, idx: number) => {
        items.push({
          id: `src-${Date.now()}-${idx}`,
          type: s.type === 'web' ? 'web' : 'kb',
          title: s.title || s.url || `来源 ${idx + 1}`,
          url: s.url || '',
          content: s.content || s.snippet || '',
          selected: true,
          groupId,
          groupTitle,
          addedAt,
        })
      })
    }

    return items
  }

  const appendReportToChat = (report: string) => {
    if (!report) return
    setChatHistory(prev => {
      const existing = prev.find(msg => msg.id === 'research-report')
      const content = `**📚 深度研究完成**\n\n${report}`
      if (existing) {
        return prev.map(msg => (msg.id === 'research-report' ? { ...msg, content } : msg))
      }
      return [
        ...prev,
        {
          id: 'research-report',
          role: 'assistant',
          content,
        },
      ]
    })
  }

  const fetchReportText = async (reportUrl: string) => {
    if (!reportUrl) return ''
    const url = reportUrl.startsWith('http') ? reportUrl : apiUrl(reportUrl)
    const res = await fetch(url)
    if (!res.ok) return ''
    return res.text()
  }

  const restoreResearchState = async (reason: string) => {
    setRestoreError(null)
    const persisted = readPersistedState()
    if (!persisted) return
    let researchId = persisted.research_id
    if (!researchId && persisted.topic) {
      try {
        const res = await fetch(
          apiUrl(`/api/v1/research/latest?topic=${encodeURIComponent(persisted.topic)}`)
        )
        if (res.ok) {
          const data = await res.json()
          researchId = data.research_id
          if (researchId) {
            writePersistedState({ research_id: researchId })
          }
        }
      } catch {
        // Ignore lookup failures
      }
    }

    if (!researchId) return

    try {
      const res = await fetch(apiUrl(`/api/v1/research/status/${researchId}`))
      if (!res.ok) {
        return
      }
      const data = await res.json()
      if (data.metadata?.topic) {
        writePersistedState({ topic: data.metadata.topic })
      }
      dispatch({ type: 'reset' })
      const storedSources = readStoredSources()
      setSources(storedSources)

      const applyProgress = (progress: any) => {
        if (!progress?.events || !Array.isArray(progress.events)) return
        progress.events.forEach((event: any) => {
          if (!event?.status) return
          const { status, ...rest } = event
          dispatch({ type: status as any, ...rest } as ResearchEvent)
        })
      }

      applyProgress(data.progress?.planning)
      applyProgress(data.progress?.researching)
      applyProgress(data.progress?.reporting)

      if (data.stage && data.stage !== 'idle') {
        setGlobalResearchState(prev => ({
          ...prev,
          status: data.stage === 'completed' ? 'completed' : 'running',
          topic: persisted.topic || data.metadata?.topic || prev.topic,
        }))
      }

      let reportContent = ''
      if (data.report_url) {
        reportContent = await fetchReportText(data.report_url)
      }

      const reportingEvents = data.progress?.reporting?.events || []
      const completedEvent = [...reportingEvents]
        .reverse()
        .find((event: any) => event.status === 'reporting_completed')

      if (reportContent) {
        dispatch({
          type: 'reporting_completed',
          word_count:
            completedEvent?.word_count || data.metadata?.report_word_count || reportContent.length,
          sections: completedEvent?.sections || 0,
          citations: completedEvent?.citations || 0,
          report: reportContent,
        } as ResearchEvent)
        appendReportToChat(reportContent)
        setGlobalResearchState(prev => ({
          ...prev,
          status: 'completed',
          report: reportContent,
          topic: persisted.topic || data.metadata?.topic || prev.topic,
        }))
      }

      if (data.metadata || reportContent) {
        const nextSources = buildSourcesFromMetadata(
          data.metadata,
          reportContent,
          persisted.topic || data.metadata?.topic || '',
          researchId
        )
        const merged = mergeSources(readStoredSources(), nextSources)
        setSources(merged)
        writeStoredSources(merged)
      }

      writePersistedState({
        research_id: researchId,
        report_url: data.report_url || persisted.report_url,
        metadata_url: data.metadata_url || persisted.metadata_url,
      })
    } catch (error) {
      setRestoreError(`恢复失败${reason ? `(${reason})` : ''}: ${String(error)}`)
    }
  }

  // Initialize Knowledge Bases
  useEffect(() => {
    fetch(apiUrl('/api/v1/knowledge/list'))
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          const names = data.map((kb: any) => kb.name)
          setKbs(names)
          if (!selectedKb) {
            const defaultKb = data.find((kb: any) => kb.is_default)?.name || names[0]
            if (defaultKb) setSelectedKb(defaultKb)
          }
        }
      })
      .catch(err => console.error('Failed to fetch KBs:', err))
  }, [])

  // Auto-scroll Chat
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTo({
        top: chatContainerRef.current.scrollHeight,
        behavior: 'smooth',
      })
    }
  }, [chatHistory])

  useEffect(() => {
    const runRestore = async () => {
      const persisted = readPersistedState()
      if (persisted?.kb_name) {
        setSelectedKb(persisted.kb_name)
      }
      if (persisted?.plan_mode) {
        setPlanMode(persisted.plan_mode)
      }
      if (persisted?.enabled_tools) {
        setEnabledTools(persisted.enabled_tools)
      }
      const storedSources = readStoredSources()
      if (storedSources.length > 0) {
        setSources(storedSources)
      }
      await restoreResearchState('mount')
      setIsRestoring(false)
    }
    runRestore()
  }, [])

  // Initial Greeting
  useEffect(() => {
    if (isRestoring) return
    if (chatHistory.length === 0) {
      setChatHistory([
        {
          id: 'welcome',
          role: 'assistant',
          content:
            'Welcome to Deep Research Lab. \n\nPlease configure your settings above, then enter a research topic below.',
        },
      ])
    }
  }, [chatHistory.length, isRestoring])

  // Select latest active task automatically if none selected
  useEffect(() => {
    if (!selectedTaskId && state.activeTaskIds.length > 0) {
      setSelectedTaskId(state.activeTaskIds[0])
    }
  }, [state.activeTaskIds, selectedTaskId])

  // Start Research Function (Local)
  const startResearchLocal = (topic: string) => {
    // Mark the old WebSocket as "done" so its onclose handler won't restore stale state
    resultReceivedRef.current = true
    if (wsRef.current) wsRef.current.close()
    resultReceivedRef.current = false
    clearPersistedState()
    dispatch({ type: 'reset' })
    setSelectedTaskId(null)
    setRestoreError(null)
    writePersistedState({
      topic,
      kb_name: selectedKb,
      plan_mode: planMode,
      enabled_tools: enabledTools,
      started_at: Date.now(),
    })

    // Update Global State to "running" for sidebar status
    setGlobalResearchState(prev => ({
      ...prev,
      status: 'running',
      topic,
      report: null,
    }))

    const ws = new WebSocket(wsUrl('/api/v1/research/run'))
    wsRef.current = ws

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          topic,
          kb_name: selectedKb,
          plan_mode: planMode,
          enabled_tools: enabledTools,
          skip_rephrase: !enableOptimization, // If we already optimized, skip internal rephrase
        })
      )
    }

    ws.onmessage = event => {
      try {
        const data = JSON.parse(event.data)

        if (data.type === 'task_id') {
          if (data.task_id) {
            writePersistedState({ task_id: data.task_id })
          }
          return
        }

        if (data.type === 'status') {
          if (data.research_id) {
            writePersistedState({ research_id: data.research_id })
          }
          return
        }

        if (data.type === 'report_path') {
          if (typeof data.path === 'string') {
            if (data.path.includes('/api/outputs/')) {
              writePersistedState({ report_url: data.path })
            }
          }
          return
        }

        if (data.type === 'ping') {
          return
        }

        // Dispatch all events to reducer
        if (data.type === 'progress') {
          // Flatten progress event to match ResearchEvent
          const rest = { ...data }
          delete rest.type
          // Map stage/status to event type if specific type is generic
          const eventType = data.status as string
          // Map known statuses to specific event types if needed or pass through
          dispatch({
            type: eventType as any, // dynamic mapping
            ...rest,
          })
        } else if (data.type === 'log') {
          dispatch({
            type: 'log',
            content: data.content.content || data.content, // Handle different log formats
          })
        } else if (data.type === 'result') {
          resultReceivedRef.current = true
          if (data.research_id) {
            writePersistedState({ research_id: data.research_id })
          }
          dispatch({
            type: 'reporting_completed',
            word_count: data.metadata?.report_word_count || 0,
            sections: Object.keys(data.metadata?.statistics || {}).length, // approximate
            citations: data.metadata?.statistics?.total_tool_calls || 0,
            report: data.report,
          })
          // Update Global State to "completed"
          setGlobalResearchState(prev => ({
            ...prev,
            status: 'completed',
            report: data.report,
            topic:
              data.metadata?.topic ||
              state.planning.originalTopic ||
              state.planning.optimizedTopic ||
              prev.topic,
          }))
          appendReportToChat(data.report || '')
          if (data.metadata || data.report) {
            const topic =
              data.metadata?.topic ||
              state.planning.originalTopic ||
              state.planning.optimizedTopic ||
              ''
            const nextSources = buildSourcesFromMetadata(
              data.metadata,
              data.report || '',
              topic,
              data.research_id
            )
            setSources(prev => {
              const merged = mergeSources(prev, nextSources)
              writeStoredSources(merged)
              return merged
            })
          }
          writePersistedState({
            research_id: data.research_id || readPersistedState()?.research_id,
          })
        } else if (data.type === 'error') {
          dispatch({ type: 'error', content: data.content })
          setGlobalResearchState(prev => ({ ...prev, status: 'idle' }))
        } else {
          // Forward other events directly
          dispatch(data as ResearchEvent)
        }
      } catch (e) {
        console.error('WS Parse Error', e)
      }
    }

    ws.onerror = e => {
      console.error('WS Error', e)
      dispatch({ type: 'error', content: 'WebSocket connection failed' })
      setGlobalResearchState(prev => ({ ...prev, status: 'idle' }))
      // Don't call restoreResearchState here — onerror is always followed by
      // onclose (per WebSocket spec), so let onclose handle the restore to
      // avoid restoring twice.
    }

    ws.onclose = () => {
      // Only restore if the WebSocket closed unexpectedly (no result received).
      // If a result was already processed, or a new research session replaced this
      // WebSocket, restoring would clobber the current state with stale data.
      if (!resultReceivedRef.current) {
        restoreResearchState('ws-close')
      }
    }
  }

  const handleSendMessage = async () => {
    if (!inputTopic.trim()) return
    if (state.global.stage !== 'idle' && state.global.stage !== 'completed') return

    const userMsg: ChatMsg = {
      id: Date.now().toString(),
      role: 'user',
      content: inputTopic,
    }

    setChatHistory(prev => [...prev, userMsg])
    setInputTopic('')

    if (!enableOptimization) {
      startResearchLocal(userMsg.content)
      return
    }

    setIsOptimizing(true)
    setChatHistory(prev => [
      ...prev,
      {
        id: 'optimizing',
        role: 'assistant',
        content: 'Optimizing topic...',
        isOptimizing: true,
      },
    ])

    try {
      const res = await fetch(apiUrl('/api/v1/research/optimize_topic'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: userMsg.content,
          iteration: 0,
          kb_name: selectedKb,
        }),
      })
      const data = await res.json()

      setChatHistory(prev => prev.filter(msg => msg.id !== 'optimizing'))

      if (data.error) {
        setChatHistory(prev => [
          ...prev,
          {
            id: Date.now().toString(),
            role: 'assistant',
            content: `Error optimizing: ${data.error}`,
          },
        ])
      } else {
        const optimizedTopic = data.topic || userMsg.content
        setChatHistory(prev => [
          ...prev,
          {
            id: Date.now().toString(),
            role: 'assistant',
            content: `I have optimized your topic:\n\n**${optimizedTopic}**\n\n${data.reasoning || ''}\n\nStart research?`,
            type: 'topic_proposal',
            proposal: optimizedTopic,
            original_topic: userMsg.content,
          },
        ])
      }
    } catch {
      setChatHistory(prev => prev.filter(msg => msg.id !== 'optimizing'))
      setChatHistory(prev => [
        ...prev,
        {
          id: Date.now().toString(),
          role: 'assistant',
          content: `Network error. Try again.`,
        },
      ])
    } finally {
      setIsOptimizing(false)
    }
  }

  // PDF Export using the new pdfExport utility
  const handleExportPdf = async () => {
    if (!state.reporting.generatedReport) return
    if (!reportContentRef.current) return

    setIsExportingPdf(true)
    try {
      // Wait for Mermaid diagrams and KaTeX formulas to render
      await new Promise(resolve => setTimeout(resolve, 2000))

      // Use the new PDF export utility
      await exportToPdf(reportContentRef.current, {
        filename: state.planning.originalTopic || 'research-report',
        marginLeft: 20,
        marginRight: 20,
        marginTop: 25,
        marginBottom: 25,
        showPageNumbers: true,
        scale: 2,
      })
    } catch (err) {
      console.error('PDF Export failed', err)
    } finally {
      setIsExportingPdf(false)
    }
  }

  const handleExportPptx = async () => {
    if (!state.reporting.generatedReport) return

    setIsExportingPptx(true)
    try {
      const res = await fetch(apiUrl('/api/v1/research/export_pptx'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          markdown: state.reporting.generatedReport,
          title: state.planning.originalTopic || undefined,
          style_prompt: pptStylePrompt || undefined,
          style_model: pptStyleModel || undefined,
          style_api_key: pptApiKey || undefined,
          style_base_url: pptBaseUrl || undefined,
        }),
      })

      if (!res.ok) {
        throw new Error(await res.text())
      }

      const data = await res.json()
      const downloadUrl = typeof data?.download_url === 'string' ? data.download_url : ''
      if (!downloadUrl) return

      const href = downloadUrl.startsWith('http') ? downloadUrl : apiUrl(downloadUrl)

      const a = document.createElement('a')
      a.href = href
      a.download =
        typeof data?.filename === 'string' && data.filename
          ? data.filename
          : `${state.planning.originalTopic || 'report'}.pptx`
      a.click()
    } catch (err) {
      console.error('PPTX Export failed', err)
    } finally {
      setIsExportingPptx(false)
    }
  }

  const toggleSourceSelection = (id: string) => {
    setSources(prev => {
      const next = prev.map(source =>
        source.id === id ? { ...source, selected: !source.selected } : source
      )
      writeStoredSources(next)
      return next
    })
  }

  const selectedSourcesCount = sources.filter(s => s.selected).length
  const totalSourcesCount = sources.length
  const groupedSources = sources.reduce(
    (acc, source) => {
      const groupId = source.groupId || 'ungrouped'
      if (!acc[groupId]) {
        acc[groupId] = {
          groupId,
          title: source.groupTitle || '未分组来源',
          items: [],
        }
      }
      acc[groupId].items.push(source)
      return acc
    },
    {} as Record<string, { groupId: string; title: string; items: SourceItem[] }>
  )

  const sourceGroups = Object.values(groupedSources).sort((a, b) => {
    const aTime = a.items[0]?.addedAt || 0
    const bTime = b.items[0]?.addedAt || 0
    return bTime - aTime
  })

  const toggleGroupSelection = (groupId: string, selected: boolean) => {
    setSources(prev => {
      const next = prev.map(source => {
        if (source.groupId === groupId) {
          return { ...source, selected }
        }
        return source
      })
      writeStoredSources(next)
      return next
    })
  }

  return (
    <div className="h-screen animate-fade-in flex gap-4 p-4">
      {/* LEFT PANEL */}
      <div className="flex-[1_1_33%] min-w-[350px] max-w-[500px] flex flex-col gap-4 h-full">
        {/* Config Header */}
        <div className="bg-white dark:bg-slate-800 p-4 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <h2 className="font-bold text-slate-800 dark:text-slate-100 flex items-center gap-2">
              <Settings className="w-5 h-5 text-slate-500 dark:text-slate-400" />
              配置
            </h2>
            <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
              <div
                className={`w-2 h-2 rounded-full ${state.global.stage !== 'idle' && state.global.stage !== 'completed' ? 'bg-emerald-500 animate-pulse' : 'bg-slate-300 dark:bg-slate-600'}`}
              />
              {state.global.stage === 'idle'
                ? '空闲'
                : state.global.stage === 'completed'
                  ? '已完成'
                  : '运行中'}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3">
            {/* KB Selection */}
            <div>
              <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1 block">
                知识库
              </label>
              <select
                value={selectedKb}
                onChange={e => setSelectedKb(e.target.value)}
                className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
              >
                {kbs.length === 0 && <option value="">加载中...</option>}
                {kbs.map(kb => (
                  <option key={kb} value={kb}>
                    {kb}
                  </option>
                ))}
              </select>
            </div>

            {/* Plan Mode */}
            <div>
              <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1 block">
                计划模式
              </label>
              <div className="flex bg-slate-50 dark:bg-slate-700 p-1 rounded-lg border border-slate-200 dark:border-slate-600">
                {['quick', 'medium', 'deep', 'auto'].map(mode => (
                  <button
                    key={mode}
                    onClick={() => setPlanMode(mode)}
                    className={`flex-1 py-1.5 text-xs font-medium rounded-md capitalize transition-all ${
                      planMode === mode
                        ? 'bg-white dark:bg-slate-600 text-emerald-700 dark:text-emerald-400 shadow-sm border border-slate-100 dark:border-slate-500'
                        : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300'
                    }`}
                  >
                    {mode === 'quick'
                      ? '快速'
                      : mode === 'medium'
                        ? '标准'
                        : mode === 'deep'
                          ? '深入'
                          : '自动'}
                  </button>
                ))}
              </div>
            </div>

            {/* Tools */}
            <div>
              <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1 block">
                研究工具
              </label>
              <div className="flex gap-2">
                {[
                  { key: 'RAG', label: '知识库', icon: Database },
                  { key: 'Paper', label: '论文', icon: GraduationCap },
                  { key: 'Web', label: '网络', icon: Globe },
                ].map(tool => {
                  const isSelected = enabledTools.includes(tool.key)
                  const Icon = tool.icon
                  return (
                    <button
                      key={tool.key}
                      onClick={() => {
                        if (isSelected && enabledTools.length === 1) return
                        setEnabledTools(prev =>
                          isSelected ? prev.filter(t => t !== tool.key) : [...prev, tool.key]
                        )
                      }}
                      className={`flex-1 flex items-center justify-center gap-1.5 py-2 px-2 rounded-lg text-xs font-medium transition-all border ${
                        isSelected
                          ? 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-700'
                          : 'bg-slate-50 dark:bg-slate-700 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-600'
                      }`}
                    >
                      <Icon className="w-3.5 h-3.5" />
                      {tool.label}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Optimization Toggle */}
            <div className="flex items-center justify-between bg-slate-50 dark:bg-slate-700 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600">
              <div className="flex items-center gap-2">
                <Sparkles
                  className={`w-4 h-4 ${enableOptimization ? 'text-indigo-500 dark:text-indigo-400' : 'text-slate-400 dark:text-slate-500'}`}
                />
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  主题优化
                </span>
              </div>
              <button
                onClick={() => setEnableOptimization(!enableOptimization)}
                className={`w-10 h-5 rounded-full relative transition-colors ${enableOptimization ? 'bg-indigo-500' : 'bg-slate-300 dark:bg-slate-600'}`}
              >
                <div
                  className={`absolute top-1 w-3 h-3 bg-white rounded-full transition-transform ${enableOptimization ? 'left-6' : 'left-1'}`}
                />
              </button>
            </div>

            <div>
              <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1 block">
                PPT 风格提示词
              </label>
              <textarea
                value={pptStylePrompt}
                onChange={e => setPptStylePrompt(e.target.value)}
                placeholder='例如："极简商务风，深蓝色主色调，少字多留白"'
                rows={3}
                className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20 resize-none"
              />
            </div>

            {/* PPT Model Configuration */}
            <div className="border border-slate-200 dark:border-slate-600 rounded-lg p-3 space-y-3">
              <div className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                PPT 调用模型配置（可选）
              </div>
              <div>
                <label className="text-xs text-slate-500 dark:text-slate-400 mb-1 block">
                  模型名称
                </label>
                <input
                  value={pptStyleModel}
                  onChange={e => setPptStyleModel(e.target.value)}
                  placeholder='例如："nano-banana"'
                  className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
                />
              </div>
              <div>
                <label className="text-xs text-slate-500 dark:text-slate-400 mb-1 block">
                  API Key
                </label>
                <input
                  type="password"
                  value={pptApiKey}
                  onChange={e => setPptApiKey(e.target.value)}
                  placeholder="留空则使用默认配置"
                  className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
                />
              </div>
              <div>
                <label className="text-xs text-slate-500 dark:text-slate-400 mb-1 block">
                  Base URL
                </label>
                <input
                  value={pptBaseUrl}
                  onChange={e => setPptBaseUrl(e.target.value)}
                  placeholder='例如："https://api.example.com/v1"'
                  className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Sources Panel */}
        <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 flex flex-col max-h-[220px] overflow-hidden">
          <div className="p-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider flex items-center justify-between">
            <span>已选来源</span>
            <span className="text-[10px] text-slate-400 dark:text-slate-500">
              {selectedSourcesCount}/{totalSourcesCount}
            </span>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-2 text-xs">
            {restoreError && <div className="text-rose-600 dark:text-rose-400">{restoreError}</div>}
            {sourceGroups.length === 0 && !restoreError && (
              <div className="text-slate-400 dark:text-slate-500">暂无来源</div>
            )}
            {sourceGroups.map(group => {
              const selectedCount = group.items.filter(s => s.selected).length
              const allSelected = selectedCount === group.items.length
              return (
                <div key={group.groupId} className="space-y-2">
                  <div className="flex items-center justify-between text-[10px] text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                    <span className="truncate">{group.title}</span>
                    <button
                      onClick={() => toggleGroupSelection(group.groupId, !allSelected)}
                      className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300"
                    >
                      {allSelected ? '取消全选' : '全选'} {selectedCount}/{group.items.length}
                    </button>
                  </div>
                  {group.items.map(source => (
                    <label
                      key={source.id}
                      className="flex items-start gap-2 p-2 rounded-lg bg-slate-50 dark:bg-slate-700/40 border border-slate-100 dark:border-slate-700 hover:border-slate-200 dark:hover:border-slate-600 transition-colors cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={source.selected}
                        onChange={() => toggleSourceSelection(source.id)}
                        className="mt-0.5"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="font-medium text-slate-700 dark:text-slate-200 truncate">
                          {source.title}
                        </div>
                        {source.url && (
                          <div className="text-[10px] text-slate-400 dark:text-slate-500 truncate">
                            {source.url}
                          </div>
                        )}
                        {source.content && (
                          <div className="text-[10px] text-slate-500 dark:text-slate-400 line-clamp-2 mt-1">
                            {source.content}
                          </div>
                        )}
                      </div>
                    </label>
                  ))}
                </div>
              )
            })}
          </div>
        </div>

        {/* Chat Interface */}
        <div className="flex-1 bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 flex flex-col overflow-hidden">
          <div className="p-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider flex items-center gap-2">
            <MessageSquare className="w-4 h-4" />
            主题助手
          </div>
          <div
            ref={chatContainerRef}
            className="flex-1 overflow-y-auto p-4 space-y-4 bg-slate-50/30 dark:bg-slate-800/30"
          >
            {chatHistory.map(msg => (
              <div
                key={msg.id}
                className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}
              >
                <div
                  className={`max-w-[90%] rounded-2xl px-4 py-3 text-sm ${msg.role === 'user' ? 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-900 dark:text-indigo-100 rounded-tr-none' : 'bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 text-slate-700 dark:text-slate-200 rounded-tl-none shadow-sm'}`}
                >
                  {msg.isOptimizing ? (
                    <div className="flex items-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin text-indigo-500 dark:text-indigo-400" />
                      <span>正在优化主题...</span>
                    </div>
                  ) : (
                    <div className="prose prose-sm dark:prose-invert max-w-none">
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                  )}
                </div>
                {msg.type === 'topic_proposal' && msg.proposal && state.global.stage === 'idle' && (
                  <div className="mt-2 flex gap-2 animate-fade-in">
                    <button
                      onClick={() => startResearchLocal(msg.proposal!)}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 text-white text-xs font-bold rounded-full hover:bg-emerald-700 shadow-lg shadow-emerald-500/20"
                    >
                      <Play className="w-3 h-3" /> 开始研究
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
          <div className="p-3 bg-white dark:bg-slate-800 border-t border-slate-100 dark:border-slate-700">
            <div className="relative flex items-center gap-2">
              <input
                type="text"
                value={inputTopic}
                onChange={e => setInputTopic(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSendMessage()}
                placeholder={
                  state.global.stage !== 'idle' && state.global.stage !== 'completed'
                    ? '研究进行中...'
                    : '请输入研究主题...'
                }
                disabled={state.global.stage !== 'idle' && state.global.stage !== 'completed'}
                className="flex-1 pl-4 pr-10 py-2.5 bg-slate-100 dark:bg-slate-700 border-transparent focus:bg-white dark:focus:bg-slate-600 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 rounded-xl text-sm text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500 transition-all outline-none disabled:opacity-50"
              />
              <button
                onClick={handleSendMessage}
                disabled={
                  !inputTopic.trim() ||
                  (state.global.stage !== 'idle' && state.global.stage !== 'completed')
                }
                className="p-2.5 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 disabled:opacity-50"
              >
                {isOptimizing ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* RIGHT PANEL: Research Dashboard */}
      <div className="flex-[2_1_67%] min-w-0 flex flex-col h-full overflow-hidden bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 relative">
        <ResearchDashboard
          state={state}
          selectedTaskId={selectedTaskId}
          onTaskSelect={setSelectedTaskId}
          onAddToNotebook={() => setShowNotebookModal(true)}
          onExportMarkdown={() => {
            const blob = new Blob([state.reporting.generatedReport || ''], {
              type: 'text/markdown',
            })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `${state.planning.originalTopic || '报告'}.md`
            a.click()
          }}
          onExportPdf={handleExportPdf}
          isExportingPdf={isExportingPdf}
          onExportPptx={handleExportPptx}
          pptStylePrompt={pptStylePrompt}
          onPptStylePromptChange={setPptStylePrompt}
          isExportingPptx={isExportingPptx}
        />
        {/* Hidden Render Div for PDF - uses preprocessed markdown */}
        <div
          style={{
            position: 'absolute',
            top: '-9999px',
            left: '-9999px',
            width: '800px',
          }}
        >
          <div
            ref={reportContentRef}
            className="bg-white"
            style={{
              padding: '50px 40px', // More vertical padding for better page spacing
              fontFamily: 'ui-sans-serif, system-ui, sans-serif',
              fontSize: '14px',
              lineHeight: '1.7',
              color: '#1e293b',
            }}
          >
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeKatex, rehypeRaw]}
              components={{
                h1: ({ ...props }) => (
                  <h1
                    style={{
                      fontSize: '26px',
                      fontWeight: 'bold',
                      marginBottom: '20px',
                      paddingBottom: '10px',
                      borderBottom: '2px solid #e2e8f0',
                    }}
                    {...props}
                  />
                ),
                h2: ({ ...props }) => (
                  <h2
                    style={{
                      fontSize: '20px',
                      fontWeight: 'bold',
                      marginTop: '28px',
                      marginBottom: '14px',
                      color: '#312e81',
                    }}
                    {...props}
                  />
                ),
                h3: ({ ...props }) => (
                  <h3
                    style={{
                      fontSize: '16px',
                      fontWeight: '600',
                      marginTop: '20px',
                      marginBottom: '10px',
                    }}
                    {...props}
                  />
                ),
                p: ({ ...props }) => (
                  <p style={{ marginBottom: '14px', textAlign: 'justify' }} {...props} />
                ),
                table: ({ ...props }) => (
                  <table
                    style={{
                      width: '100%',
                      borderCollapse: 'collapse',
                      margin: '18px 0',
                      fontSize: '13px',
                    }}
                    {...props}
                  />
                ),
                th: ({ ...props }) => (
                  <th
                    style={{
                      border: '1px solid #cbd5e1',
                      padding: '10px',
                      backgroundColor: '#f1f5f9',
                      fontWeight: '600',
                      textAlign: 'left',
                    }}
                    {...props}
                  />
                ),
                td: ({ ...props }) => (
                  <td style={{ border: '1px solid #e2e8f0', padding: '10px' }} {...props} />
                ),
                a: ({ href, ...props }) => (
                  <a
                    href={href}
                    style={{ color: '#4f46e5', textDecoration: 'underline' }}
                    {...props}
                  />
                ),
                blockquote: ({ ...props }) => (
                  <blockquote
                    style={{
                      borderLeft: '4px solid #c7d2fe',
                      paddingLeft: '16px',
                      margin: '18px 0',
                      color: '#475569',
                      fontStyle: 'italic',
                    }}
                    {...props}
                  />
                ),
                ul: ({ ...props }) => (
                  <ul style={{ marginLeft: '24px', marginBottom: '14px' }} {...props} />
                ),
                ol: ({ ...props }) => (
                  <ol style={{ marginLeft: '24px', marginBottom: '14px' }} {...props} />
                ),
                li: ({ ...props }) => <li style={{ marginBottom: '6px' }} {...props} />,
                // Handle details/summary for PDF - render as expanded
                details: ({ children }) => (
                  <div
                    style={{
                      marginTop: '8px',
                      marginBottom: '8px',
                      paddingLeft: '12px',
                      borderLeft: '2px solid #e2e8f0',
                    }}
                  >
                    {children}
                  </div>
                ),
                summary: ({ children }) => (
                  <div
                    style={{
                      fontWeight: '600',
                      color: '#475569',
                      marginBottom: '8px',
                    }}
                  >
                    {children}
                  </div>
                ),
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
                      style={{
                        backgroundColor: '#f1f5f9',
                        padding: '2px 6px',
                        borderRadius: '4px',
                        fontSize: '13px',
                        fontFamily: 'monospace',
                      }}
                      {...props}
                    >
                      {children}
                    </code>
                  ) : (
                    <code
                      style={{
                        display: 'block',
                        backgroundColor: '#1e293b',
                        color: '#e2e8f0',
                        padding: '16px',
                        borderRadius: '8px',
                        fontSize: '13px',
                        fontFamily: 'monospace',
                        overflowX: 'auto',
                        whiteSpace: 'pre',
                      }}
                      {...props}
                    >
                      {children}
                    </code>
                  )
                },
                pre: ({ children, ...props }) => {
                  const child = React.Children.toArray(children)[0] as React.ReactElement<{
                    className?: string
                  }>
                  if (child?.props?.className?.includes('language-mermaid')) {
                    return <>{children}</>
                  }
                  return (
                    <pre style={{ margin: '18px 0' }} {...props}>
                      {children}
                    </pre>
                  )
                },
              }}
            >
              {preprocessMarkdownForPdf(state.reporting.generatedReport || '')}
            </ReactMarkdown>
          </div>
        </div>
      </div>

      <AddToNotebookModal
        isOpen={showNotebookModal}
        onClose={() => setShowNotebookModal(false)}
        recordType="research"
        title={state.planning.originalTopic || 'Research Report'}
        userQuery={state.planning.originalTopic || ''}
        output={state.reporting.generatedReport || ''}
        metadata={{ plan_mode: planMode, enabled_tools: enabledTools }}
        kbName={selectedKb}
      />
    </div>
  )
}
