'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  Database,
  Download,
  Eye,
  FileText,
  FolderOpen,
  Layers3,
  ListTree,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Plus,
  RefreshCcw,
  ScrollText,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import RichMarkdownRenderer from '@/components/common/RichMarkdownRenderer'
import Button from '@/components/ui/Button'
import { apiUrl } from '@/lib/api'
import {
  createStructureNoteJob,
  createStructureNoteJobFromKnowledgeBase,
  createStructureNoteProject,
  deleteStructureNoteProject,
  fetchStructureNoteMarkdown,
  getStructureNoteJob,
  invalidateStructureNoteCaches,
  listStructureNoteJobs,
  listStructureNoteKnowledgeBaseFiles,
  listStructureNoteProjects,
  renameStructureNoteProject,
  retryStructureNoteJob,
  type StructureNoteDifficulty,
  type StructureNoteJob,
  type StructureNoteKbFile,
  type StructureNoteKbGroup,
  type StructureNoteLanguage,
  type StructureNoteProject,
  type StructureNoteStatus,
  type StructureNoteStyleLevel,
} from '@/lib/structure-note-api'

type SourceMode = 'upload' | 'knowledge_base'

interface MaterialNode {
  key: string
  fileName: string
  sourceKind: 'upload' | 'knowledge_base'
  updatedAt: string
}

interface VersionNode {
  label: string
  job: StructureNoteJob
  isLatest: boolean
}

interface NoteNode {
  key: string
  title: string
  sourceFileName: string
  latestJob: StructureNoteJob
  versions: VersionNode[]
}

interface ProjectNode {
  key: string
  name: string
  materials: MaterialNode[]
  notes: NoteNode[]
}

type MaterialMap = Map<string, MaterialNode>
type NoteJobMap = Map<string, StructureNoteJob[]>

interface ProjectAccumulator {
  name: string
  materials: MaterialMap
  notes: NoteJobMap
}

const PROCESSING_STATUS_ORDER: StructureNoteStatus[] = [
  'queued',
  'normalizing',
  'indexing',
  'planning',
  'generating',
  'processing_images',
  'rendering',
]

const PROCESSING_STATUSES = new Set<StructureNoteStatus>(PROCESSING_STATUS_ORDER)

const DIFFICULTY_OPTIONS: Array<{
  value: StructureNoteDifficulty
  labelKey: string
  hintKey: string
}> = [
  {
    value: 'simple',
    labelKey: 'Simple',
    hintKey: 'Shorter notes focused on key definitions and outcomes.',
  },
  {
    value: 'medium',
    labelKey: 'Medium',
    hintKey: 'Balanced classroom-style coverage with core logic.',
  },
  {
    value: 'detailed',
    labelKey: 'Detailed',
    hintKey: 'Longer notes with deeper reasoning and slower generation.',
  },
]

const NOTE_LANGUAGE_OPTIONS: Array<{
  value: StructureNoteLanguage
  labelKey: string
  hintKey: string
}> = [
  {
    value: 'zh',
    labelKey: 'Chinese',
    hintKey: 'Generate the final note content in Chinese.',
  },
  {
    value: 'en',
    labelKey: 'English',
    hintKey: 'Generate the final note content in English.',
  },
]

const STYLE_LEVEL_OPTIONS: Array<{
  value: StructureNoteStyleLevel
  labelKey: string
  hintKey: string
}> = [
  {
    value: 'low',
    labelKey: 'Low',
    hintKey: 'Popular-science style for fast entry-level understanding.',
  },
  {
    value: 'medium',
    labelKey: 'Medium',
    hintKey: 'Standard classroom note style with balanced clarity and detail.',
  },
  {
    value: 'high',
    labelKey: 'High',
    hintKey:
      'Academic style with more rigorous principles, formulas, and derivations when supported.',
  },
]

const STATUS_LABELS: Record<StructureNoteStatus, string> = {
  queued: 'Queued',
  normalizing: 'Normalizing source',
  indexing: 'Building page index',
  planning: 'Planning sections',
  generating: 'Generating notes',
  processing_images: 'Processing figures',
  rendering: 'Rendering PDF',
  ready: 'Ready',
  failed: 'Failed',
}

function formatTimestamp(value: string) {
  if (!value) return ''
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    }).format(new Date(value))
  } catch {
    return value
  }
}

