'use client'

/* eslint-disable react-hooks/exhaustive-deps */

import { useState, useEffect, useRef } from 'react'
import {
  Settings as SettingsIcon,
  Sun,
  Moon,
  Globe,
  Save,
  RotateCcw,
  Loader2,
  Check,
  Server,
  AlertCircle,
  Database,
  Search,
  Volume2,
  Cpu,
  Key,
  Brain,
  Eye,
  EyeOff,
  RefreshCw,
  CheckCircle,
  XCircle,
  Info,
  Sliders,
} from 'lucide-react'
import { apiUrl } from '@/lib/api'
import { getTranslation } from '@/lib/i18n'
import { setTheme } from '@/lib/theme'
import { debounce } from '@/lib/debounce'

import { useGlobal } from '@/context/GlobalContext'

// --- Types matching backend ---

interface UISettings {
  theme: 'light' | 'dark'
  language: 'zh' | 'en'
  output_language: 'zh' | 'en'
}

interface EnvInfo {
  model: string
  [key: string]: string
}

// Config is dynamic, but we know some structure
interface ConfigData {
  system?: {
    language?: string
    [key: string]: any
  }
  tools?: {
    rag_tool?: {
      kb_base_dir?: string
      default_kb?: string
      [key: string]: any
    }
    run_code?: {
      workspace?: string
      allowed_roots?: string[]
      language?: string
      timeout?: number
      sandbox?: boolean
      [key: string]: any
    }
    web_search?: {
      enabled?: boolean
      max_results?: number
      [key: string]: any
    }
    [key: string]: any
  }
  logging?: {
    level?: string
    [key: string]: any
  }
  tts?: {
    default_voice?: string
    default_language?: string
    [key: string]: any
  }
  [key: string]: any
}

interface FullSettingsResponse {
  ui: UISettings
  config: ConfigData
  env: EnvInfo
}

// Environment variable types
interface EnvVarInfo {
  key: string
  value: string
  description: string
  category: string
  required: boolean
  default: string
  sensitive: boolean
  is_set: boolean
}

interface EnvCategoryInfo {
  id: string
  name: string
  description: string
  icon: string
}

interface EnvConfigResponse {
  variables: EnvVarInfo[]
  categories: EnvCategoryInfo[]
}

interface TestResults {
  llm: { status: string; model: string | null; error: string | null; base_url?: string }
  embedding: { status: string; model: string | null; error: string | null; base_url?: string }
  tts: {
    status: string
    model: string | null
    error: string | null
    base_url?: string
    provider?: string
  }
}

interface LLMProvider {
  name: string
  binding: string
  base_url: string
  api_key: string
  model: string
  is_active: boolean
  provider_type: 'api' | 'local'
  requires_key: boolean
}

interface LLMModeInfo {
  mode: 'api' | 'local' | 'hybrid'
  active_provider: {
    name: string
    model: string
    provider_type: 'api' | 'local'
    binding: string
  } | null
  env_configured: boolean
  effective_source: 'env' | 'provider'
}

// Tab types
type SettingsTab = 'general' | 'environment' | 'local_models'

export default function SettingsPage() {
  const { uiSettings, refreshSettings } = useGlobal()
  const t = (key: string) => getTranslation(uiSettings.language, key)
  const [activeTab, setActiveTab] = useState<SettingsTab>('general')
  const [data, setData] = useState<FullSettingsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [error, setError] = useState('')

  // Edit states
  const [editedConfig, setEditedConfig] = useState<ConfigData | null>(null)
  const [editedUI, setEditedUI] = useState<UISettings | null>(null)

  // --- Helper Data ---

  interface ProviderPreset {
    id: string
    name: string
    binding: 'openai' | 'azure_openai' | 'ollama' | 'anthropic' | 'gemini' | 'groq' | 'openrouter'
    base_url?: string
    default_model: string
    models: string[]
    requires_key: boolean
    help_text?: string
  }

  // Local deployment presets only - cloud providers should use Environment Variables tab
  const PROVIDER_PRESETS: ProviderPreset[] = [
    {
      id: 'ollama',
      name: 'Ollama',
      binding: 'openai',
      base_url: 'http://localhost:11434/v1',
      default_model: 'llama3.2',
      models: [
        'llama3.2',
        'llama3.3',
        'qwen2.5',
        'qwen3',
        'mistral-nemo',
        'deepseek-r1',
        'gemma2',
        'phi3',
      ],
      requires_key: false,
      help_text:
        "Ollama runs models locally. Default: http://localhost:11434/v1. Run 'ollama serve' first.",
    },
    {
      id: 'lmstudio',
      name: 'LM Studio',
      binding: 'openai',
      base_url: 'http://127.0.0.1:1234',
      default_model: 'local-model',
      models: [],
      requires_key: false,
      help_text:
        "LM Studio provides a local OpenAI-compatible API. Default port: 1234. Use 'Refresh Models' to auto-detect loaded models.",
    },
    {
      id: 'llamacpp',
      name: 'llama.cpp Server',
      binding: 'openai',
      base_url: 'http://localhost:8080/v1',
      default_model: 'local-model',
      models: [],
      requires_key: false,
      help_text: 'llama.cpp server with OpenAI-compatible API. Default port: 8080.',
    },
    {
      id: 'vllm',
      name: 'vLLM',
      binding: 'openai',
      base_url: 'http://localhost:8000/v1',
      default_model: 'local-model',
      models: [],
      requires_key: false,
      help_text: 'vLLM high-throughput inference server. Default port: 8000.',
    },
    {
      id: 'custom',
      name: 'Custom Local Server',
      binding: 'openai',
      base_url: 'http://localhost:8000/v1',
      default_model: '',
      models: [],
      requires_key: false,
      help_text: 'Any OpenAI-compatible local server. Configure the URL and model manually.',
    },
  ]

  // Environment variables states
  const [envConfig, setEnvConfig] = useState<EnvConfigResponse | null>(null)
  const [editedEnvVars, setEditedEnvVars] = useState<Record<string, string>>({})
  const [showSensitive, setShowSensitive] = useState<Record<string, boolean>>({})
  const [envSaving, setEnvSaving] = useState(false)
  const [envSaveSuccess, setEnvSaveSuccess] = useState(false)
  const [envError, setEnvError] = useState('')
  const [testResults, setTestResults] = useState<TestResults | null>(null)
  // Individual service testing states
  const [testingService, setTestingService] = useState<Record<string, boolean>>({})
  const [serviceTestResults, setServiceTestResults] = useState<
    Record<
      string,
      {
        status: string
        model: string | null
        error: string | null
        response_time_ms: number | null
        message: string | null
        base_url?: string
        provider?: string
      }
    >
  >({})

  // LLM Providers state
  const [providers, setProviders] = useState<LLMProvider[]>([])
  const [loadingProviders, setLoadingProviders] = useState(false)
  const [ragProviders, setRagProviders] = useState<string[]>([])
  const [currentRagProvider, setCurrentRagProvider] = useState<string>('lightrag')
  const [editingProvider, setEditingProvider] = useState<LLMProvider | null>(null) // null means adding new
  const [selectedPresetId, setSelectedPresetId] = useState<string>('ollama')
  const [customModelInput, setCustomModelInput] = useState(true)
  const [showProviderForm, setShowProviderForm] = useState(false)
  const [testProviderResult, setTestProviderResult] = useState<{
    success: boolean
    message: string
  } | null>(null)
  const [testingProvider, setTestingProvider] = useState(false)
  const [fetchedModels, setFetchedModels] = useState<string[]>([])
  const [fetchingModels, setFetchingModels] = useState(false)
  const [savingProvider, setSavingProvider] = useState(false)
  const [providerError, setProviderError] = useState<string | null>(null)
  const [originalProviderName, setOriginalProviderName] = useState<string | null>(null)

  // LLM Mode state
  const [llmModeInfo, setLlmModeInfo] = useState<LLMModeInfo | null>(null)
  const [testing, setTesting] = useState(false)
  const [providerTypeFilter, setProviderTypeFilter] = useState<'all' | 'api' | 'local'>('all')

  // Create debounced theme save function
  const debouncedSaveTheme = useRef(
    debounce(async (themeValue: 'light' | 'dark', uiSettings: UISettings) => {
      try {
        await fetch(apiUrl('/api/v1/settings/ui'), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...uiSettings, theme: themeValue }),
        })
      } catch {
        // Silently fail - theme is still saved to localStorage
      }
    }, 500)
  ).current

  const [loadingRagProviders, setLoadingRagProviders] = useState(false)

  useEffect(() => {
    fetchSettings()
    fetchEnvConfig()
    fetchRagProviders()
    fetchLLMMode()
    if (activeTab === 'local_models') {
      fetchProviders()
    }
  }, [uiSettings, activeTab])

  const fetchLLMMode = async () => {
    try {
      const res = await fetch(apiUrl('/api/v1/config/llm/mode/'))
      if (res.ok) {
        const data = await res.json()
        setLlmModeInfo(data)
      }
    } catch (err) {
      console.error('Failed to fetch LLM mode:', err)
    }
  }

  const fetchProviders = async () => {
    setLoadingProviders(true)
    try {
      const res = await fetch(apiUrl('/api/v1/config/llm/'))
      if (res.ok) {
        const data = await res.json()
        setProviders(data)
      }
    } catch (err) {
      console.error('Failed to fetch providers:', err)
    } finally {
      setLoadingProviders(false)
    }
  }

  const fetchRagProviders = async () => {
    setLoadingRagProviders(true)
    try {
      const res = await fetch(apiUrl('/api/v1/settings/rag/providers'))
      if (res.ok) {
        const data = await res.json()
        setRagProviders(data.providers || [])
        setCurrentRagProvider(data.current || 'lightrag')
      }
    } catch (err) {
      console.error('Failed to fetch RAG providers:', err)
    } finally {
      setLoadingRagProviders(false)
    }
  }

  const fetchModels = async () => {
    if (!editingProvider || !editingProvider.base_url) return
    setFetchingModels(true)
    setFetchedModels([])

    try {
      const preset = PROVIDER_PRESETS.find(p => p.id === selectedPresetId)
      const requiresKey = preset ? preset.requires_key : true

      const res = await fetch(apiUrl('/api/v1/config/llm/models/'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...editingProvider, requires_key: requiresKey }),
      })

      const data = await res.json()
      if (data.success && Array.isArray(data.models) && data.models.length > 0) {
        setFetchedModels(data.models)
        setCustomModelInput(false)
      } else {
        // Fallback to preset models if available
        if (preset && preset.models.length > 0) {
          setFetchedModels(preset.models)
          if (!data.success) {
            console.warn('Backend model fetch failed, using presets:', data.message)
          }
        } else {
          alert(`No models found. ${data.message || ''}`)
        }
      }
    } catch (err) {
      console.error(err)
      const preset = PROVIDER_PRESETS.find(p => p.id === selectedPresetId)
      if (preset && preset.models.length > 0) {
        setFetchedModels(preset.models)
      } else {
        alert(t('Failed to connect to backend for model fetching.'))
      }
    } finally {
      setFetchingModels(false)
    }
  }

  const handleProviderSave = async (provider: LLMProvider) => {
    setSavingProvider(true)
    setProviderError(null)
    try {
      // 1. Validate model exists at the provider (optional)
      setProviderError(t('Validating model...'))

      const preset = PROVIDER_PRESETS.find(p => p.id === selectedPresetId)
      const requiresKey = preset ? preset.requires_key : true

      let isModelValid = false
      try {
        const modelCheckRes = await fetch(apiUrl('/api/v1/config/llm/models/'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...provider, requires_key: requiresKey }),
        })

        const modelData = await modelCheckRes.json()
        if (modelData.success && Array.isArray(modelData.models)) {
          const normalizeModel = (m: string) => m.split(':')[0].toLowerCase()
          const enteredModel = provider.model
          const normalizedEntered = normalizeModel(enteredModel)

          const isMatch = modelData.models.some(
            (m: string) => m === enteredModel || normalizeModel(m) === normalizedEntered
          )

          if (!isMatch) {
            const availableModels = modelData.models.slice(0, 5).join(', ')
            const warning = `${t('Model')} "${enteredModel}" ${t('not found at provider')}. ${t('Available')}: ${availableModels}${modelData.models.length > 5 ? '...' : ''}. ${t('Continue anyway?')}`
            if (!confirm(warning)) {
              setSavingProvider(false)
              setProviderError(null)
              return
            }
          } else {
            isModelValid = true
          }
        } else {
          // Model fetch failed but proceed with save
          console.warn('Model validation failed:', modelData.message)
        }
      } catch (validationErr) {
        console.warn('Model validation error:', validationErr)
        // Continue with save even if validation fails
      }

      setProviderError(isModelValid ? t('Model verified. Saving...') : t('Saving...'))

      // 2. Proceed with save
      const isUpdate = originalProviderName !== null && originalProviderName !== ''
      const method = isUpdate ? 'PUT' : 'POST'
      const url = isUpdate
        ? apiUrl(`/api/v1/config/llm/${encodeURIComponent(originalProviderName!)}`)
        : apiUrl('/api/v1/config/llm/')

      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(provider),
      })

      if (res.ok) {
        fetchProviders()
        setShowProviderForm(false)
        setEditingProvider(null)
        setOriginalProviderName(null)
      } else {
        const err = await res.json()
        setProviderError(err.detail || t('Failed to save provider'))
      }
    } catch (err) {
      console.error(err)
      setProviderError(`${t('An error occurred')}: ${(err as any).message}`)
    } finally {
      setSavingProvider(false)
    }
  }

  const handleDeleteProvider = async (name: string) => {
    if (!confirm(`${t('Delete provider')} ${name}?`)) return
    try {
      let url
      if (!name) {
        // Handle empty name using query param endpoint
        url = apiUrl('/api/v1/config/llm/?name=')
      } else {
        url = apiUrl(`/api/v1/config/llm/${encodeURIComponent(name)}`)
      }

      const res = await fetch(url, {
        method: 'DELETE',
      })
      if (res.ok) {
        fetchProviders()
      } else {
        const err = await res.json()
        alert(`${t('Failed to delete provider')}: ${err.detail || res.statusText}`)
      }
    } catch (err) {
      console.error(err)
      alert(`${t('Failed to delete provider')}: ${(err as any).message}`)
    }
  }

  const handleActivateProvider = async (name: string) => {
    try {
      const res = await fetch(apiUrl('/api/v1/config/llm/active/'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      if (res.ok) fetchProviders()
    } catch (err) {
      console.error(err)
    }
  }

  const handleTestProvider = async (provider: LLMProvider) => {
    setTestingProvider(true)
    setTestProviderResult(null)
    try {
      // Find preset to check if key is required
      const preset = PROVIDER_PRESETS.find(p => p.id === selectedPresetId)
      const requiresKey = preset ? preset.requires_key : true

      const res = await fetch(apiUrl('/api/v1/config/llm/test/'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...provider, requires_key: requiresKey }),
      })
      const data = await res.json()
      setTestProviderResult(data)
    } catch {
      setTestProviderResult({ success: false, message: t('Connection failed') })
    } finally {
      setTestingProvider(false)
    }
  }

  const fetchSettings = async () => {
    try {
      const res = await fetch(apiUrl('/api/v1/settings/'))
      if (res.ok) {
        const responseData = await res.json()
        setData(responseData)
        setEditedConfig(JSON.parse(JSON.stringify(responseData.config)))
        if (!editedUI) {
          const uiData = JSON.parse(JSON.stringify(responseData.ui))
          // localStorage takes priority over backend
          const storedTheme = localStorage.getItem('deeptutor-theme')
          if (storedTheme === 'light' || storedTheme === 'dark') {
            uiData.theme = storedTheme
          }
          setEditedUI(uiData)
          // Apply theme if present
          if (uiData.theme) {
            applyTheme(uiData.theme)
          }
        }
      } else {
        setError('Failed to load settings')
      }
    } catch {
      setError('Failed to connect to backend')
    } finally {
      setLoading(false)
    }
  }

  const fetchEnvConfig = async () => {
    try {
      const res = await fetch(apiUrl('/api/v1/settings/env/'))
      if (res.ok) {
        const responseData: EnvConfigResponse = await res.json()
        setEnvConfig(responseData)
        const initialValues: Record<string, string> = {}
        responseData.variables.forEach(v => {
          initialValues[v.key] = v.value
        })
        setEditedEnvVars(initialValues)
        // Auto test on load
        testEnvConfig()
      }
    } catch (err) {
      console.error('Failed to fetch env config:', err)
    }
  }

  const handleEnvVarChange = (key: string, value: string) => {
    setEditedEnvVars(prev => ({ ...prev, [key]: value }))
  }

  const toggleSensitiveVisibility = (key: string) => {
    setShowSensitive(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const handleEnvSave = async () => {
    setEnvSaving(true)
    setEnvSaveSuccess(false)
    setEnvError('')

    try {
      const updates = Object.entries(editedEnvVars)
        .filter(([key, value]) => {
          const original = envConfig?.variables.find(v => v.key === key)
          if (original?.sensitive && value.includes('*') && value === original.value) {
            return false
          }
          return true
        })
        .map(([key, value]) => ({ key, value }))

      const res = await fetch(apiUrl('/api/v1/settings/env/'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ variables: updates }),
      })

      if (!res.ok) {
        const errorData = await res.json()
        throw new Error(errorData.detail?.errors?.join(', ') || 'Failed to save')
      }

      setEnvSaveSuccess(true)
      setTimeout(() => setEnvSaveSuccess(false), 2000)

      await fetchEnvConfig()
      await testEnvConfig()
    } catch (err: any) {
      setEnvError(err.message || 'Failed to save environment variables')
    } finally {
      setEnvSaving(false)
    }
  }

  const testEnvConfig = async () => {
    setTesting(true)
    try {
      const res = await fetch(apiUrl('/api/v1/settings/env/test/'), {
        method: 'POST',
      })
      if (res.ok) {
        const results = await res.json()
        setTestResults(results)
      }
    } catch (err) {
      console.error('Failed to test env config:', err)
    } finally {
      setTesting(false)
    }
  }

  // Test a single service (llm, embedding, tts)
  const testSingleService = async (service: 'llm' | 'embedding' | 'tts') => {
    setTestingService(prev => ({ ...prev, [service]: true }))
    try {
      const res = await fetch(apiUrl(`/api/v1/settings/env/test/${service}`), {
        method: 'POST',
      })
      if (res.ok) {
        const result = await res.json()
        setServiceTestResults(prev => ({ ...prev, [service]: result }))
        // Also update testResults for status icons
        setTestResults(prev =>
          prev
            ? {
                ...prev,
                [service]: {
                  status: result.status === 'success' ? 'configured' : result.status,
                  model: result.model,
                  error: result.error,
                },
              }
            : null
        )
      }
    } catch (err) {
      console.error(`Failed to test ${service}:`, err)
      setServiceTestResults(prev => ({
        ...prev,
        [service]: {
          status: 'error',
          model: null,
          error: t('Connection failed'),
          response_time_ms: null,
          message: null,
        },
      }))
    } finally {
      setTestingService(prev => ({ ...prev, [service]: false }))
    }
  }

  const getCategoryIcon = (iconName: string) => {
    switch (iconName) {
      case 'brain':
        return <Brain className="w-4 h-4" />
      case 'database':
        return <Database className="w-4 h-4" />
      case 'volume':
        return <Volume2 className="w-4 h-4" />
      case 'search':
        return <Search className="w-4 h-4" />
      case 'settings':
        return <SettingsIcon className="w-4 h-4" />
      default:
        return <Key className="w-4 h-4" />
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'configured':
        return <CheckCircle className="w-4 h-4 text-green-500" />
      case 'not_configured':
        return <XCircle className="w-4 h-4 text-amber-500" />
      case 'error':
        return <AlertCircle className="w-4 h-4 text-red-500" />
      default:
        return <Info className="w-4 h-4 text-slate-400" />
    }
  }

  const applyTheme = (theme: 'light' | 'dark') => {
    // Persist theme to localStorage and document immediately
    setTheme(theme)
  }

  const handleSave = async () => {
    if (!editedConfig || !editedUI) return
    setSaving(true)
    setSaveSuccess(false)
    setError('')

    try {
      // 1. Save Environment Variables if they exist
      if (Object.keys(editedEnvVars).length > 0) {
        const envUpdates = Object.entries(editedEnvVars)
          .filter(([key, value]) => {
            const original = envConfig?.variables.find(v => v.key === key)
            // Don't send masked values back if they haven't changed
            if (original?.sensitive && value.includes('*') && value === original.value) {
              return false
            }
            return true
          })
          .map(([key, value]) => ({ key, value }))

        if (envUpdates.length > 0) {
          const envRes = await fetch(apiUrl('/api/v1/settings/env'), {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ variables: envUpdates }),
          })
          if (!envRes.ok) {
            const errorData = await envRes.json()
            throw new Error(
              errorData.detail?.errors?.join(', ') || t('Failed to save environment variables')
            )
          }
          // Reload env config immediately to get updated state (including persistence)
          await fetchEnvConfig()
        }
      }

      // 2. Save Config
      const configRes = await fetch(apiUrl('/api/v1/settings/config'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: editedConfig }),
      })

      if (!configRes.ok) throw new Error(t('Failed to save configuration'))

      // 3. Save UI Settings
      const uiRes = await fetch(apiUrl('/api/v1/settings/ui'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editedUI),
      })

      if (!uiRes.ok) throw new Error(t('Failed to save UI settings'))

      const newConfig = await configRes.json()
      const newUI = await uiRes.json()

      setData(prev => (prev ? { ...prev, config: newConfig, ui: newUI } : null))

      // Sync theme immediately when saving
      if (editedUI.theme) {
        setTheme(editedUI.theme)
      }

      await refreshSettings()

      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 2000)
    } catch (err: any) {
      setError(err.message || 'Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  const handleConfigChange = (section: string, key: string, value: any, subSection?: string) => {
    setEditedConfig(prev => {
      if (!prev) return null
      const newConfig = { ...prev }

      if (subSection) {
        if (!newConfig[section]) newConfig[section] = {}
        if (!newConfig[section][subSection]) newConfig[section][subSection] = {}
        newConfig[section][subSection][key] = value
      } else {
        if (!newConfig[section]) newConfig[section] = {}
        newConfig[section][key] = value
      }
      return newConfig
    })
  }

  const handleUIChange = (key: keyof UISettings, value: any) => {
    setEditedUI(prev => {
      if (!prev) return null
      const newUI = { ...prev, [key]: value }
      if (key === 'theme') {
        applyTheme(value)
        // Debounced auto-save to backend
        debouncedSaveTheme(value, newUI)
      }
      return newUI
    })
  }

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-blue-600 dark:text-blue-400" />
      </div>
    )
  }

  if (!editedConfig || !editedUI)
    return <div className="p-8 text-red-500 dark:text-red-400">Error loading data</div>

  return (
    <div className="h-screen overflow-y-auto animate-fade-in">
      {/* Sticky Save Button at Top */}
      <div className="sticky top-0 z-50 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700 shadow-md">
        <div className="max-w-4xl mx-auto p-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
              System Settings
            </h1>
          </div>
          <button
            onClick={handleSave}
            disabled={saving}
            className={`py-2 px-6 rounded-lg font-medium flex items-center gap-2 transition-all ${
              saving
                ? 'bg-slate-100 dark:bg-slate-700 text-slate-400 dark:text-slate-500'
                : saveSuccess
                  ? 'bg-green-500 text-white'
                  : 'bg-blue-600 text-white hover:bg-blue-700'
            }`}
          >
            {saving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : saveSuccess ? (
              <Check className="w-4 h-4" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {saving ? t('Saving...') : saveSuccess ? t('Saved') : t('Save All Changes')}
          </button>
        </div>
      </div>

      <div className="max-w-4xl mx-auto p-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100 flex items-center gap-3">
              <div className="p-2 bg-blue-50 dark:bg-blue-900/30 rounded-xl">
                <SettingsIcon className="w-6 h-6 text-blue-600 dark:text-blue-400" />
              </div>
              {t('System Settings')}
            </h1>
            <p className="text-slate-500 dark:text-slate-400 mt-2 ml-1">
              {t('Manage system configuration and preferences')}
            </p>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-1 p-1 bg-slate-100 dark:bg-slate-800 rounded-xl mb-4">
          <button
            onClick={() => setActiveTab('general')}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'general'
                ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
            }`}
          >
            <Sliders className="w-4 h-4" />
            {t('General Settings')}
          </button>
          <button
            onClick={() => setActiveTab('environment')}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'environment'
                ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
            }`}
          >
            <Key className="w-4 h-4" />
            {t('Environment Variables')}
            {testResults && (
              <span
                className={`ml-1 w-2 h-2 rounded-full ${
                  Object.values(testResults).every(r => r.status === 'configured')
                    ? 'bg-green-500'
                    : Object.values(testResults).some(r => r.status === 'error')
                      ? 'bg-red-500'
                      : 'bg-amber-500'
                }`}
              />
            )}
          </button>
          <button
            onClick={() => setActiveTab('local_models')}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'local_models'
                ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
            }`}
          >
            <Server className="w-4 h-4" />
            {t('LLM Providers')}
            {llmModeInfo && (
              <span
                className={`ml-1 px-1.5 py-0.5 text-[9px] rounded font-medium ${
                  llmModeInfo.mode === 'hybrid'
                    ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400'
                    : llmModeInfo.mode === 'api'
                      ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400'
                      : 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400'
                }`}
              >
                {llmModeInfo.mode.toUpperCase()}
              </span>
            )}
          </button>
        </div>

        {/* Configuration Status Panel - Quick Test */}
        <div className="mb-6 bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden">
          <div className="px-4 py-2.5 border-b border-slate-100 dark:border-slate-700 bg-gradient-to-r from-slate-50 to-blue-50/30 dark:from-slate-800/50 dark:to-blue-900/20 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Cpu className="w-4 h-4 text-blue-500 dark:text-blue-400" />
              <h2 className="font-semibold text-sm text-slate-900 dark:text-slate-100">
                {t('Configuration Status')}
              </h2>
            </div>
            <span className="text-[10px] text-slate-500 dark:text-slate-400">
              {t('Click each card to test')}
            </span>
          </div>
          <div className="p-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {/* LLM Status */}
              <div
                className={`p-3 rounded-lg border transition-all ${
                  serviceTestResults.llm?.status === 'success' ||
                  testResults?.llm?.status === 'configured'
                    ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800'
                    : serviceTestResults.llm?.status === 'error' ||
                        testResults?.llm?.status === 'error'
                      ? 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
                      : 'bg-slate-50 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Brain className="w-4 h-4 text-purple-500" />
                    <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
                      LLM
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {serviceTestResults.llm?.response_time_ms && (
                      <span className="text-[9px] text-slate-400">
                        {serviceTestResults.llm.response_time_ms}ms
                      </span>
                    )}
                    {(serviceTestResults.llm || testResults?.llm) &&
                      getStatusIcon(
                        serviceTestResults.llm?.status === 'success'
                          ? 'configured'
                          : serviceTestResults.llm?.status || testResults?.llm?.status || 'unknown'
                      )}
                  </div>
                </div>
                <p className="text-[10px] text-slate-600 dark:text-slate-400 font-mono truncate mb-1">
                  {serviceTestResults.llm?.model ||
                    testResults?.llm?.model ||
                    editedEnvVars['LLM_MODEL'] ||
                    t('Not configured')}
                </p>
                <p className="text-[10px] text-slate-500 dark:text-slate-500 truncate mb-2">
                  {editedEnvVars['LLM_HOST']
                    ? editedEnvVars['LLM_HOST'].includes('localhost') ||
                      editedEnvVars['LLM_HOST'].includes('127.0.0.1')
                      ? `🏠 ${editedEnvVars['LLM_HOST']}`
                      : `☁️ ${editedEnvVars['LLM_HOST']}`
                    : t('No endpoint')}
                </p>
                {serviceTestResults.llm?.message && (
                  <p className="text-[9px] text-green-600 dark:text-green-400 truncate mb-2">
                    {serviceTestResults.llm.message}
                  </p>
                )}
                {serviceTestResults.llm?.error && (
                  <p className="text-[9px] text-red-600 dark:text-red-400 truncate mb-2">
                    {serviceTestResults.llm.error}
                  </p>
                )}
                <button
                  onClick={() => testSingleService('llm')}
                  disabled={testingService.llm}
                  className="w-full py-1.5 text-[10px] font-medium text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-900/30 hover:bg-purple-100 dark:hover:bg-purple-900/50 rounded flex items-center justify-center gap-1.5 transition-colors border border-purple-200 dark:border-purple-800 disabled:opacity-50"
                >
                  {testingService.llm ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <RefreshCw className="w-3 h-3" />
                  )}
                  {testingService.llm ? t('Testing...') : t('Test LLM')}
                </button>
              </div>

              {/* Embedding Status */}
              <div
                className={`p-3 rounded-lg border transition-all ${
                  serviceTestResults.embedding?.status === 'success' ||
                  testResults?.embedding?.status === 'configured'
                    ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800'
                    : serviceTestResults.embedding?.status === 'error' ||
                        testResults?.embedding?.status === 'error'
                      ? 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
                      : 'bg-slate-50 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Database className="w-4 h-4 text-indigo-500" />
                    <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
                      {t('Embedding')}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {serviceTestResults.embedding?.response_time_ms && (
                      <span className="text-[9px] text-slate-400">
                        {serviceTestResults.embedding.response_time_ms}ms
                      </span>
                    )}
                    {(serviceTestResults.embedding || testResults?.embedding) &&
                      getStatusIcon(
                        serviceTestResults.embedding?.status === 'success'
                          ? 'configured'
                          : serviceTestResults.embedding?.status ||
                              testResults?.embedding?.status ||
                              'unknown'
                      )}
                  </div>
                </div>
                <p className="text-[10px] text-slate-600 dark:text-slate-400 font-mono truncate mb-1">
                  {serviceTestResults.embedding?.model ||
                    testResults?.embedding?.model ||
                    editedEnvVars['EMBEDDING_MODEL'] ||
                    t('Not configured')}
                </p>
                <p className="text-[10px] text-slate-500 dark:text-slate-500 truncate mb-2">
                  {editedEnvVars['EMBEDDING_HOST']
                    ? editedEnvVars['EMBEDDING_HOST'].includes('localhost') ||
                      editedEnvVars['EMBEDDING_HOST'].includes('127.0.0.1')
                      ? `🏠 ${editedEnvVars['EMBEDDING_HOST']}`
                      : `☁️ ${editedEnvVars['EMBEDDING_HOST']}`
                    : t('No endpoint')}
                </p>
                {serviceTestResults.embedding?.message && (
                  <p className="text-[9px] text-green-600 dark:text-green-400 truncate mb-2">
                    {serviceTestResults.embedding.message}
                  </p>
                )}
                {serviceTestResults.embedding?.error && (
                  <p className="text-[9px] text-red-600 dark:text-red-400 truncate mb-2">
                    {serviceTestResults.embedding.error}
                  </p>
                )}
                <button
                  onClick={() => testSingleService('embedding')}
                  disabled={testingService.embedding}
                  className="w-full py-1.5 text-[10px] font-medium text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-900/30 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 rounded flex items-center justify-center gap-1.5 transition-colors border border-indigo-200 dark:border-indigo-800 disabled:opacity-50"
                >
                  {testingService.embedding ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <RefreshCw className="w-3 h-3" />
                  )}
                  {testingService.embedding ? t('Testing...') : t('Test Embedding')}
                </button>
              </div>

              {/* TTS Status */}
              <div
                className={`p-3 rounded-lg border transition-all ${
                  serviceTestResults.tts?.status === 'success' ||
                  testResults?.tts?.status === 'configured'
                    ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800'
                    : serviceTestResults.tts?.status === 'error' ||
                        testResults?.tts?.status === 'error'
                      ? 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
                      : 'bg-slate-50 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Volume2 className="w-4 h-4 text-rose-500" />
                    <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
                      TTS
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {serviceTestResults.tts?.response_time_ms && (
                      <span className="text-[9px] text-slate-400">
                        {serviceTestResults.tts.response_time_ms}ms
                      </span>
                    )}
                    {(serviceTestResults.tts || testResults?.tts) &&
                      getStatusIcon(
                        serviceTestResults.tts?.status === 'success'
                          ? 'configured'
                          : serviceTestResults.tts?.status || testResults?.tts?.status || 'unknown'
                      )}
                  </div>
                </div>
                <p className="text-[10px] text-slate-600 dark:text-slate-400 font-mono truncate mb-1">
                  {serviceTestResults.tts?.model ||
                    testResults?.tts?.model ||
                    editedEnvVars['TTS_MODEL'] ||
                    t('Not configured')}
                </p>
                <p className="text-[10px] text-slate-500 dark:text-slate-500 truncate mb-2">
                  {serviceTestResults.tts?.base_url ||
                    testResults?.tts?.base_url ||
                    (editedEnvVars['TTS_PROVIDER'] === 'doubao'
                      ? editedEnvVars['TTS_DOUBAO_URL']
                      : editedEnvVars['TTS_URL']) ||
                    t('No endpoint')}
                </p>
                {serviceTestResults.tts?.message && (
                  <p className="text-[9px] text-green-600 dark:text-green-400 truncate mb-2">
                    {serviceTestResults.tts.message}
                  </p>
                )}
                {serviceTestResults.tts?.error && (
                  <p className="text-[9px] text-red-600 dark:text-red-400 truncate mb-2">
                    {serviceTestResults.tts.error}
                  </p>
                )}
                <button
                  onClick={() => testSingleService('tts')}
                  disabled={testingService.tts}
                  className="w-full py-1.5 text-[10px] font-medium text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-900/30 hover:bg-rose-100 dark:hover:bg-rose-900/50 rounded flex items-center justify-center gap-1.5 transition-colors border border-rose-200 dark:border-rose-800 disabled:opacity-50"
                >
                  {testingService.tts ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <RefreshCw className="w-3 h-3" />
                  )}
                  {testingService.tts ? t('Testing...') : t('Test TTS')}
                </button>
              </div>
            </div>
          </div>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl flex items-center gap-3 text-red-700 dark:text-red-400 font-medium">
            <AlertCircle className="w-5 h-5" />
            <span>{error}</span>
          </div>
        )}

        {/* General Settings Tab */}
        {activeTab === 'general' && (
          <div className="space-y-4">
            {/* Row 1: Interface + System Language + Active Model */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {/* Interface Settings */}
              <section className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex items-center gap-2">
                  <Globe className="w-4 h-4 text-blue-500 dark:text-blue-400" />
                  <h2 className="font-semibold text-sm text-slate-900 dark:text-slate-100">
                    {t('Interface Preferences')}
                  </h2>
                </div>
                <div className="p-4 space-y-4">
                  {/* Theme Mode */}
                  <div>
                    <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
                      {t('Theme')}
                    </label>
                    <div className="flex bg-slate-100 dark:bg-slate-700 p-0.5 rounded-lg">
                      {['light', 'dark'].map(themeOption => (
                        <button
                          key={themeOption}
                          onClick={() => handleUIChange('theme', themeOption as any)}
                          className={`flex-1 py-1.5 px-3 rounded-md text-xs font-medium flex items-center justify-center gap-1.5 transition-all ${
                            editedUI.theme === themeOption
                              ? 'bg-white dark:bg-slate-600 text-blue-600 dark:text-blue-400 shadow-sm'
                              : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
                          }`}
                        >
                          {themeOption === 'light' ? (
                            <Sun className="w-3.5 h-3.5" />
                          ) : (
                            <Moon className="w-3.5 h-3.5" />
                          )}
                          <span>{themeOption === 'light' ? t('Light Mode') : t('Dark Mode')}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                  {/* Interface Language */}
                  <div>
                    <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
                      {t('Language')}
                    </label>
                    <select
                      value={editedUI.language}
                      onChange={e => handleUIChange('language', e.target.value)}
                      className="w-full p-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
                    >
                      <option value="en">{t('English')}</option>
                      <option value="zh">{t('Chinese')}</option>
                    </select>
                  </div>
                </div>
              </section>

              {/* System Language */}
              <section className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex items-center gap-2">
                  <Server className="w-4 h-4 text-purple-500 dark:text-purple-400" />
                  <h2 className="font-semibold text-sm text-slate-900 dark:text-slate-100">
                    {t('System Configuration')}
                  </h2>
                </div>
                <div className="p-4">
                  <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                    {t('System Language')}
                  </label>
                  <p className="text-[10px] text-slate-400 dark:text-slate-500 mb-2">
                    {t('Default language for system operations')}
                  </p>
                  <select
                    value={editedConfig.system?.language || 'en'}
                    onChange={e => handleConfigChange('system', 'language', e.target.value)}
                    className="w-full p-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
                  >
                    <option value="en">{t('English')}</option>
                    <option value="zh">{t('Chinese')}</option>
                  </select>
                </div>
              </section>

              {/* Active Models Status */}
              {data?.env && (
                <section className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden">
                  <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Cpu className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
                      <h2 className="font-semibold text-sm text-slate-900 dark:text-slate-100">
                        {t('Active Models')}
                      </h2>
                    </div>
                    <span className="text-[10px] bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 px-1.5 py-0.5 rounded font-medium">
                      {t('Status')}
                    </span>
                  </div>
                  <div className="p-4">
                    <div className="flex items-center gap-3 p-3 bg-emerald-50 dark:bg-emerald-900/20 rounded-lg border border-emerald-100 dark:border-emerald-800">
                      <div className="p-2 bg-white dark:bg-slate-700 rounded-lg shadow-sm">
                        <Server className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-xs text-emerald-700 dark:text-emerald-300 font-medium">
                          {t('Active LLM Model')}
                        </p>
                        <p className="text-sm font-bold text-emerald-900 dark:text-emerald-200 font-mono truncate">
                          {data.env.model || t('Not configured')}
                        </p>
                      </div>
                    </div>
                  </div>
                </section>
              )}
            </div>

            {/* Row 2: RAG Provider (Currently locked to RAG-Anything) */}
            <section className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex items-center gap-2">
                <Database className="w-4 h-4 text-indigo-500 dark:text-indigo-400" />
                <h2 className="font-semibold text-sm text-slate-900 dark:text-slate-100">
                  {t('RAG Provider')}
                </h2>
              </div>
              <div className="p-4">
                <div className="flex flex-col lg:flex-row lg:items-start gap-4">
                  <div className="flex-1">
                    <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                      {t('Active RAG System')}
                    </label>
                    <p className="text-[10px] text-slate-400 dark:text-slate-500 mb-2">
                      {t(
                        'RAG-Anything provides end-to-end academic document processing with MinerU and LightRAG'
                      )}
                    </p>
                    {loadingRagProviders ? (
                      <div className="flex items-center gap-2 text-sm text-slate-500">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>{t('Loading providers...')}</span>
                      </div>
                    ) : (
                      <div className="w-full p-2 bg-slate-100 dark:bg-slate-700/50 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-700 dark:text-slate-300 flex items-center justify-between">
                        <span>
                          RAG-Anything - End-to-end academic document processing (MinerU + LightRAG)
                        </span>
                        <span className="text-[10px] px-2 py-0.5 bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400 rounded-full">
                          Default
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="lg:w-1/2 text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-700/50 p-3 rounded-lg border border-slate-100 dark:border-slate-600">
                    <p>
                      RAG-Anything combines MinerU for multimodal PDF parsing (images, tables,
                      equations) with LightRAG for knowledge graph construction.
                    </p>
                    <p className="mt-1.5">
                      <span className="font-medium text-slate-600 dark:text-slate-300">
                        Supported modes:
                      </span>{' '}
                      hybrid, local, global, naive
                    </p>
                  </div>
                </div>
              </div>
            </section>

            {/* Row 3: Research Tools (Web Search + Knowledge Base) + TTS */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {/* Research Tools */}
              <section className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex items-center gap-2">
                  <Search className="w-4 h-4 text-amber-500 dark:text-amber-400" />
                  <h2 className="font-semibold text-sm text-slate-900 dark:text-slate-100">
                    {t('Research Tools')}
                  </h2>
                </div>
                <div className="p-4 grid grid-cols-2 gap-3">
                  {/* Web Search */}
                  <div className="p-3 bg-slate-50 dark:bg-slate-700/50 rounded-lg border border-slate-100 dark:border-slate-600">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-xs font-medium text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
                        <Globe className="w-3.5 h-3.5 text-blue-500" />
                        {t('Web Search')}
                      </span>
                      <div className="relative inline-flex items-center cursor-pointer">
                        <input
                          type="checkbox"
                          checked={editedConfig.tools?.web_search?.enabled ?? true}
                          onChange={e =>
                            handleConfigChange('tools', 'enabled', e.target.checked, 'web_search')
                          }
                          className="sr-only peer"
                        />
                        <div className="w-9 h-5 bg-slate-200 dark:bg-slate-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 dark:after:border-slate-500 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-600"></div>
                      </div>
                    </div>
                    <div>
                      <label className="block text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">
                        {t('Max Results')}
                      </label>
                      <input
                        type="number"
                        min="1"
                        max="20"
                        value={editedConfig.tools?.web_search?.max_results || 5}
                        onChange={e =>
                          handleConfigChange(
                            'tools',
                            'max_results',
                            parseInt(e.target.value),
                            'web_search'
                          )
                        }
                        className="w-full p-1.5 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded text-xs text-slate-900 dark:text-slate-100"
                      />
                    </div>
                  </div>

                  {/* Knowledge Base */}
                  <div className="p-3 bg-slate-50 dark:bg-slate-700/50 rounded-lg border border-slate-100 dark:border-slate-600">
                    <div className="flex items-center mb-3">
                      <span className="text-xs font-medium text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
                        <Database className="w-3.5 h-3.5 text-purple-500" />
                        {t('Knowledge Base')}
                      </span>
                    </div>
                    <div className="space-y-2">
                      <div>
                        <label className="block text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">
                          {t('Default KB')}
                        </label>
                        <input
                          type="text"
                          value={editedConfig.tools?.rag_tool?.default_kb || ''}
                          onChange={e =>
                            handleConfigChange('tools', 'default_kb', e.target.value, 'rag_tool')
                          }
                          className="w-full p-1.5 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded text-xs text-slate-900 dark:text-slate-100"
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">
                          {t('Base Directory')}
                        </label>
                        <input
                          type="text"
                          value={editedConfig.tools?.rag_tool?.kb_base_dir || ''}
                          onChange={e =>
                            handleConfigChange('tools', 'kb_base_dir', e.target.value, 'rag_tool')
                          }
                          className="w-full p-1.5 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded text-xs font-mono text-slate-600 dark:text-slate-300"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </section>

              {/* TTS Settings */}
              <section className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex items-center gap-2">
                  <Volume2 className="w-4 h-4 text-rose-500 dark:text-rose-400" />
                  <h2 className="font-semibold text-sm text-slate-900 dark:text-slate-100">
                    {t('Text-to-Speech')}
                  </h2>
                </div>
                <div className="p-4 space-y-4">
                  {/* Provider Selection */}
                  <div>
                    <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
                      {t('Provider')}
                    </label>
                    <select
                      value={editedConfig.tts?.provider || 'openai'}
                      onChange={e => handleConfigChange('tts', 'provider', e.target.value)}
                      className="w-full p-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
                    >
                      <option value="openai">OpenAI / Compatible</option>
                      <option value="doubao">Doubao Podcast</option>
                    </select>
                  </div>

                  {editedConfig.tts?.provider === 'doubao' ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
                          {t('App ID')}
                        </label>
                        <input
                          type="text"
                          value={editedConfig.tts?.app_id || ''}
                          onChange={e => handleConfigChange('tts', 'app_id', e.target.value)}
                          className="w-full p-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
                          {t('Access Token')}
                        </label>
                        <input
                          type="password"
                          value={editedConfig.tts?.access_token || ''}
                          onChange={e => handleConfigChange('tts', 'access_token', e.target.value)}
                          className="w-full p-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
                          {t('Cluster')}
                        </label>
                        <input
                          type="text"
                          value={editedConfig.tts?.cluster || 'volc_ttos_samantha'}
                          onChange={e => handleConfigChange('tts', 'cluster', e.target.value)}
                          placeholder="volc_ttos_samantha"
                          className="w-full p-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100"
                        />
                      </div>
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
                          {t('Default Voice')}
                        </label>
                        <input
                          type="text"
                          value={editedConfig.tts?.default_voice || 'Cherry'}
                          onChange={e => handleConfigChange('tts', 'default_voice', e.target.value)}
                          className="w-full p-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
                          {t('Default Language')}
                        </label>
                        <input
                          type="text"
                          value={editedConfig.tts?.default_language || 'English'}
                          onChange={e =>
                            handleConfigChange('tts', 'default_language', e.target.value)
                          }
                          className="w-full p-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100"
                        />
                      </div>
                    </div>
                  )}
                </div>
              </section>
            </div>
          </div>
        )}

        {/* Environment Variables Tab */}
        {activeTab === 'environment' && envConfig && (
          <div className="space-y-4">
            {/* Environment Variables by Category - 2-column layout */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {envConfig.categories.map(category => {
                const categoryVars = envConfig.variables.filter(v => v.category === category.id)
                if (categoryVars.length === 0) return null

                return (
                  <section
                    key={category.id}
                    className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden"
                  >
                    <div className="px-4 py-2.5 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex items-center gap-2">
                      <div className="text-blue-500 dark:text-blue-400">
                        {getCategoryIcon(category.icon)}
                      </div>
                      <div>
                        <h2 className="font-semibold text-sm text-slate-900 dark:text-slate-100">
                          {category.name}
                        </h2>
                        <p className="text-[10px] text-slate-500 dark:text-slate-400">
                          {category.description}
                        </p>
                      </div>
                    </div>

                    <div className="p-4 space-y-3">
                      {categoryVars.map(envVar => (
                        <div key={envVar.key} className="space-y-1">
                          <div className="flex items-center justify-between">
                            <label className="text-xs font-medium text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
                              <code className="bg-slate-100 dark:bg-slate-700 px-1.5 py-0.5 rounded text-slate-800 dark:text-slate-200 text-[10px]">
                                {envVar.key}
                              </code>
                              {envVar.required && (
                                <span className="text-red-500 text-[9px] font-semibold">
                                  REQUIRED
                                </span>
                              )}
                              {envVar.is_set && <CheckCircle className="w-3 h-3 text-green-500" />}
                            </label>
                            {envVar.sensitive && (
                              <button
                                onClick={() => toggleSensitiveVisibility(envVar.key)}
                                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 p-0.5"
                              >
                                {showSensitive[envVar.key] ? (
                                  <EyeOff className="w-3.5 h-3.5" />
                                ) : (
                                  <Eye className="w-3.5 h-3.5" />
                                )}
                              </button>
                            )}
                          </div>
                          <p className="text-[10px] text-slate-500 dark:text-slate-400 line-clamp-1">
                            {envVar.description}
                          </p>
                          <input
                            type={
                              envVar.sensitive && !showSensitive[envVar.key] ? 'password' : 'text'
                            }
                            value={editedEnvVars[envVar.key] || ''}
                            onChange={e => handleEnvVarChange(envVar.key, e.target.value)}
                            placeholder={envVar.default || `Enter ${envVar.key}`}
                            className="w-full p-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-xs text-slate-900 dark:text-slate-100 font-mono placeholder:text-slate-300 dark:placeholder:text-slate-500 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
                          />
                        </div>
                      ))}
                    </div>
                  </section>
                )
              })}
            </div>

            {/* Save Environment Variables */}
            <div className="pt-2 pb-4">
              {envError && (
                <div className="mb-3 p-2.5 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg flex items-center gap-2 text-red-700 dark:text-red-400 text-xs">
                  <AlertCircle className="w-4 h-4" />
                  <span>{envError}</span>
                </div>
              )}
              <button
                onClick={handleEnvSave}
                disabled={envSaving}
                className={`w-full py-3 rounded-xl font-bold text-base flex items-center justify-center gap-2 transition-all ${
                  envSaving
                    ? 'bg-slate-100 dark:bg-slate-700 text-slate-400 dark:text-slate-500'
                    : envSaveSuccess
                      ? 'bg-green-500 text-white shadow-lg shadow-green-500/30'
                      : 'bg-gradient-to-r from-amber-500 to-orange-500 text-white hover:shadow-lg hover:shadow-orange-500/30 hover:-translate-y-0.5'
                }`}
              >
                {envSaving ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : envSaveSuccess ? (
                  <Check className="w-5 h-5" />
                ) : (
                  <Key className="w-5 h-5" />
                )}
                {envSaveSuccess ? t('Environment Updated!') : t('Apply Environment Changes')}
              </button>
            </div>
          </div>
        )}

        {/* LLM Providers Tab */}
        {activeTab === 'local_models' && (
          <div className="space-y-4">
            {/* LLM Mode Status Banner */}
            {llmModeInfo && (
              <div
                className={`p-4 rounded-xl border ${
                  llmModeInfo.mode === 'hybrid'
                    ? 'bg-purple-50 dark:bg-purple-900/20 border-purple-200 dark:border-purple-800'
                    : llmModeInfo.mode === 'api'
                      ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800'
                      : 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div
                      className={`p-2 rounded-lg ${
                        llmModeInfo.mode === 'hybrid'
                          ? 'bg-purple-100 dark:bg-purple-800/30'
                          : llmModeInfo.mode === 'api'
                            ? 'bg-blue-100 dark:bg-blue-800/30'
                            : 'bg-emerald-100 dark:bg-emerald-800/30'
                      }`}
                    >
                      <Cpu
                        className={`w-5 h-5 ${
                          llmModeInfo.mode === 'hybrid'
                            ? 'text-purple-600 dark:text-purple-400'
                            : llmModeInfo.mode === 'api'
                              ? 'text-blue-600 dark:text-blue-400'
                              : 'text-emerald-600 dark:text-emerald-400'
                        }`}
                      />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                          {t('LLM Mode')}: <span className="uppercase">{llmModeInfo.mode}</span>
                        </h3>
                        <span
                          className={`px-2 py-0.5 text-[10px] rounded-full font-medium ${
                            llmModeInfo.effective_source === 'provider'
                              ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300'
                              : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400'
                          }`}
                        >
                          {llmModeInfo.effective_source === 'provider'
                            ? t('Using Provider')
                            : t('Using ENV')}
                        </span>
                      </div>
                      <p className="text-xs text-slate-600 dark:text-slate-400 mt-0.5">
                        {llmModeInfo.mode === 'hybrid'
                          ? t(
                              'Both API and Local providers available. Active provider takes priority.'
                            )
                          : llmModeInfo.mode === 'api'
                            ? t('Only API (cloud) providers are used.')
                            : t('Only Local (self-hosted) providers are used.')}
                      </p>
                    </div>
                  </div>
                  {llmModeInfo.active_provider && (
                    <div className="text-right">
                      <p className="text-[10px] text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                        {t('Active')}
                      </p>
                      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        {llmModeInfo.active_provider.name}
                      </p>
                      <p className="text-xs text-slate-500 dark:text-slate-400 font-mono">
                        {llmModeInfo.active_provider.model}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Header & Add Button */}
            <div className="flex justify-between items-center bg-white dark:bg-slate-800 px-4 py-3 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700">
              <div>
                <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {t('LLM Providers')}
                </h2>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {t(
                    'Manage both API and Local LLM providers. Set LLM_MODE in Environment Variables to control which type is used.'
                  )}
                </p>
              </div>
              <button
                onClick={() => {
                  const defaultPreset = PROVIDER_PRESETS[0]
                  setEditingProvider({
                    name: '',
                    binding: defaultPreset.binding,
                    base_url: defaultPreset.base_url || '',
                    api_key: '',
                    model: defaultPreset.default_model,
                    is_active: false,
                    provider_type: 'local',
                    requires_key: defaultPreset.requires_key,
                  })
                  setOriginalProviderName(null)
                  setSelectedPresetId(defaultPreset.id)
                  setFetchedModels([])
                  setShowProviderForm(true)
                  setTestProviderResult(null)
                }}
                className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg flex items-center gap-1.5 text-xs font-medium transition-colors"
              >
                <Server className="w-3.5 h-3.5" />
                {t('Add Provider')}
              </button>
            </div>

            {/* Provider Type Filter */}
            <div className="flex items-center gap-2 bg-white dark:bg-slate-800 px-4 py-2 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700">
              <span className="text-xs text-slate-500 dark:text-slate-400">{t('Filter')}:</span>
              <div className="flex bg-slate-100 dark:bg-slate-700 p-0.5 rounded-lg">
                {(['all', 'api', 'local'] as const).map(filter => (
                  <button
                    key={filter}
                    onClick={() => setProviderTypeFilter(filter)}
                    className={`px-3 py-1 rounded-md text-xs font-medium transition-all ${
                      providerTypeFilter === filter
                        ? 'bg-white dark:bg-slate-600 text-blue-600 dark:text-blue-400 shadow-sm'
                        : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
                    }`}
                  >
                    {filter === 'all' ? t('All') : filter === 'api' ? t('API (Cloud)') : t('Local')}
                  </button>
                ))}
              </div>
            </div>

            {/* Provider List */}
            {loadingProviders ? (
              <div className="flex justify-center p-6">
                <Loader2 className="w-6 h-6 animate-spin text-emerald-500" />
              </div>
            ) : providers.filter(
                p => providerTypeFilter === 'all' || p.provider_type === providerTypeFilter
              ).length === 0 ? (
              <div className="text-center p-8 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-dashed border-slate-300 dark:border-slate-700">
                <Server className="w-10 h-10 text-slate-300 dark:text-slate-600 mx-auto mb-2" />
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  {providerTypeFilter === 'all'
                    ? t('No providers configured yet.')
                    : providerTypeFilter === 'api'
                      ? t('No API providers configured.')
                      : t('No local providers configured.')}
                </p>
                <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
                  {t('Add providers to manage your LLM configurations.')}
                </p>
              </div>
            ) : (
              <div className="grid gap-3">
                {providers
                  .filter(
                    p => providerTypeFilter === 'all' || p.provider_type === providerTypeFilter
                  )
                  .map(provider => (
                    <div
                      key={provider.name}
                      className={`bg-white dark:bg-slate-800 px-4 py-3 rounded-xl shadow-sm border transition-all ${provider.is_active ? 'border-blue-500 ring-1 ring-blue-500/20' : 'border-slate-200 dark:border-slate-700'}`}
                    >
                      <div className="flex justify-between items-center">
                        <div className="flex items-center gap-3 min-w-0 flex-1">
                          <div
                            className={`p-2 rounded-lg flex-shrink-0 ${provider.is_active ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400' : 'bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400'}`}
                          >
                            <Server className="w-4 h-4" />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 flex-wrap">
                              <h3 className="font-semibold text-slate-900 dark:text-slate-100 text-sm">
                                {provider.name}
                              </h3>
                              {provider.is_active && (
                                <span className="px-1.5 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 text-[10px] rounded font-medium">
                                  {t('Active')}
                                </span>
                              )}
                              <span
                                className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                                  provider.provider_type === 'api'
                                    ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400'
                                    : 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400'
                                }`}
                              >
                                {provider.provider_type === 'api'
                                  ? `☁️ ${t('API')}`
                                  : `🏠 ${t('Local')}`}
                              </span>
                              <span className="text-[10px] bg-slate-100 dark:bg-slate-700 px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-600 uppercase tracking-wider font-semibold text-slate-500">
                                {provider.binding}
                              </span>
                            </div>
                            <div className="flex items-center gap-2 mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                              <span className="font-medium text-slate-600 dark:text-slate-300">
                                {provider.model}
                              </span>
                              <span className="text-slate-300 dark:text-slate-600">•</span>
                              <span className="font-mono truncate text-[10px]">
                                {provider.base_url}
                              </span>
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-1 flex-shrink-0 ml-2">
                          {!provider.is_active && (
                            <button
                              onClick={() => handleActivateProvider(provider.name)}
                              className="p-1.5 text-slate-400 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-md transition-colors"
                              title={t('Set as Active')}
                            >
                              <CheckCircle className="w-4 h-4" />
                            </button>
                          )}
                          <button
                            onClick={() => handleTestProvider(provider)}
                            className="p-1.5 text-slate-400 hover:text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20 rounded-md transition-colors"
                            title={t('Test Connection')}
                          >
                            <RefreshCw className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => {
                              setEditingProvider({ ...provider })
                              setOriginalProviderName(provider.name)
                              const preset =
                                PROVIDER_PRESETS.find(
                                  p => p.base_url && provider.base_url.includes(p.base_url)
                                ) || PROVIDER_PRESETS.find(p => p.id === 'custom')
                              if (preset) setSelectedPresetId(preset.id)
                              setFetchedModels([])
                              setShowProviderForm(true)
                              setTestProviderResult(null)
                            }}
                            className="p-1.5 text-slate-400 hover:text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-900/20 rounded-md transition-colors"
                            title={t('Edit')}
                          >
                            <Sliders className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleDeleteProvider(provider.name)}
                            className="p-1.5 text-slate-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-md transition-colors"
                            title={t('Delete')}
                          >
                            <XCircle className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
              </div>
            )}

            {/* Edit/Add Form Modal */}
            {showProviderForm && editingProvider && (
              <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
                <div className="bg-white dark:bg-slate-800 rounded-xl shadow-xl w-full max-w-md overflow-hidden flex flex-col max-h-[85vh]">
                  <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 bg-emerald-50/50 dark:bg-emerald-900/20 flex justify-between items-center">
                    <h3 className="font-semibold text-sm text-slate-900 dark:text-slate-100 flex items-center gap-2">
                      <Server className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                      {editingProvider.name ? t('Edit Provider') : t('Add Provider')}
                    </h3>
                    <button
                      onClick={() => setShowProviderForm(false)}
                      className="text-slate-400 hover:text-slate-600 p-1"
                    >
                      <XCircle className="w-5 h-5" />
                    </button>
                  </div>
                  <div className="p-4 overflow-y-auto space-y-3">
                    {/* Provider Type Selection */}
                    <div>
                      <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                        {t('Provider Type')}
                      </label>
                      <div className="flex bg-slate-100 dark:bg-slate-700 p-0.5 rounded-lg">
                        <button
                          type="button"
                          onClick={() =>
                            setEditingProvider(prev =>
                              prev
                                ? {
                                    ...prev,
                                    provider_type: 'local',
                                    requires_key: false,
                                  }
                                : null
                            )
                          }
                          className={`flex-1 py-1.5 px-3 rounded-md text-xs font-medium flex items-center justify-center gap-1.5 transition-all ${
                            editingProvider.provider_type === 'local'
                              ? 'bg-white dark:bg-slate-600 text-emerald-600 dark:text-emerald-400 shadow-sm'
                              : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
                          }`}
                        >
                          🏠 {t('Local')}
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            setEditingProvider(prev =>
                              prev
                                ? {
                                    ...prev,
                                    provider_type: 'api',
                                    requires_key: true,
                                  }
                                : null
                            )
                          }
                          className={`flex-1 py-1.5 px-3 rounded-md text-xs font-medium flex items-center justify-center gap-1.5 transition-all ${
                            editingProvider.provider_type === 'api'
                              ? 'bg-white dark:bg-slate-600 text-blue-600 dark:text-blue-400 shadow-sm'
                              : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
                          }`}
                        >
                          ☁️ {t('API (Cloud)')}
                        </button>
                      </div>
                      <p className="mt-1 text-[10px] text-slate-500 dark:text-slate-400">
                        {editingProvider.provider_type === 'local'
                          ? t('Local servers (Ollama, LM Studio, vLLM) running on your machine.')
                          : t('Cloud API providers (OpenAI, Anthropic, DeepSeek, etc.).')}
                      </p>
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                        {t('Server Preset')}
                      </label>
                      <select
                        value={selectedPresetId}
                        onChange={e => {
                          const newId = e.target.value
                          setSelectedPresetId(newId)
                          const preset = PROVIDER_PRESETS.find(p => p.id === newId)
                          if (preset && editingProvider) {
                            setEditingProvider({
                              ...editingProvider,
                              binding: preset.binding,
                              base_url: preset.base_url || editingProvider.base_url,
                              model: preset.default_model || editingProvider.model,
                              requires_key: preset.requires_key,
                            })
                            setCustomModelInput(preset.models.length === 0)
                            setFetchedModels([])
                          }
                        }}
                        className="w-full p-2 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100 font-medium"
                      >
                        {PROVIDER_PRESETS.map(preset => (
                          <option key={preset.id} value={preset.id}>
                            {preset.name}
                          </option>
                        ))}
                      </select>
                      {PROVIDER_PRESETS.find(p => p.id === selectedPresetId)?.help_text && (
                        <p className="mt-1 text-[10px] text-slate-500 dark:text-slate-400">
                          {PROVIDER_PRESETS.find(p => p.id === selectedPresetId)?.help_text}
                        </p>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                          {t('Name')}
                        </label>
                        <input
                          type="text"
                          value={editingProvider.name}
                          onChange={e =>
                            setEditingProvider(prev =>
                              prev ? { ...prev, name: e.target.value } : null
                            )
                          }
                          disabled={
                            !!providers.find(p => p.name === editingProvider.name && p.name !== '')
                          }
                          placeholder={t('My Provider')}
                          className="w-full p-2 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                          {t('Binding')}
                        </label>
                        <input
                          type="text"
                          value={editingProvider.binding}
                          disabled
                          className="w-full p-2 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm text-slate-500"
                        />
                      </div>
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                        {t('Base URL')}
                      </label>
                      <input
                        type="text"
                        value={editingProvider.base_url}
                        onChange={e =>
                          setEditingProvider(prev =>
                            prev ? { ...prev, base_url: e.target.value } : null
                          )
                        }
                        placeholder={
                          selectedPresetId === 'lmstudio'
                            ? 'http://127.0.0.1:1234'
                            : selectedPresetId === 'ollama'
                              ? 'http://localhost:11434/v1'
                              : 'http://localhost:8080/v1'
                        }
                        className={`w-full p-2 bg-slate-50 dark:bg-slate-700 border rounded-lg font-mono text-xs ${
                          editingProvider.base_url.includes('/chat/completions') ||
                          editingProvider.base_url.includes('/models/')
                            ? 'border-red-400 dark:border-red-500 ring-1 ring-red-400/30'
                            : 'border-slate-200 dark:border-slate-600'
                        }`}
                      />
                      {/* Base URL validation warning */}
                      {(editingProvider.base_url.includes('/chat/completions') ||
                        editingProvider.base_url.includes('/models/')) && (
                        <div className="mt-1.5 p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
                          <p className="text-[11px] text-red-600 dark:text-red-400 font-medium flex items-center gap-1">
                            <AlertCircle className="w-3 h-3" />
                            {t('Invalid URL format detected')}
                          </p>
                          <p className="text-[10px] text-red-500 dark:text-red-400/80 mt-0.5">
                            {t(
                              "Base URL should NOT include '/chat/completions' or '/models/'. The system will append these automatically."
                            )}
                          </p>
                          <p className="text-[10px] text-red-500 dark:text-red-400/80 mt-0.5">
                            {t('Example')}:{' '}
                            <code className="bg-red-100 dark:bg-red-800/30 px-1 rounded">
                              http://127.0.0.1:1234
                            </code>{' '}
                            {t('or')}{' '}
                            <code className="bg-red-100 dark:bg-red-800/30 px-1 rounded">
                              http://127.0.0.1:1234/v1
                            </code>
                          </p>
                        </div>
                      )}
                      {/* Normal help text */}
                      {!editingProvider.base_url.includes('/chat/completions') &&
                        !editingProvider.base_url.includes('/models/') && (
                          <p className="mt-1 text-[10px] text-slate-500 dark:text-slate-400">
                            {t(
                              "Only enter the base URL. '/chat/completions' will be appended automatically."
                            )}
                          </p>
                        )}
                    </div>

                    {PROVIDER_PRESETS.find(p => p.id === selectedPresetId)?.requires_key && (
                      <div>
                        <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                          {t('API Key')}{' '}
                          <span className="text-slate-400">({t('optional for local')})</span>
                        </label>
                        <input
                          type="password"
                          value={editingProvider.api_key}
                          onChange={e =>
                            setEditingProvider(prev =>
                              prev ? { ...prev, api_key: e.target.value } : null
                            )
                          }
                          placeholder={t('Usually not required for local servers')}
                          className="w-full p-2 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg font-mono text-xs"
                        />
                      </div>
                    )}

                    <div>
                      <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1 flex justify-between">
                        <span>{t('Model')}</span>
                        {(PROVIDER_PRESETS.find(p => p.id === selectedPresetId)?.models?.length ??
                          0) > 0 && (
                          <button
                            onClick={() => setCustomModelInput(!customModelInput)}
                            className="text-[10px] text-blue-600 hover:underline"
                          >
                            {customModelInput ? t('Select from list') : t('Enter custom')}
                          </button>
                        )}
                      </label>
                      <div className="flex gap-2">
                        {!customModelInput &&
                        (fetchedModels.length > 0 ||
                          (PROVIDER_PRESETS.find(p => p.id === selectedPresetId)?.models?.length ??
                            0) > 0) ? (
                          <div className="relative flex-1">
                            <select
                              value={editingProvider.model}
                              onChange={e =>
                                setEditingProvider(prev =>
                                  prev ? { ...prev, model: e.target.value } : null
                                )
                              }
                              className="w-full p-2 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm appearance-none"
                            >
                              {fetchedModels.length > 0 ? (
                                <>
                                  <option value="" disabled>
                                    {t('Select a fetched model')}
                                  </option>
                                  {fetchedModels.map(m => (
                                    <option key={m} value={m}>
                                      {m}
                                    </option>
                                  ))}
                                </>
                              ) : (
                                PROVIDER_PRESETS.find(p => p.id === selectedPresetId)?.models.map(
                                  m => (
                                    <option key={m} value={m}>
                                      {m}
                                    </option>
                                  )
                                )
                              )}
                            </select>
                            <div className="absolute inset-y-0 right-0 flex items-center px-2 pointer-events-none text-slate-500">
                              <svg
                                className="w-3.5 h-3.5"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                              >
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth="2"
                                  d="M19 9l-7 7-7-7"
                                ></path>
                              </svg>
                            </div>
                          </div>
                        ) : (
                          <input
                            type="text"
                            value={editingProvider.model}
                            onChange={e =>
                              setEditingProvider(prev =>
                                prev ? { ...prev, model: e.target.value } : null
                              )
                            }
                            placeholder="gpt-4o-mini"
                            className="flex-1 p-2 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm"
                          />
                        )}
                        <button
                          type="button"
                          onClick={fetchModels}
                          disabled={fetchingModels || !editingProvider.base_url}
                          className="p-2 bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors disabled:opacity-50"
                          title={t('Refresh Models from API')}
                        >
                          {fetchingModels ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            <RotateCcw className="w-4 h-4" />
                          )}
                        </button>
                      </div>
                    </div>
                    <div className="flex items-center justify-between pt-1">
                      <button
                        type="button"
                        onClick={() => handleTestProvider(editingProvider)}
                        disabled={testingProvider}
                        className="text-xs text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
                      >
                        {testingProvider ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <RefreshCw className="w-3 h-3" />
                        )}
                        {t('Test Connection')}
                      </button>
                      {testProviderResult && (
                        <span
                          className={`text-[10px] px-2 py-0.5 rounded ${testProviderResult.success ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300' : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'}`}
                        >
                          {testProviderResult.success
                            ? t('Success!')
                            : `${t('Failed')}: ${testProviderResult.message}`}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="px-4 py-3 border-t border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex flex-col gap-2">
                    {providerError && (
                      <div className="p-2 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg text-red-600 dark:text-red-400 text-xs">
                        {providerError}
                      </div>
                    )}
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => setShowProviderForm(false)}
                        className="px-3 py-1.5 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg font-medium"
                      >
                        {t('Cancel')}
                      </button>
                      <button
                        onClick={() => handleProviderSave(editingProvider)}
                        disabled={savingProvider}
                        className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-medium shadow-sm disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
                      >
                        {savingProvider && <Loader2 className="w-3 h-3 animate-spin" />}
                        {savingProvider ? t('Saving...') : t('Save Server')}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