function formatFileSize(sizeBytes: number) {
  if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) return ''
  if (sizeBytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(sizeBytes / 1024))} KB`
  }
  return `${(sizeBytes / 1024 / 1024).toFixed(1)} MB`
}

function formatPageRange(pageStart: number, pageEnd: number) {
  return pageStart === pageEnd ? `p. ${pageStart}` : `pp. ${pageStart}-${pageEnd}`
}

function stripExtension(fileName: string) {
  return fileName.replace(/\.[^/.]+$/, '') || fileName
}

function getProjectInitials(name: string) {
  const compact = name.trim()
  if (!compact) return 'SN'
  return compact.slice(0, 2).toUpperCase()
}

function getProjectName(job: StructureNoteJob) {
  return job.project_name || job.source_ref?.kb_name || 'Local Uploads'
}

function getSourceKind(job: StructureNoteJob): 'upload' | 'knowledge_base' {
  return job.source_kind === 'knowledge_base' ? 'knowledge_base' : 'upload'
}

function getSourceFileName(job: StructureNoteJob) {
  return job.source_ref?.file_name || job.file_name
}

function getSourceFileId(job: StructureNoteJob) {
  if (getSourceKind(job) === 'knowledge_base') {
    return `${job.source_ref?.kb_name || getProjectName(job)}/${job.source_ref?.file_id || job.file_name}`
  }
  return job.source_ref?.file_name || job.file_name
}

function getMaterialKey(job: StructureNoteJob) {
  return `${getSourceKind(job)}:${getProjectName(job)}:${getSourceFileId(job)}`
}

function getNoteTitle(job: StructureNoteJob) {
  return job.note_title || stripExtension(getSourceFileName(job))
}

function getStatusProgress(status: StructureNoteStatus) {
  if (status === 'ready' || status === 'failed') return 100
  const index = PROCESSING_STATUS_ORDER.indexOf(status)
  if (index < 0) return 8
  return Math.max(10, Math.round(((index + 1) / PROCESSING_STATUS_ORDER.length) * 92))
}

function buildProjectTree(
  jobs: StructureNoteJob[],
  projectRecords: StructureNoteProject[]
): ProjectNode[] {
  const projectMap = new Map<string, ProjectAccumulator>()

  projectRecords.forEach(project => {
    const projectName = project.name.trim()
    if (!projectName) return
    projectMap.set(projectName, {
      name: projectName,
      materials: new Map<string, MaterialNode>(),
      notes: new Map<string, StructureNoteJob[]>(),
    })
  })

  jobs.forEach(job => {
    const projectName = getProjectName(job)
    const projectKey = projectName
    const project = projectMap.get(projectKey) ?? {
      name: projectName,
      materials: new Map<string, MaterialNode>(),
      notes: new Map<string, StructureNoteJob[]>(),
    }
    const materialKey = getMaterialKey(job)
    const existingMaterial = project.materials.get(materialKey)
    if (!existingMaterial || job.updated_at > existingMaterial.updatedAt) {
      project.materials.set(materialKey, {
        key: materialKey,
        fileName: getSourceFileName(job),
        sourceKind: getSourceKind(job),
        updatedAt: job.updated_at,
      })
    }
    project.notes.set(materialKey, [...(project.notes.get(materialKey) ?? []), job])
    projectMap.set(projectKey, project)
  })

  return Array.from(projectMap.entries())
    .map(([projectKey, project]) => {
      const notes = Array.from(project.notes.entries())
        .map(([noteKey, noteJobs]) => {
          const sortedVersions = [...noteJobs].sort((a, b) =>
            a.created_at.localeCompare(b.created_at)
          )
          const latestJob = sortedVersions[sortedVersions.length - 1]
          return {
            key: noteKey,
            title: getNoteTitle(latestJob),
            sourceFileName: getSourceFileName(latestJob),
            latestJob,
            versions: sortedVersions.map((job, index) => ({
              label: `v${index + 1}`,
              job,
              isLatest: index === sortedVersions.length - 1,
            })),
          }
        })
        .sort((a, b) => b.latestJob.updated_at.localeCompare(a.latestJob.updated_at))

      return {
        key: projectKey,
        name: project.name,
        materials: Array.from(project.materials.values()).sort((a, b) =>
          a.fileName.localeCompare(b.fileName)
        ),
        notes,
      }
    })
    .sort((a, b) => a.name.localeCompare(b.name))
}

function rewriteRelativeMarkdownAssets(content: string, assetBaseUrl: string | null) {
  if (!assetBaseUrl) return content
  const base = apiUrl(assetBaseUrl).replace(/\/$/, '')
  return content.replace(
    /(!\[[^\]]*\]\()((?!https?:\/\/|data:|\/|#)[^)]+)(\))/gi,
    (_match, prefix, src, suffix) => {
      const normalizedSrc = String(src).replace(/^\.\//, '')
      return `${prefix}${base}/${normalizedSrc}${suffix}`
    }
  )
}

function scrollToSection(sectionId: string) {
  const target = document.getElementById(sectionId)
  target?.scrollIntoView({ block: 'start', behavior: 'smooth' })
}

function StatusIcon({ status }: { status: StructureNoteStatus }) {
  if (status === 'ready') {
    return <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-hidden="true" />
  }
  if (status === 'failed') {
    return <AlertCircle className="h-4 w-4 text-rose-600" aria-hidden="true" />
  }
  if (PROCESSING_STATUSES.has(status)) {
    return <Clock3 className="h-4 w-4 text-[var(--muted-foreground)]" aria-hidden="true" />
  }
  return <Clock3 className="h-4 w-4 text-[var(--muted-foreground)]" aria-hidden="true" />
}

export default function StructureNotePage() {
  const { t, i18n } = useTranslation()
  const [jobs, setJobs] = useState<StructureNoteJob[]>([])
  const [projects, setProjects] = useState<StructureNoteProject[]>([])
  const [kbGroups, setKbGroups] = useState<StructureNoteKbGroup[]>([])
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const selectedJobIdRef = useRef<string | null>(null)
  const [selectedJob, setSelectedJob] = useState<StructureNoteJob | null>(null)
  const [sourceMode, setSourceMode] = useState<SourceMode>('upload')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [selectedKbName, setSelectedKbName] = useState('')
  const [selectedKbFileId, setSelectedKbFileId] = useState('')
  const [targetProjectName, setTargetProjectName] = useState('')
  const [difficulty, setDifficulty] = useState<StructureNoteDifficulty>('medium')
  const [noteLanguage, setNoteLanguage] = useState<StructureNoteLanguage>(() =>
    i18n.language?.toLowerCase().startsWith('zh') ? 'zh' : 'en'
  )
  const [styleLevel, setStyleLevel] = useState<StructureNoteStyleLevel>('medium')
  const [logs, setLogs] = useState<string[]>([])
  const [markdownText, setMarkdownText] = useState('')
  const [markdownLoading, setMarkdownLoading] = useState(false)
  const [markdownError, setMarkdownError] = useState<string | null>(null)
  const [editingMarkdown, setEditingMarkdown] = useState(false)
  const [loadingJobs, setLoadingJobs] = useState(true)
  const [loadingKbFiles, setLoadingKbFiles] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [pageError, setPageError] = useState<string | null>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [expandedProjectKeys, setExpandedProjectKeys] = useState<Set<string>>(new Set())
  const [expandedMaterialsKeys, setExpandedMaterialsKeys] = useState<Set<string>>(new Set())
  const [expandedNoteKeys, setExpandedNoteKeys] = useState<Set<string>>(new Set())
  const seenProjectKeysRef = useRef<Set<string>>(new Set())
  const [creatingProject, setCreatingProject] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [renamingProjectName, setRenamingProjectName] = useState<string | null>(null)
  const [projectNameDraft, setProjectNameDraft] = useState('')
  const [projectBusyName, setProjectBusyName] = useState<string | null>(null)

  useEffect(() => {
    selectedJobIdRef.current = selectedJobId
  }, [selectedJobId])

  const projectTree = useMemo(() => buildProjectTree(jobs, projects), [jobs, projects])

  const selectedTreeContext = useMemo(() => {
    if (!selectedJobId) return null
    for (const project of projectTree) {
      for (const note of project.notes) {
        for (const version of note.versions) {
          if (version.job.job_id === selectedJobId) {
            return {
              projectKey: project.key,
              projectName: project.name,
              noteKey: note.key,
              noteTitle: note.title,
              versionLabel: version.label,
              isLatest: version.isLatest,
            }
          }
        }
      }
    }
    return null
  }, [projectTree, selectedJobId])

  const selectedKbGroup = useMemo(
    () => kbGroups.find(group => group.kb_name === selectedKbName) ?? null,
    [kbGroups, selectedKbName]
  )

  const selectedKbFile = useMemo<StructureNoteKbFile | null>(
    () => selectedKbGroup?.files.find(file => file.file_id === selectedKbFileId) ?? null,
    [selectedKbFileId, selectedKbGroup]
  )

  const selectedPdfUrl = useMemo(() => {
    if (!selectedJob?.final_pdf_url) return null
    return apiUrl(selectedJob.final_pdf_url)
  }, [selectedJob])

  const selectedMarkdownUrl = useMemo(() => {
    if (!selectedJob?.rendered_markdown_url) return null
    return apiUrl(selectedJob.rendered_markdown_url)
  }, [selectedJob])

  const displayMarkdown = useMemo(
    () => rewriteRelativeMarkdownAssets(markdownText, selectedJob?.asset_base_url ?? null),
    [markdownText, selectedJob?.asset_base_url]
  )

  useEffect(() => {
    let active = true
    void (async () => {
      try {
        setLoadingJobs(true)
        const [nextProjects, nextJobs] = await Promise.all([
          listStructureNoteProjects({ force: true }),
          listStructureNoteJobs({ force: true }),
        ])
        if (!active) return
        setProjects(nextProjects)
        setJobs(nextJobs)
        const currentSelectedJobId = selectedJobIdRef.current
        const nextSelectedJobId =
          currentSelectedJobId && nextJobs.some(job => job.job_id === currentSelectedJobId)
            ? currentSelectedJobId
            : (nextJobs[0]?.job_id ?? null)
        setSelectedJobId(nextSelectedJobId)
        setSelectedJob(
          nextJobs.find(job => job.job_id === nextSelectedJobId) ?? nextJobs[0] ?? null
        )
      } catch (error) {
        if (!active) return
        setPageError(error instanceof Error ? error.message : t('Unknown error'))
      } finally {
        if (active) setLoadingJobs(false)
      }
    })()
    return () => {
      active = false
    }
  }, [t])

  useEffect(() => {
    let active = true
    void (async () => {
      try {
        setLoadingKbFiles(true)
        const nextGroups = await listStructureNoteKnowledgeBaseFiles({ force: true })
        if (!active) return
        setKbGroups(nextGroups)
      } catch (error) {
        if (!active) return
        setPageError(error instanceof Error ? error.message : t('Unknown error'))
      } finally {
        if (active) setLoadingKbFiles(false)
      }
    })()
    return () => {
      active = false
    }
  }, [t])

  useEffect(() => {
    if (kbGroups.length === 0) {
      setSelectedKbName('')
      setSelectedKbFileId('')
      return
    }
    const firstSelectableGroup = kbGroups.find(group => group.files.length > 0) ?? kbGroups[0]
    setSelectedKbName(current =>
      current && kbGroups.some(group => group.kb_name === current)
        ? current
        : firstSelectableGroup.kb_name
    )
  }, [kbGroups])

  useEffect(() => {
    if (!selectedKbGroup) {
      setSelectedKbFileId('')
      return
    }
    setSelectedKbFileId(current =>
      current && selectedKbGroup.files.some(file => file.file_id === current)
        ? current
        : (selectedKbGroup.files[0]?.file_id ?? '')
    )
  }, [selectedKbGroup])

  useEffect(() => {
    if (!selectedTreeContext) return
    setExpandedProjectKeys(current => new Set(current).add(selectedTreeContext.projectKey))
    setExpandedNoteKeys(current => new Set(current).add(selectedTreeContext.noteKey))
  }, [selectedTreeContext])

  useEffect(() => {
    setExpandedMaterialsKeys(current => {
      const next = new Set(current)
      const seen = seenProjectKeysRef.current
      projectTree.forEach(project => {
        if (seen.has(project.key)) return
        seen.add(project.key)
        next.add(project.key)
      })
      return next
    })
  }, [projectTree])

  useEffect(() => {
    if (targetProjectName && projectTree.some(project => project.name === targetProjectName)) {
      return
    }
    if (selectedTreeContext?.projectName) {
      setTargetProjectName(selectedTreeContext.projectName)
      return
    }
    setTargetProjectName(projectTree[0]?.name ?? '')
  }, [projectTree, selectedTreeContext?.projectName, targetProjectName])

  useEffect(() => {
    if (!selectedJobId) return
    let active = true
    void (async () => {
      try {
        const job = await getStructureNoteJob(selectedJobId)
        if (!active) return
        setSelectedJob(job)
        setJobs(prev => {
          const others = prev.filter(item => item.job_id !== job.job_id)
          return [job, ...others].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
        })
      } catch (error) {
        if (!active) return
        setPageError(error instanceof Error ? error.message : t('Unknown error'))
      }
    })()
    return () => {
      active = false
    }
  }, [selectedJobId, t])

  useEffect(() => {
    if (!selectedJob?.rendered_markdown_url) {
      setMarkdownText('')
      setMarkdownError(null)
      setEditingMarkdown(false)
      return
    }

    let active = true
    void (async () => {
      try {
        setMarkdownLoading(true)
        setMarkdownError(null)
        const content = await fetchStructureNoteMarkdown(selectedJob.rendered_markdown_url!)
        if (!active) return
        setMarkdownText(content)
        setEditingMarkdown(false)
      } catch (error) {
        if (!active) return
        setMarkdownError(error instanceof Error ? error.message : t('Unknown error'))
      } finally {
        if (active) setMarkdownLoading(false)
      }
    })()

    return () => {
      active = false
    }
  }, [selectedJob?.rendered_markdown_url, t])

  useEffect(() => {
    if (!selectedJob || !selectedJob.task_id || !PROCESSING_STATUSES.has(selectedJob.status)) {
      return
    }

    const source = new EventSource(
      apiUrl(`/api/v1/structure-note/tasks/${selectedJob.task_id}/stream`)
    )
    source.addEventListener('log', event => {
      try {
        const payload = JSON.parse((event as MessageEvent).data) as { line?: string }
        if (!payload.line) return
        setLogs(prev => [...prev.slice(-19), payload.line!])
      } catch {}
    })

    const refreshSelected = async () => {
      try {
        const refreshed = await getStructureNoteJob(selectedJob.job_id)
        setSelectedJob(refreshed)
        setJobs(prev => {
          const others = prev.filter(item => item.job_id !== refreshed.job_id)
          return [refreshed, ...others].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
        })
        if (!PROCESSING_STATUSES.has(refreshed.status)) {
          invalidateStructureNoteCaches()
        }
      } catch {}
    }

    const interval = window.setInterval(() => {
      void refreshSelected()
    }, 2500)

    source.addEventListener('complete', () => {
      void refreshSelected()
      source.close()
    })
    source.addEventListener('failed', () => {
      void refreshSelected()
      source.close()
    })
    source.onerror = () => {
      source.close()
    }

    return () => {
      window.clearInterval(interval)
      source.close()
    }
  }, [selectedJob])

  const toggleProject = (projectKey: string) => {
    setExpandedProjectKeys(current => {
      const next = new Set(current)
      if (next.has(projectKey)) {
        next.delete(projectKey)
      } else {
        next.add(projectKey)
      }
      return next
    })
  }

  const toggleMaterials = (projectKey: string) => {
    setExpandedMaterialsKeys(current => {
      const next = new Set(current)
      if (next.has(projectKey)) {
        next.delete(projectKey)
      } else {
        next.add(projectKey)
      }
      return next
    })
  }

  const toggleNote = (noteKey: string) => {
    setExpandedNoteKeys(current => {
      const next = new Set(current)
      if (next.has(noteKey)) {
        next.delete(noteKey)
      } else {
        next.add(noteKey)
      }
      return next
    })
  }

  const selectJob = (job: StructureNoteJob) => {
    setSelectedJobId(job.job_id)
    setSelectedJob(job)
    setLogs([])
  }

  const refreshProjectState = async (preferredJobId?: string | null) => {
    const [nextProjects, nextJobs] = await Promise.all([
      listStructureNoteProjects({ force: true }),
      listStructureNoteJobs({ force: true }),
    ])
    setProjects(nextProjects)
    setJobs(nextJobs)
    const nextSelectedJobId =
      preferredJobId && nextJobs.some(job => job.job_id === preferredJobId)
        ? preferredJobId
        : (nextJobs[0]?.job_id ?? null)
    setSelectedJobId(nextSelectedJobId)
    setSelectedJob(nextJobs.find(job => job.job_id === nextSelectedJobId) ?? null)
    if (!nextSelectedJobId) {
      setMarkdownText('')
      setMarkdownError(null)
      setEditingMarkdown(false)
      setLogs([])
    }
    return { projects: nextProjects, jobs: nextJobs }
  }

  const handleCreateProject = async () => {
    const name = newProjectName.trim()
    if (!name) {
      setPageError(t('Enter a project name first.'))
      return
    }
    try {
      setProjectBusyName(name)
      setPageError(null)
      const project = await createStructureNoteProject(name)
      await refreshProjectState(selectedJobId)
      setExpandedProjectKeys(current => new Set(current).add(project.name))
      setExpandedMaterialsKeys(current => new Set(current).add(project.name))
      setTargetProjectName(project.name)
      setNewProjectName('')
      setCreatingProject(false)
    } catch (error) {
      setPageError(error instanceof Error ? error.message : t('Unknown error'))
    } finally {
      setProjectBusyName(null)
    }
  }

  const startRenameProject = (projectName: string) => {
    setRenamingProjectName(projectName)
    setProjectNameDraft(projectName)
  }

  const handleRenameProject = async (oldName: string) => {
    const newName = projectNameDraft.trim()
    if (!newName) {
      setPageError(t('Enter a project name first.'))
      return
    }
    try {
      setProjectBusyName(oldName)
      setPageError(null)
      const project = await renameStructureNoteProject(oldName, newName)
      await refreshProjectState(selectedJobId)
      setExpandedProjectKeys(current => {
        const next = new Set(current)
        if (next.delete(oldName)) next.add(project.name)
        return next
      })
      setExpandedMaterialsKeys(current => {
        const next = new Set(current)
        if (next.delete(oldName)) next.add(project.name)
        return next
      })
      setExpandedNoteKeys(current => {
        const next = new Set<string>()
        current.forEach(key => next.add(key.replace(`:${oldName}:`, `:${project.name}:`)))
        return next
      })
      if (targetProjectName === oldName) {
        setTargetProjectName(project.name)
      }
      setRenamingProjectName(null)
      setProjectNameDraft('')
    } catch (error) {
      setPageError(error instanceof Error ? error.message : t('Unknown error'))
    } finally {
      setProjectBusyName(null)
    }
  }

  const handleDeleteProject = async (projectName: string) => {
    const confirmed = window.confirm(
      t('Delete project "{{name}}" and all of its Structure Note versions?', { name: projectName })
    )
    if (!confirmed) return
    try {
      setProjectBusyName(projectName)
      setPageError(null)
      await deleteStructureNoteProject(projectName)
      await refreshProjectState(
        selectedTreeContext?.projectKey === projectName ? null : selectedJobId
      )
      setExpandedProjectKeys(current => {
        const next = new Set(current)
        next.delete(projectName)
        return next
      })
      setExpandedMaterialsKeys(current => {
        const next = new Set(current)
        next.delete(projectName)
        return next
      })
      if (targetProjectName === projectName) {
        setTargetProjectName('')
      }
      if (renamingProjectName === projectName) {
        setRenamingProjectName(null)
        setProjectNameDraft('')
      }
    } catch (error) {
      setPageError(error instanceof Error ? error.message : t('Unknown error'))
    } finally {
      setProjectBusyName(null)
    }
  }

  const handleCreate = async () => {
    if (sourceMode === 'upload' && !selectedFile) {
      setPageError(t('Select a PDF, PPT, or PPTX file first.'))
      return
    }
    if (sourceMode === 'knowledge_base' && (!selectedKbName || !selectedKbFileId)) {
      setPageError(t('Select a Knowledge Base file first.'))
      return
    }

    try {
      setSubmitting(true)
      setPageError(null)
      setLogs([])
      const effectiveProjectName = targetProjectName.trim() || null
      const job =
        sourceMode === 'knowledge_base'
          ? await createStructureNoteJobFromKnowledgeBase(
              selectedKbName,
              selectedKbFileId,
              difficulty,
              noteLanguage,
              styleLevel,
              effectiveProjectName
            )
          : await createStructureNoteJob(
              selectedFile!,
              difficulty,
              noteLanguage,
              styleLevel,
              effectiveProjectName
            )
      const nextProjects = await listStructureNoteProjects({ force: true })
      setProjects(nextProjects)
      setJobs(prev => [job, ...prev.filter(item => item.job_id !== job.job_id)])
      setSelectedJobId(job.job_id)
      setSelectedJob(job)
      setSelectedFile(null)
      setExpandedProjectKeys(current => new Set(current).add(getProjectName(job)))
      setExpandedMaterialsKeys(current => new Set(current).add(getProjectName(job)))
      setTargetProjectName(getProjectName(job))
    } catch (error) {
      setPageError(error instanceof Error ? error.message : t('Unknown error'))
    } finally {
      setSubmitting(false)
    }
  }

  const handleRetry = async () => {
    if (!selectedJob) return
    try {
      setRetrying(true)
      setPageError(null)
      setLogs([])
      const job = await retryStructureNoteJob(selectedJob.job_id)
      setSelectedJob(job)
      setSelectedJobId(job.job_id)
      setJobs(prev => [job, ...prev.filter(item => item.job_id !== job.job_id)])
    } catch (error) {
      setPageError(error instanceof Error ? error.message : t('Unknown error'))
    } finally {
      setRetrying(false)
    }
  }

  const createDisabled =
    submitting || (sourceMode === 'upload' ? !selectedFile : !selectedKbName || !selectedKbFileId)

  return (
    <div
      className={[
        'grid h-full min-h-0 grid-cols-1 gap-0',
        sidebarCollapsed
          ? 'lg:grid-cols-[72px_minmax(0,1fr)]'
          : 'lg:grid-cols-[340px_minmax(0,1fr)]',
      ].join(' ')}
    >
      <aside className="border-b border-[var(--border)] bg-[var(--secondary)]/35 lg:border-b-0 lg:border-r">
        <div className="flex h-full min-h-0 flex-col">
          <div className="border-b border-[var(--border)] px-3 py-4">
            <div className="flex items-start justify-between gap-2">
              {sidebarCollapsed ? (
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--background)] text-sm font-semibold text-[var(--foreground)]">
                  <BookOpen className="h-4 w-4" aria-hidden="true" />
                </div>
              ) : (
                <div className="min-w-0 px-2">
                  <h1 className="text-lg font-semibold text-[var(--foreground)] text-balance">
                    {t('Structure Note')}
                  </h1>
                  <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                    {t('Manage materials and generated notes by project.')}
                  </p>
                </div>
              )}
              <button
                type="button"
                onClick={() => setSidebarCollapsed(value => !value)}
                className="rounded-lg p-2 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                aria-label={sidebarCollapsed ? t('Expand sidebar') : t('Collapse sidebar')}
                title={sidebarCollapsed ? t('Expand sidebar') : t('Collapse sidebar')}
              >
                {sidebarCollapsed ? (
                  <PanelLeftOpen className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <PanelLeftClose className="h-4 w-4" aria-hidden="true" />
                )}
              </button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
            {sidebarCollapsed ? (
              <nav aria-label={t('Projects')} className="space-y-2">
                {loadingJobs ? (
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg text-[var(--muted-foreground)]">
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  </div>
                ) : projectTree.length === 0 ? (
                  <div
                    className="flex h-10 w-10 items-center justify-center rounded-lg border border-dashed border-[var(--border)] text-xs text-[var(--muted-foreground)]"
                    title={t('No projects yet. Upload or select a Knowledge Base file to start.')}
                  >
                    0
                  </div>
                ) : (
                  projectTree.map(project => {
                    const active = selectedTreeContext?.projectKey === project.key
                    return (
                      <button
                        key={project.key}
                        type="button"
                        onClick={() => {
                          setExpandedProjectKeys(current => new Set(current).add(project.key))
                          setSidebarCollapsed(false)
                        }}
                        title={project.name}
                        className={[
                          'flex h-10 w-10 items-center justify-center rounded-lg border text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]',
                          active
                            ? 'border-[var(--ring)] bg-[var(--background)] text-[var(--foreground)]'
                            : 'border-transparent text-[var(--muted-foreground)] hover:border-[var(--border)] hover:bg-[var(--background)]',
                        ].join(' ')}
                      >
                        {getProjectInitials(project.name)}
                      </button>
                    )
                  })
                )}
              </nav>
            ) : (
              <div className="space-y-2" aria-label={t('Project navigator')}>
                {creatingProject ? (
                  <form
                    className="mb-3 space-y-2 rounded-lg border border-[var(--border)] bg-[var(--background)] p-2"
                    onSubmit={event => {
                      event.preventDefault()
                      void handleCreateProject()
                    }}
                  >
                    <input
                      value={newProjectName}
                      onChange={event => setNewProjectName(event.target.value)}
                      placeholder={t('New project name')}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                      aria-label={t('New project name')}
                    />
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          setCreatingProject(false)
                          setNewProjectName('')
                        }}
                        className="rounded-lg p-2 text-[var(--muted-foreground)] hover:bg-[var(--secondary)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                        aria-label={t('Cancel new project')}
                        title={t('Cancel new project')}
                      >
                        <X className="h-4 w-4" aria-hidden="true" />
                      </button>
                      <button
                        type="submit"
                        disabled={projectBusyName === newProjectName.trim()}
                        className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-3 py-2 text-xs font-medium text-[var(--primary-foreground)] disabled:opacity-60"
                      >
                        {projectBusyName === newProjectName.trim() ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                        ) : (
                          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                        )}
                        {t('Create')}
                      </button>
                    </div>
                  </form>
                ) : (
                  <button
                    type="button"
                    onClick={() => setCreatingProject(true)}
                    className="mb-3 flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-[var(--border)] px-3 py-2 text-sm font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--background)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                  >
                    <Plus className="h-4 w-4" aria-hidden="true" />
                    {t('New Project')}
                  </button>
                )}
                {loadingJobs ? (
                  <div className="flex items-center gap-2 px-2 py-3 text-sm text-[var(--muted-foreground)]">
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    <span>{t('Loading')}</span>
                  </div>
                ) : projectTree.length === 0 ? (
                  <p className="px-2 py-3 text-sm text-[var(--muted-foreground)]">
                    {t('No projects yet. Upload or select a Knowledge Base file to start.')}
                  </p>
                ) : (
                  projectTree.map(project => {
                    const projectExpanded = expandedProjectKeys.has(project.key)
                    const projectActive = selectedTreeContext?.projectKey === project.key
                    const projectBusy = projectBusyName === project.name
                    return (
                      <div key={project.key} className="rounded-lg">
                        {renamingProjectName === project.name ? (
                          <form
                            className="flex items-center gap-2 rounded-lg bg-[var(--background)] px-2 py-2"
                            onSubmit={event => {
                              event.preventDefault()
                              void handleRenameProject(project.name)
                            }}
                          >
                            <input
                              value={projectNameDraft}
                              onChange={event => setProjectNameDraft(event.target.value)}
                              className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-sm text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                              aria-label={t('Project name')}
                            />
                            <button
                              type="submit"
                              disabled={projectBusy}
                              className="rounded-lg p-1.5 text-emerald-600 hover:bg-[var(--secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-60"
                              aria-label={t('Save project name')}
                              title={t('Save project name')}
                            >
                              {projectBusy ? (
                                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                              ) : (
                                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                              )}
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setRenamingProjectName(null)
                                setProjectNameDraft('')
                              }}
                              className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--secondary)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                              aria-label={t('Cancel rename')}
                              title={t('Cancel rename')}
                            >
                              <X className="h-4 w-4" aria-hidden="true" />
                            </button>
                          </form>
                        ) : (
                          <div
                            className={[
                              'flex items-center gap-1 rounded-lg transition-colors',
                              projectActive
                                ? 'bg-[var(--background)] text-[var(--foreground)]'
                                : 'text-[var(--foreground)] hover:bg-[var(--background)]/70',
                            ].join(' ')}
                          >
                            <button
                              type="button"
                              onClick={() => toggleProject(project.key)}
                              onDoubleClick={() => startRenameProject(project.name)}
                              className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-2 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                            >
                              {projectExpanded ? (
                                <ChevronDown
                                  className="h-4 w-4 shrink-0 text-[var(--muted-foreground)]"
                                  aria-hidden="true"
                                />
                              ) : (
                                <ChevronRight
                                  className="h-4 w-4 shrink-0 text-[var(--muted-foreground)]"
                                  aria-hidden="true"
                                />
                              )}
                              <Layers3
                                className="h-4 w-4 shrink-0 text-[var(--muted-foreground)]"
                                aria-hidden="true"
                              />
                              <span className="min-w-0 flex-1 truncate font-medium">
                                {project.name}
                              </span>
                            </button>
                            <button
                              type="button"
                              onClick={() => startRenameProject(project.name)}
                              className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--secondary)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                              aria-label={t('Rename project')}
                              title={t('Rename project')}
                            >
                              <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                            </button>
                            <button
                              type="button"
                              onClick={() => void handleDeleteProject(project.name)}
                              disabled={projectBusy}
                              className="mr-1 rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-rose-50 hover:text-rose-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-60 dark:hover:bg-rose-950/30"
                              aria-label={t('Delete project')}
                              title={t('Delete project')}
                            >
                              {projectBusy ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                              ) : (
                                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                              )}
                            </button>
                          </div>
                        )}

                        {projectExpanded ? (
                          <div className="ml-4 mt-1 space-y-3 border-l border-[var(--border)] pl-3">
                            <div>
                              <button
                                type="button"
                                onClick={() => toggleMaterials(project.key)}
                                className="mb-1 flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)] hover:bg-[var(--background)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                              >
                                {expandedMaterialsKeys.has(project.key) ? (
                                  <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
                                ) : (
                                  <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
                                )}
                                <FolderOpen className="h-3.5 w-3.5" aria-hidden="true" />
                                <span className="min-w-0 flex-1">{t('Materials')}</span>
                                <span className="rounded bg-[var(--secondary)] px-1.5 py-0.5">
                                  {project.materials.length}
                                </span>
                              </button>
                              {expandedMaterialsKeys.has(project.key) ? (
                                <div className="space-y-1">
                                  {project.materials.length > 0 ? (
                                    project.materials.map(material => (
                                      <div
                                        key={material.key}
                                        className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-[var(--muted-foreground)]"
                                        title={material.fileName}
                                      >
                                        {material.sourceKind === 'knowledge_base' ? (
                                          <Database
                                            className="h-3.5 w-3.5 shrink-0"
                                            aria-hidden="true"
                                          />
                                        ) : (
                                          <FileText
                                            className="h-3.5 w-3.5 shrink-0"
                                            aria-hidden="true"
                                          />
                                        )}
                                        <span className="min-w-0 flex-1 truncate">
                                          {material.fileName}
                                        </span>
                                      </div>
                                    ))
                                  ) : (
                                    <p className="px-2 py-1.5 text-xs text-[var(--muted-foreground)]">
                                      {t('No materials yet.')}
                                    </p>
                                  )}
                                </div>
                              ) : null}
                            </div>

                            <div>
                              <div className="mb-1 flex items-center gap-2 px-2 text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                                <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
                                <span>{t('Structure Notes')}</span>
                              </div>
                              <div className="space-y-1">
                                {project.notes.length === 0 ? (
                                  <p className="px-2 py-1.5 text-xs text-[var(--muted-foreground)]">
                                    {t('No Structure Notes yet.')}
                                  </p>
                                ) : null}
                                {project.notes.map(note => {
                                  const noteExpanded = expandedNoteKeys.has(note.key)
                                  const noteActive = selectedTreeContext?.noteKey === note.key
                                  return (
                                    <div key={note.key}>
                                      <button
                                        type="button"
                                        onClick={() => toggleNote(note.key)}
                                        className={[
                                          'flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]',
                                          noteActive
                                            ? 'bg-[var(--background)] text-[var(--foreground)]'
                                            : 'text-[var(--foreground)] hover:bg-[var(--background)]/70',
                                        ].join(' ')}
                                      >
                                        {noteExpanded ? (
                                          <ChevronDown
                                            className="mt-0.5 h-4 w-4 shrink-0 text-[var(--muted-foreground)]"
                                            aria-hidden="true"
                                          />
                                        ) : (
                                          <ChevronRight
                                            className="mt-0.5 h-4 w-4 shrink-0 text-[var(--muted-foreground)]"
                                            aria-hidden="true"
                                          />
                                        )}
                                        <span className="min-w-0 flex-1">
                                          <span className="block truncate text-sm font-medium">
                                            {note.title}
                                          </span>
                                          <span className="mt-0.5 block truncate text-xs text-[var(--muted-foreground)]">
                                            {note.sourceFileName}
                                          </span>
                                        </span>
                                        <StatusIcon status={note.latestJob.status} />
                                      </button>

                                      {noteExpanded ? (
                                        <div className="ml-6 mt-1 space-y-1 border-l border-[var(--border)] pl-2">
                                          {note.versions.map(version => {
                                            const active = version.job.job_id === selectedJobId
                                            return (
                                              <button
                                                key={version.job.job_id}
                                                type="button"
                                                onClick={() => selectJob(version.job)}
                                                className={[
                                                  'flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]',
                                                  active
                                                    ? 'border border-[var(--ring)] bg-[var(--background)] text-[var(--foreground)]'
                                                    : 'border border-transparent text-[var(--muted-foreground)] hover:border-[var(--border)] hover:bg-[var(--background)]/70',
                                                ].join(' ')}
                                              >
                                                <StatusIcon status={version.job.status} />
                                                <span className="min-w-0 flex-1">
                                                  <span className="font-medium">
                                                    {version.label}
                                                  </span>
                                                  {version.isLatest ? (
                                                    <span className="ml-1 rounded bg-[var(--secondary)] px-1.5 py-0.5">
                                                      {t('latest')}
                                                    </span>
                                                  ) : null}
                                                  {active ? (
                                                    <span className="ml-1 rounded bg-[var(--primary)] px-1.5 py-0.5 text-[var(--primary-foreground)]">
                                                      {t('current')}
                                                    </span>
                                                  ) : null}
                                                  <span className="mt-1 block truncate">
                                                    {t(STATUS_LABELS[version.job.status])} ·{' '}
                                                    {formatTimestamp(version.job.updated_at)}
                                                  </span>
                                                </span>
                                              </button>
                                            )
                                          })}
                                        </div>
                                      ) : null}
                                    </div>
                                  )
                                })}
                              </div>
                            </div>
                          </div>
                        ) : null}
                      </div>
                    )
                  })
                )}
              </div>
            )}
          </div>
        </div>
      </aside>

      <section className="min-h-0 overflow-y-auto">
        <div className="mx-auto flex min-h-full w-full max-w-7xl flex-col gap-8 px-5 py-6 lg:px-8">
          <section
            aria-labelledby="structure-note-upload-title"
            className="grid gap-6 border border-[var(--border)] bg-[var(--background)] p-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]"
          >
            <div className="space-y-4">
              <div>
                <h2
                  id="structure-note-upload-title"
                  className="text-base font-semibold text-[var(--foreground)]"
                >
                  {t('Add Material & Configure')}
                </h2>
                <p className="mt-1 max-w-2xl text-sm text-[var(--muted-foreground)]">
                  {t(
                    'Upload a local file or select one file from Knowledge Base, then generate a versioned lecture note under its project.'
                  )}
                </p>
              </div>

                <div className="space-y-2">
                  <label
                    htmlFor="structure-note-target-project"
                    className="text-sm font-medium text-[var(--foreground)]"
                  >
                    {t('Target Project')}
                  </label>
                  <select
                    id="structure-note-target-project"
                    value={targetProjectName}
                    onChange={event => setTargetProjectName(event.target.value)}
                    disabled={projectTree.length === 0}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-60"
                  >
                    {projectTree.length === 0 ? (
                      <option value="">
                        {sourceMode === 'knowledge_base'
                          ? t('A project will be created from the selected Knowledge Base.')
                          : t('Local Uploads will be created automatically.')}
                      </option>
                    ) : (
                      projectTree.map(project => (
                        <option key={project.key} value={project.name}>
                          {project.name}
                        </option>
                      ))
                    )}
                  </select>
                  <p className="text-xs text-[var(--muted-foreground)]">
                    {t('New files and KB selections are added to this project.')}
                  </p>
                </div>

              {sourceMode === 'upload' ? (
                <div className="space-y-2">
                  <label
                    htmlFor="structure-note-file"
                    className="text-sm font-medium text-[var(--foreground)]"
                  >
                    {t('Course File')}
                  </label>
                  <div className="flex flex-col gap-3 border border-dashed border-[var(--border)] p-4">
                    <input
                      id="structure-note-file"
                      name="structure_note_file"
                      type="file"
                      accept=".pdf,.ppt,.pptx,application/pdf,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation"
                      onChange={event => setSelectedFile(event.target.files?.[0] ?? null)}
                      className="block w-full text-sm text-[var(--muted-foreground)] file:mr-4 file:rounded-lg file:border-0 file:bg-[var(--secondary)] file:px-3 file:py-2 file:text-sm file:font-medium file:text-[var(--foreground)] hover:file:bg-[var(--muted)] focus-visible:outline-none"
                      aria-describedby="structure-note-file-help"
                    />
                    <p
                      id="structure-note-file-help"
                      className="text-xs text-[var(--muted-foreground)]"
                    >
                      {selectedFile
                        ? `${selectedFile.name} · ${formatFileSize(selectedFile.size)}`
                        : t('Accepted formats: PDF, PPT, PPTX')}
                    </p>
                  </div>
                </div>
              ) : (
                <div className="grid gap-3 border border-dashed border-[var(--border)] p-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <label
                      htmlFor="structure-note-kb"
                      className="text-sm font-medium text-[var(--foreground)]"
                    >
                      {t('Knowledge Base')}
                    </label>
                    <select
                      id="structure-note-kb"
                      value={selectedKbName}
                      onChange={event => setSelectedKbName(event.target.value)}
                      disabled={loadingKbFiles || kbGroups.length === 0}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-60"
                    >
                      {kbGroups.length === 0 ? (
                        <option value="">{loadingKbFiles ? t('Loading') : t('No Knowledge Base files available.')}</option>
                      ) : (
                        kbGroups.map(group => (
                          <option key={group.kb_name} value={group.kb_name}>
                            {group.kb_name}
                          </option>
                        ))
                      )}
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label
                      htmlFor="structure-note-kb-file"
                      className="text-sm font-medium text-[var(--foreground)]"
                    >
                      {t('Knowledge Base File')}
                    </label>
                    <select
                      id="structure-note-kb-file"
                      value={selectedKbFileId}
                      onChange={event => setSelectedKbFileId(event.target.value)}
                      disabled={!selectedKbGroup || selectedKbGroup.files.length === 0}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-60"
                    >
                      {!selectedKbGroup || selectedKbGroup.files.length === 0 ? (
                        <option value="">{t('No files in this Knowledge Base.')}</option>
                      ) : (
                        selectedKbGroup.files.map(file => (
                          <option key={file.file_id} value={file.file_id}>
                            {file.display_path}
                          </option>
                        ))
                      )}
                    </select>
                  </div>

                  <p className="text-xs leading-5 text-[var(--muted-foreground)] sm:col-span-2">
                    {selectedKbFile
                      ? `${selectedKbFile.file_name} · ${formatFileSize(selectedKbFile.size_bytes)} · ${t('Project will use the selected Knowledge Base name automatically.')}`
                      : t(
                          'Only the selected file is used for Structure Note; the Knowledge Base index is unchanged.'
                        )}
                  </p>
                </div>
              )}

              <fieldset className="space-y-3">
                <legend className="text-sm font-medium text-[var(--foreground)]">
                  {t('Note Language')}
                </legend>
                <div className="grid gap-3 sm:grid-cols-2">
                  {NOTE_LANGUAGE_OPTIONS.map(option => (
                    <label
                      key={option.value}
                      className={[
                        'flex cursor-pointer flex-col gap-2 rounded-lg border p-3 transition-colors focus-within:ring-2 focus-within:ring-[var(--ring)]',
                        noteLanguage === option.value
                          ? 'border-[var(--ring)] bg-[var(--secondary)]/55'
                          : 'border-[var(--border)] hover:bg-[var(--secondary)]/35',
                      ].join(' ')}
                    >
                      <span className="flex items-center gap-2">
                        <input
                          type="radio"
                          name="structure-note-language"
                          value={option.value}
                          checked={noteLanguage === option.value}
                          onChange={() => setNoteLanguage(option.value)}
                          className="h-4 w-4 border-[var(--border)] text-[var(--primary)] focus:ring-[var(--ring)]"
                        />
                        <span className="text-sm font-medium text-[var(--foreground)]">
                          {t(option.labelKey)}
                        </span>
                      </span>
                      <span className="text-xs text-[var(--muted-foreground)]">
                        {t(option.hintKey)}
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <fieldset className="space-y-3">
                <legend className="text-sm font-medium text-[var(--foreground)]">
                  {t('Explanation Depth')}
                </legend>
                <div className="grid gap-3 sm:grid-cols-3">
                  {DIFFICULTY_OPTIONS.map(option => (
                    <label
                      key={option.value}
                      className={[
                        'flex cursor-pointer flex-col gap-2 rounded-lg border p-3 transition-colors focus-within:ring-2 focus-within:ring-[var(--ring)]',
                        difficulty === option.value
                          ? 'border-[var(--ring)] bg-[var(--secondary)]/55'
                          : 'border-[var(--border)] hover:bg-[var(--secondary)]/35',
                      ].join(' ')}
                    >
                      <span className="flex items-center gap-2">
                        <input
                          type="radio"
                          name="structure-note-difficulty"
                          value={option.value}
                          checked={difficulty === option.value}
                          onChange={() => setDifficulty(option.value)}
                          className="h-4 w-4 border-[var(--border)] text-[var(--primary)] focus:ring-[var(--ring)]"
                        />
                        <span className="text-sm font-medium text-[var(--foreground)]">
                          {t(option.labelKey)}
                        </span>
                      </span>
                      <span className="text-xs text-[var(--muted-foreground)]">
                        {t(option.hintKey)}
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <fieldset className="space-y-3">
                <legend className="text-sm font-medium text-[var(--foreground)]">
                  {t('Lecture Style Level')}
                </legend>
                <div className="grid gap-3 sm:grid-cols-3">
                  {STYLE_LEVEL_OPTIONS.map(option => (
                    <label
                      key={option.value}
                      className={[
                        'flex cursor-pointer flex-col gap-2 rounded-lg border p-3 transition-colors focus-within:ring-2 focus-within:ring-[var(--ring)]',
                        styleLevel === option.value
                          ? 'border-[var(--ring)] bg-[var(--secondary)]/55'
                          : 'border-[var(--border)] hover:bg-[var(--secondary)]/35',
                      ].join(' ')}
                    >
                      <span className="flex items-center gap-2">
                        <input
                          type="radio"
                          name="structure-note-style-level"
                          value={option.value}
                          checked={styleLevel === option.value}
                          onChange={() => setStyleLevel(option.value)}
                          className="h-4 w-4 border-[var(--border)] text-[var(--primary)] focus:ring-[var(--ring)]"
                        />
                        <span className="text-sm font-medium text-[var(--foreground)]">
                          {t(option.labelKey)}
                        </span>
                      </span>
                      <span className="text-xs text-[var(--muted-foreground)]">
                        {t(option.hintKey)}
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  onClick={handleCreate}
                  loading={submitting}
                  disabled={createDisabled}
                  icon={<Upload className="h-4 w-4" aria-hidden="true" />}
                  aria-label={t('Generate Structure Note')}
                >
                  {t('Generate Structure Note')}
                </Button>
                <span className="text-xs text-[var(--muted-foreground)]">
                  {t('Each generation creates a new version under the matching Structure Note.')}
                </span>
              </div>
            </div>

            <div
              aria-live="polite"
              className="border border-[var(--border)] bg-[var(--secondary)]/28 p-4"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-base font-semibold text-[var(--foreground)]">
                    {t('Current Version')}
                  </h2>
                  <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                    {selectedJob
                      ? `${getNoteTitle(selectedJob)} · ${t(STATUS_LABELS[selectedJob.status])}`
                      : t('Select or create a note version to see progress and results.')}
                  </p>
                  {selectedJob ? (
                    <div className="mt-2 space-y-1 text-xs text-[var(--muted-foreground)]">
                      <p>
                        {t('Project')}: {getProjectName(selectedJob)} · {t('Source')}:{' '}
                        {getSourceFileName(selectedJob)}
                      </p>
                      <p>
                        {t('Version')}:{' '}
                        {selectedTreeContext?.versionLabel ?? selectedJob.job_id.slice(-6)}
                        {selectedTreeContext?.isLatest ? ` · ${t('latest')}` : ''} ·{' '}
                        {t('Difficulty')}: {selectedJob.difficulty_level} · {t('Note Language')}:{' '}
                        {t(selectedJob.note_language === 'zh' ? 'Chinese' : 'English')} ·{' '}
                        {t('Lecture Style Level')}:{' '}
                        {t(
                          STYLE_LEVEL_OPTIONS.find(
                            option => option.value === selectedJob.style_level
                          )?.labelKey || selectedJob.style_level
                        )}
                      </p>
                    </div>
                  ) : null}
                </div>
                {selectedJob && selectedJob.status === 'failed' ? (
                  <Button
                    type="button"
                    variant="secondary"
                    loading={retrying}
                    icon={<RefreshCcw className="h-4 w-4" aria-hidden="true" />}
                    onClick={handleRetry}
                    aria-label={t('Retry failed job')}
                  >
                    {t('Retry')}
                  </Button>
                ) : null}
              </div>

              {selectedJob ? (
                <div className="mt-5 space-y-4">
                  <div>
                    <div className="mb-2 flex items-center justify-between text-xs text-[var(--muted-foreground)]">
                      <span>{t('Status')}</span>
                      <span className="inline-flex items-center gap-1">
                        <StatusIcon status={selectedJob.status} />
                        {t(STATUS_LABELS[selectedJob.status])}
                      </span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-[var(--border)]">
                      <div
                        className={[
                          'h-full rounded-full bg-[var(--primary)] transition-[width] duration-300',
                          selectedJob.status === 'failed' ? 'bg-[var(--destructive)]' : '',
                          selectedJob.status === 'ready' ? 'bg-emerald-600' : '',
                        ].join(' ')}
                        style={{ width: `${getStatusProgress(selectedJob.status)}%` }}
                      />
                    </div>
                  </div>

                  {selectedJob.error ? (
                    <div className="flex gap-3 border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-300">
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                      <span>{selectedJob.error}</span>
                    </div>
                  ) : null}

                  <div>
                    <div className="mb-2 flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
                      {PROCESSING_STATUSES.has(selectedJob.status) ? (
                        <Loader2
                          className="h-4 w-4 animate-spin text-[var(--primary)]"
                          aria-hidden="true"
                        />
                      ) : (
                        <ScrollText
                          className="h-4 w-4 text-[var(--muted-foreground)]"
                          aria-hidden="true"
                        />
                      )}
                      <span>{t('Recent Logs')}</span>
                    </div>
                    <ul className="max-h-48 space-y-2 overflow-y-auto border border-[var(--border)] bg-[var(--background)] p-3 text-xs text-[var(--muted-foreground)]">
                      {logs.length > 0 ? (
                        logs.map((line, index) => (
                          <li key={`${line}-${index}`} className="break-words">
                            {line}
                          </li>
                        ))
                      ) : (
                        <li>{t('Logs will appear here while the job is running.')}</li>
                      )}
                    </ul>
                  </div>
                </div>
              ) : null}
            </div>
          </section>

          <section className="min-h-0 border border-[var(--border)] bg-[var(--background)]">
            <div className="flex flex-col gap-4 border-b border-[var(--border)] px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h2 className="text-base font-semibold text-[var(--foreground)]">
                  {t('Online Lecture Note')}
                </h2>
                <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                  {selectedJob?.rendered_markdown_url
                    ? t(
                        'Read the Markdown note with section navigation, page grounding, and export links.'
                      )
                    : t('The Markdown lecture note will appear here when generation finishes.')}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {markdownText ? (
                  <Button
                    type="button"
                    variant="secondary"
                    icon={
                      editingMarkdown ? (
                        <Eye className="h-4 w-4" aria-hidden="true" />
                      ) : (
                        <Pencil className="h-4 w-4" aria-hidden="true" />
                      )
                    }
                    onClick={() => setEditingMarkdown(value => !value)}
                    aria-label={editingMarkdown ? t('Preview Markdown') : t('Edit Markdown')}
                  >
                    {editingMarkdown ? t('Preview') : t('Edit')}
                  </Button>
                ) : null}
                {selectedMarkdownUrl ? (
                  <a
                    href={selectedMarkdownUrl}
                    download
                    className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                  >
                    <Download className="h-4 w-4" aria-hidden="true" />
                    {t('Download MD')}
                  </a>
                ) : null}
                {selectedPdfUrl ? (
                  <a
                    href={selectedPdfUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                  >
                    <FileText className="h-4 w-4" aria-hidden="true" />
                    {t('Download PDF')}
                  </a>
                ) : null}
              </div>
            </div>

            {selectedJob?.rendered_markdown_url ? (
              <div className="grid min-h-[640px] lg:grid-cols-[280px_minmax(0,1fr)]">
                <aside className="border-b border-[var(--border)] bg-[var(--secondary)]/20 lg:border-b-0 lg:border-r">
                  <div className="sticky top-0 max-h-[640px] overflow-y-auto px-4 py-4">
                    <div className="mb-3 flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
                      <ListTree
                        className="h-4 w-4 text-[var(--muted-foreground)]"
                        aria-hidden="true"
                      />
                      <span>{t('Sections & Pages')}</span>
                    </div>
                    {selectedJob.sections?.length ? (
                      <nav aria-label={t('Structure Note sections')} className="space-y-1">
                        {selectedJob.sections.map(section => (
                          <button
                            key={section.section_id}
                            type="button"
                            onClick={() => scrollToSection(section.section_id)}
                            className="w-full rounded-lg px-3 py-2 text-left text-sm text-[var(--foreground)] transition-colors hover:bg-[var(--background)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                            style={{ paddingLeft: `${12 + Math.max(0, section.level - 2) * 14}px` }}
                          >
                            <span className="block font-medium leading-5">{section.title}</span>
                            <span className="mt-1 block text-xs text-[var(--muted-foreground)]">
                              {formatPageRange(section.page_start, section.page_end)}
                            </span>
                          </button>
                        ))}
                      </nav>
                    ) : (
                      <p className="text-sm text-[var(--muted-foreground)]">
                        {t('Section navigation will appear after planning completes.')}
                      </p>
                    )}
                  </div>
                </aside>

                <div className="min-w-0">
                  {markdownLoading ? (
                    <div className="flex min-h-[560px] items-center justify-center gap-2 text-sm text-[var(--muted-foreground)]">
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                      <span>{t('Loading Markdown note')}</span>
                    </div>
                  ) : markdownError ? (
                    <div className="m-5 flex gap-3 border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-300">
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                      <span>{markdownError}</span>
                    </div>
                  ) : editingMarkdown ? (
                    <textarea
                      value={markdownText}
                      onChange={event => setMarkdownText(event.target.value)}
                      className="min-h-[620px] w-full resize-y border-0 bg-[var(--background)] p-5 font-mono text-sm leading-6 text-[var(--foreground)] outline-none"
                      aria-label={t('Markdown source')}
                    />
                  ) : (
                    <article className="mx-auto max-w-4xl px-5 py-6 lg:px-8">
                      <RichMarkdownRenderer
                        content={displayMarkdown}
                        variant="prose"
                        enableMath
                        enableCode
                        enableMermaid
                        allowHtml
                      />
                    </article>
                  )}
                </div>
              </div>
            ) : (
              <div className="flex min-h-[440px] flex-col items-center justify-center gap-3 px-6 text-center text-sm text-[var(--muted-foreground)]">
                <FileText className="h-10 w-10 text-[var(--border)]" aria-hidden="true" />
                <p>{t('No lecture note yet.')}</p>
                <p>
                  {t(
                    'Upload a file, select a Knowledge Base file, or wait for the current version to finish rendering.'
                  )}
                </p>
              </div>
            )}
          </section>

          <section className="border border-[var(--border)] bg-[var(--background)]">
            <div className="border-b border-[var(--border)] px-5 py-4">
              <h2 className="text-base font-semibold text-[var(--foreground)]">{t('Grounding')}</h2>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                {t(
                  'Each entry tracks the section path and source page range used in the exported note.'
                )}
              </p>
            </div>
            <div className="max-h-[420px] overflow-y-auto px-4 py-4">
              {selectedJob?.citations?.length ? (
                <ol className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {selectedJob.citations.map(citation => (
                    <li
                      key={citation.citation_id}
                      className="rounded-lg border border-[var(--border)] bg-[var(--secondary)]/24 p-3"
                    >
                      <p className="text-sm font-medium text-[var(--foreground)]">
                        {citation.section_path?.length
                          ? citation.section_path.join(' / ')
                          : t('Unlabeled section')}
                      </p>
                      <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                        {citation.source_kind === 'image' ? t('Image') : t('Text')} · {t('Pages')}{' '}
                        {citation.page_start}
                        {citation.page_end !== citation.page_start ? `-${citation.page_end}` : ''}
                      </p>
                      {citation.excerpt ? (
                        <p className="mt-2 text-xs leading-6 text-[var(--muted-foreground)] break-words">
                          {citation.excerpt}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-sm text-[var(--muted-foreground)]">
                  {t('Citation entries will appear here when a job completes.')}
                </p>
              )}
            </div>
          </section>

          {pageError ? (
            <div
              role="alert"
              className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-300"
            >
              {pageError}
            </div>
          ) : null}
        </div>
      </section>
    </div>
  )
}
